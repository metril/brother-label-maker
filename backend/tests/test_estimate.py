"""Tests for labelmaker.render.estimate: the tape-usage model behind
POST /api/print/estimate and the per-job tape_used_mm figure.

All expected totals below are hand-computed (see the derivation comment
above each case), never obtained by calling estimate() and asserting it
matches itself -- the whole point of this file is to catch a wrong constant
or a wrong formula, not merely pin whatever the code currently does.

Model recap (see estimate.py's module docstring for full provenance):
  MIN_FEED_MM = 24.5 (geometry.MIN_FEED_MM -- mechanical head-to-cutter gap,
  docs/research/features.md).
  - cut_each: each label is its own job -> per label, tape used is
    max(label_len + 2*margin_mm, MIN_FEED_MM); overhead = total - content.
  - chain_ff: ONE job-level preamble for the whole chain (job.py's
    _build_chained emits strategy.preamble() exactly once for CHAIN_FF, not
    per page) -> margin is consumed once for the whole job, not once per
    label. total = content_mm + 2*margin_mm + MIN_FEED_MM (one trailing
    feed/cut). This corrects the brief's own literal "margin per label"
    draft -- see estimate.py's docstring for the full justification (the
    brief flags this branch UNVERIFIED and explicitly invites correction).
  - strip_marks: single page, single preamble (job.py's _build_strip_marks
    also emits the preamble exactly once) -> content_mm + cut-mark gap/dash/
    gap column mm (job.py's default cut_mark_gap=4/cut_mark_width=4, (n-1)
    separators between n labels) + one MIN_FEED_MM. No margin term (the
    brief's formula for this branch, unflagged, is followed literally).
"""

import pytest

from labelmaker.driver.geometry import MIN_FEED_MM, dots_to_mm
from labelmaker.driver.job import JobOptions
from labelmaker.render.estimate import TapeEstimate, estimate

# --- 0. Sanity: estimate.py's hardcoded cut-mark gap/width constants must
# stay in lockstep with driver.job.JobOptions' own defaults (estimate.py
# can't import driver.job itself -- render/ only imports driver.geometry,
# see render/__init__.py's module docstring -- so the two constants are
# independently maintained; this test is the drift guard).


def test_default_cut_mark_dimensions_match_job_options_defaults():
    defaults = JobOptions()
    assert defaults.cut_mark_gap == 4
    assert defaults.cut_mark_width == 4


# --- 1. Single short label -> MIN_FEED floor, in every mode ---------------


def test_cut_each_single_short_label_hits_min_feed_floor():
    result = estimate([5.0], chain_mode="cut_each", margin_mm=2.0)
    assert isinstance(result, TapeEstimate)
    # 5 + 2*2 = 9 < 24.5 -> floor applies.
    assert result.total_mm == pytest.approx(24.5)
    assert result.content_mm == pytest.approx(5.0)
    assert result.feed_overhead_mm == pytest.approx(19.5)
    assert result.per_label_mm == pytest.approx(24.5)
    assert result.label_lengths_mm == [5.0]
    assert result.notes  # a note explaining the floor is present


def test_chain_ff_single_short_label():
    # content=5, +2*margin(2*2=4) once, +MIN_FEED_MM once = 5+4+24.5=33.5.
    result = estimate([5.0], chain_mode="chain_ff", margin_mm=2.0)
    assert result.total_mm == pytest.approx(33.5)
    assert result.content_mm == pytest.approx(5.0)
    assert result.feed_overhead_mm == pytest.approx(28.5)
    assert result.per_label_mm == pytest.approx(33.5)


def test_strip_marks_single_label_no_mark_columns():
    # n=1 -> zero gap/dash/gap separators -> total = content + MIN_FEED_MM.
    result = estimate([5.0], chain_mode="strip_marks", margin_mm=2.0)
    assert result.total_mm == pytest.approx(5.0 + MIN_FEED_MM)
    assert result.feed_overhead_mm == pytest.approx(MIN_FEED_MM)


# --- 2. 8x20mm cut_each vs chain_ff savings --------------------------------


def test_cut_each_8x20mm_hand_computed():
    lengths = [20.0] * 8
    result = estimate(lengths, chain_mode="cut_each", margin_mm=2.0)
    # per label: max(20 + 2*2, 24.5) = max(24, 24.5) = 24.5 -> total = 8*24.5 = 196.0
    assert result.total_mm == pytest.approx(196.0)
    assert result.content_mm == pytest.approx(160.0)
    assert result.feed_overhead_mm == pytest.approx(36.0)
    assert result.per_label_mm == pytest.approx(24.5)


def test_chain_ff_8x20mm_hand_computed():
    lengths = [20.0] * 8
    result = estimate(lengths, chain_mode="chain_ff", margin_mm=2.0)
    # content=160, +2*margin(4) once, +MIN_FEED_MM(24.5) once = 188.5
    assert result.total_mm == pytest.approx(188.5)
    assert result.content_mm == pytest.approx(160.0)
    assert result.feed_overhead_mm == pytest.approx(28.5)


