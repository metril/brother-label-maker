"""Tests for labelmaker.render.estimate: the tape-usage model behind
POST /api/print/estimate and the per-job tape_used_mm figure.

All expected totals below are hand-computed (see the derivation comment
above each case), never obtained by calling estimate() and asserting it
matches itself -- the whole point of this file is to catch a wrong constant
or a wrong formula, not merely pin whatever the code currently does.

Every branch of this model is UNVERIFIED pending the physical checkpoint --
see estimate.py's module docstring for the full writeup of the two
competing, not-fully-reconciled sources feeding it:
  (A) docs/research/features.md:16 -- the mechanical spec, read as a per-job
      FLOOR (content under 24.5mm still only costs 24.5mm total).
  (B) docs/research/features.md:18 -- a Brother consumer FAQ describing
      "Small Margin/Chain" modes as ~22.6mm leader PLUS ~4mm margins PER
      LABEL -- additive, not a floor, and per-label even for chain-ish
      modes.
  (C) docs/research/features.md:44 -- the RECOMMENDATIONS section, written
      specifically for this feature's "cost-estimate math": "23-25mm
      leader once per chained job, vs ~24-26mm+cut-margin per label when
      chaining is unavailable".
Neither reading is asserted as "the" correct one here -- checkpoint 2's
physical measurement decides between them. This module currently
implements reading (C) for cut_each (additive per-label leader) and the
once-per-job reading for chain_ff (grounded in job.py's own single-preamble
CHAIN_FF code path, not a re-guess of the FAQ text) -- see below.

Model recap (see estimate.py's module docstring for the full provenance
writeup):
  MIN_FEED_MM = 24.5 (geometry.MIN_FEED_MM -- mechanical head-to-cutter gap,
  docs/research/features.md; this NUMBER is well-sourced regardless of
  which per-label/per-job reading turns out to be right).
  - cut_each: each label is its own job -> per label, tape used is
    label_len + 2*margin_mm + MIN_FEED_MM (ADDITIVE leader, reading (C)
    above) -- summed over labels; overhead = total - content. An earlier
    version of this model used a max()-floor reading (A) instead, which
    made cut_each estimate LESS tape than chain_ff/strip_marks for labels
    roughly >=20mm (e.g. 4x60mm, 2x100mm) -- backwards from the point of a
    tape-saving chain-mode feature. See
    test_chain_ff_beats_cut_each_for_common_cases below, which pins that
    this no longer happens.
  - chain_ff: ONE job-level preamble for the whole chain (job.py's
    _build_chained emits strategy.preamble() exactly once for CHAIN_FF, not
    per page) -> this model treats margin as consumed once for the whole
    job, not once per label. total = content_mm + 2*margin_mm + MIN_FEED_MM
    (one trailing feed/cut). See estimate.py's docstring for why this
    once-per-job reading was chosen over reading (B)'s per-label one, and
    why BOTH remain open questions for the physical checkpoint.
  - strip_marks: single page, single preamble (job.py's _build_strip_marks
    also emits the preamble exactly once) -> content_mm + cut-mark gap/dash/
    gap column mm (job.py's default cut_mark_gap=4/cut_mark_width=4, (n-1)
    separators between n labels) + one MIN_FEED_MM. No margin term (the
    brief's formula for this branch is followed literally).
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


# --- 1. Single short label, in every mode ----------------------------------


def test_cut_each_single_short_label_additive_leader():
    result = estimate([5.0], chain_mode="cut_each", margin_mm=2.0)
    assert isinstance(result, TapeEstimate)
    # additive leader: 5 + 2*2 + 24.5 = 33.5 (not a floor -- see module docstring).
    assert result.total_mm == pytest.approx(33.5)
    assert result.content_mm == pytest.approx(5.0)
    assert result.feed_overhead_mm == pytest.approx(28.5)
    assert result.per_label_mm == pytest.approx(33.5)
    assert result.label_lengths_mm == [5.0]
    assert result.notes  # a note explaining the leader is present


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
    # per label: 20 + 2*2 + 24.5 = 48.5 (additive leader) -> total = 8*48.5 = 388.0
    assert result.total_mm == pytest.approx(388.0)
    assert result.content_mm == pytest.approx(160.0)
    assert result.feed_overhead_mm == pytest.approx(228.0)
    assert result.per_label_mm == pytest.approx(48.5)


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
    # 388.0 - 188.5 = 199.5mm saved by chaining instead of cutting each.
    assert cut_each.total_mm - chain_ff.total_mm == pytest.approx(199.5)
    assert chain_ff.total_mm < cut_each.total_mm


def test_strip_marks_beats_cut_each_for_8x20mm():
    # The reviewer's headline counter-example under the OLD max()-floor
    # cut_each model (196.35 strip_marks vs 196.00 cut_each -- strip_marks
    # LOST): with the additive leader, cut_each is 388.0 (see
    # test_cut_each_8x20mm_hand_computed) and strip_marks is ~196.35 (see
    # test_strip_marks_three_labels_hand_computed's derivation, same
    # formula scaled to n=8) -- strip_marks now clearly wins.
    lengths = [20.0] * 8
    cut_each = estimate(lengths, chain_mode="cut_each", margin_mm=2.0)
    strip_marks = estimate(lengths, chain_mode="strip_marks", margin_mm=2.0)
    assert strip_marks.total_mm < cut_each.total_mm


@pytest.mark.parametrize(
    "lengths",
    [[60.0] * 4, [100.0] * 2, [20.0] * 8],
    ids=["4x60mm", "2x100mm", "8x20mm"],
)
def test_chain_ff_beats_cut_each_for_common_cases(lengths):
    # Pins the tape-saving claim itself for the cases the coordinator's
    # review flagged as inverted under the old max()-floor cut_each model:
    # 4x60mm (354.0 vs 268.5), 2x100mm (257.0 vs 228.5), 8x20mm (388.0 vs
    # 188.5) -- chain_ff must win every time, not just at small n.
    cut_each = estimate(lengths, chain_mode="cut_each", margin_mm=2.0)
    chain_ff = estimate(lengths, chain_mode="chain_ff", margin_mm=2.0)
    assert chain_ff.total_mm < cut_each.total_mm


def test_cut_each_note_mentions_chain_ff_savings_when_multiple_labels():
    result = estimate([20.0] * 8, chain_mode="cut_each", margin_mm=2.0)
    assert any("chain_ff" in note for note in result.notes)


def test_cut_each_note_is_marked_unverified():
    result = estimate([20.0], chain_mode="cut_each", margin_mm=2.0)
    assert any("UNVERIFIED" in note for note in result.notes)


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


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
def test_every_mode_carries_an_unverified_note(chain_mode):
    # Every branch of this model is UNVERIFIED pending the physical
    # checkpoint (see module docstring) -- not just chain_ff.
    result = estimate([10.0, 30.0], chain_mode=chain_mode, margin_mm=2.0)
    assert any("UNVERIFIED" in note for note in result.notes)


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