def test_chain_ff_saves_tape_vs_cut_each_for_8x20mm():
    lengths = [20.0] * 8
    cut_each = estimate(lengths, chain_mode="cut_each", margin_mm=2.0)
    chain_ff = estimate(lengths, chain_mode="chain_ff", margin_mm=2.0)
    # 196.0 - 188.5 = 7.5mm saved by chaining instead of cutting each.
    assert cut_each.total_mm - chain_ff.total_mm == pytest.approx(7.5)
    assert chain_ff.total_mm < cut_each.total_mm


def test_cut_each_note_mentions_chain_ff_savings_when_multiple_labels():
    result = estimate([20.0] * 8, chain_mode="cut_each", margin_mm=2.0)
    assert any("chain_ff" in note for note in result.notes)


# --- 3. strip_marks includes mark columns ----------------------------------


def test_strip_marks_three_labels_hand_computed():
    lengths = [15.0, 15.0, 15.0]
    result = estimate(lengths, chain_mode="strip_marks", margin_mm=2.0)
    # default cut_mark_gap=4, cut_mark_width=4 dots -> one gap+dash+gap block
    # = 2*4 + 4 = 12 dots, occurring (n-1)=2 times between 3 labels = 24 dots.
    mark_columns_mm = dots_to_mm(24)
    assert mark_columns_mm == pytest.approx(3.386666666666667)
    expected_total = 45.0 + mark_columns_mm + MIN_FEED_MM
    assert result.total_mm == pytest.approx(expected_total)
    assert result.content_mm == pytest.approx(45.0)
    assert result.feed_overhead_mm == pytest.approx(mark_columns_mm + MIN_FEED_MM)
    assert any("cut-mark" in note or "mark" in note for note in result.notes)


def test_strip_marks_mark_columns_scale_with_label_count():
    # More labels -> more (n-1) separators -> strictly more mark-column mm,
    # independent of the monotonicity-in-content check below.
    two = estimate([15.0, 15.0], chain_mode="strip_marks", margin_mm=2.0)
    four = estimate([15.0, 15.0, 15.0, 15.0], chain_mode="strip_marks", margin_mm=2.0)
    two_overhead_minus_floor = two.feed_overhead_mm - MIN_FEED_MM
    four_overhead_minus_floor = four.feed_overhead_mm - MIN_FEED_MM
    assert four_overhead_minus_floor > two_overhead_minus_floor


# --- 4. Monotonicity: more labels -> more tape, in every mode --------------


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
def test_more_labels_means_more_tape(chain_mode):
    smaller = estimate([12.0, 12.0], chain_mode=chain_mode, margin_mm=2.0)
    bigger = estimate([12.0, 12.0, 12.0], chain_mode=chain_mode, margin_mm=2.0)
    assert bigger.total_mm > smaller.total_mm


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
def test_longer_labels_means_more_tape(chain_mode):
    smaller = estimate([12.0, 12.0], chain_mode=chain_mode, margin_mm=2.0)
    bigger = estimate([40.0, 40.0], chain_mode=chain_mode, margin_mm=2.0)
    assert bigger.total_mm > smaller.total_mm


# --- 5. Structural invariants -----------------------------------------------


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
def test_per_label_mm_is_total_over_count(chain_mode):
    lengths = [10.0, 30.0, 50.0]
    result = estimate(lengths, chain_mode=chain_mode, margin_mm=2.0)
    assert result.per_label_mm == pytest.approx(result.total_mm / len(lengths))


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
def test_feed_overhead_is_total_minus_content(chain_mode):
    lengths = [10.0, 30.0, 50.0]
    result = estimate(lengths, chain_mode=chain_mode, margin_mm=2.0)
    assert result.feed_overhead_mm == pytest.approx(result.total_mm - result.content_mm)


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
def test_notes_are_always_present(chain_mode):
    result = estimate([10.0, 30.0], chain_mode=chain_mode, margin_mm=2.0)
    assert len(result.notes) >= 1
    assert all(isinstance(n, str) and n for n in result.notes)


def test_label_lengths_mm_echoed_verbatim_and_content_mm_is_their_sum():
    lengths = [10.0, 30.0, 50.5]
    result = estimate(lengths, chain_mode="cut_each", margin_mm=2.0)
    assert result.label_lengths_mm == lengths
    assert result.content_mm == pytest.approx(sum(lengths))


# --- 6. Validation -----------------------------------------------------------


def test_estimate_empty_labels_raises():
    with pytest.raises(ValueError):
        estimate([], chain_mode="cut_each", margin_mm=2.0)


def test_estimate_unknown_chain_mode_raises():
    with pytest.raises(ValueError):
        estimate([10.0], chain_mode="not_a_real_mode", margin_mm=2.0)


def test_estimate_accepts_chain_mode_enum_instance():
    # driver.protocol.ChainMode is str-valued (Task 1.3a) -- callers (e.g.
    # api/router_print.py) may pass either the enum member or its plain
    # string value; both must work identically since estimate.py itself
    # never imports driver.protocol (render/ only imports driver.geometry).
    from labelmaker.driver.protocol import ChainMode

    by_enum = estimate([10.0], chain_mode=ChainMode.CUT_EACH, margin_mm=2.0)
    by_str = estimate([10.0], chain_mode="cut_each", margin_mm=2.0)
    assert by_enum.total_mm == by_str.total_mm
