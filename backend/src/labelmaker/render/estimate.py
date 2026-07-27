"""Tape-usage estimator: how much physical tape a print job will actually
consume, before it prints.

This is the tape-saving payoff behind Task 2.9's chain-mode wiring: chaining
labels together (chain_ff) or ganging them onto one strip with cut marks
(strip_marks) avoids re-paying the mechanical head-to-cutter feed floor for
every single label the way cut_each does. Surfacing that difference to the
user (POST /api/print/estimate) is the point of this module.

Only imports labelmaker.driver.geometry (MIN_FEED_MM, dots_to_mm) -- render/
never imports the rest of labelmaker.driver (see render/__init__.py's module
docstring); ChainMode therefore isn't imported here either. `chain_mode` is
accepted as a plain string -- driver.protocol.ChainMode is a str-valued enum
(Task 1.3a), so passing a ChainMode member works identically to passing its
`.value` (see test_estimate.py's test_estimate_accepts_chain_mode_enum_instance).

EVERY branch below is UNVERIFIED pending the physical checkpoint. Two
competing sources feed this model and they don't fully agree with each
other -- see each branch for which one this implementation follows and why:

  (A) docs/research/features.md:16 -- the mechanical spec: content shorter
      than 24.5mm still only consumes 24.5mm total (a FLOOR/max() reading).
  (B) docs/research/features.md:18 -- a Brother consumer FAQ, measuring
      REAL cut/chain modes: "Small Margin and Chain modes... ~22.6mm leader
      PLUS only ~4mm side margins PER LABEL" -- leader is described as
      ADDITIVE waste on top of a label's own content, not a floor, and
      "per label" even for chain-ish modes.
  (C) docs/research/features.md:44 -- the RECOMMENDATIONS section, written
      specifically for "cost-estimate math" (this exact feature): "23-25mm
      leader once per chained job, vs ~24-26mm+cut-margin per label when
      chaining is unavailable" -- ADDITIVE per-label leader for
      chaining-unavailable (cut_each), ONCE-per-job leader for chaining.

(A) and (B)/(C) disagree on whether the per-label figure is a floor or an
addition; (B) and (C) also don't cleanly say whether "Chain" there means
this project's chain_ff (a persistent ESC i K/ESC i d SETTING covering the
whole job) or something closer to strip_marks. None of this is settled by
reading the spec -- it needs the physical checkpoint to actually measure.

Model, one term at a time (constants documented with their provenance):

- MIN_FEED_MM = 24.5mm (geometry.MIN_FEED_MM): the mechanical head-to-cutter
  gap -- confirmed by Brother's own raster manual AND independently
  corroborated by the consumer FAQ above. The NUMBER itself is
  well-sourced and not in question; what's UNVERIFIED is how it combines
  with content/margin per-label vs per-job in each mode below.

- cut_each: every label is its own independent job (job.py's _build_chained
  CUT_EACH branch: fresh preamble + page_header + page_end per image, its
  own feed/cut every time). This model follows reading (C) -- see
  features.md:44's own "cost-estimate math" guidance -- and treats
  MIN_FEED_MM as an ADDITIVE per-label leader, not a floor:
      per_label = label_len_mm + 2*margin_mm + MIN_FEED_MM
  summed over labels. This is symmetric with chain_ff's formula below
  (same three terms), just evaluated once per label instead of once for
  the whole job -- matching cut_each's own preamble/margin emission being
  literally once per label in job.py's real CUT_EACH code path (unlike
  chain_ff, which shares ONE preamble across the whole chain -- see
  chain_ff below). UNVERIFIED: reading (A) would instead treat MIN_FEED_MM
  as a floor here (`max(label_len + 2*margin, MIN_FEED_MM)`), which a
  short label could satisfy without any additive leader at all -- that
  reading was this module's FIRST implementation, and was replaced because
  it produced cut_each estimates LOWER than chain_ff/strip_marks for
  labels roughly >=20mm (e.g. 4 labels at 60mm, 2 at 100mm), i.e. it told
  users cutting each label separately saves tape versus chaining --
  backwards from the entire premise of a chain-mode tape-saving feature,
  and inconsistent with reading (C)'s own explicit "cost-estimate math"
  instruction. See test_estimate.py's test_chain_ff_beats_cut_each_for_* for
  the cases this resolves. To be confirmed (or corrected back toward (A))
  at the physical checkpoint.

- chain_ff: job.py's _build_chained CHAIN_FF branch emits `strategy.
  preamble(...)` -- which is where margin (ESC i d) gets set -- exactly
  ONCE for the whole chain, not once per page (see strategies.py:
  ClassicStrategy.preamble/E310BTStrategy.preamble, called a single time
  before the per-page loop in job.py). This model treats margin as
  consumed once for the whole job, not per label:
      total = content_mm + 2*margin_mm + MIN_FEED_MM
  (one job-wide margin allowance, one trailing feed/cut).

  This is ONE of two competing UNVERIFIED hypotheses, not a settled fact:
    - "once per job" (what this model implements): ESC i K/ESC i d are
      emitted exactly once in job.py's CHAIN_FF preamble -- a software-level
      observation about how many times the BYTES are sent, which is
      suggestive but does NOT by itself establish the printer's physical
      feed behavior for a chained job (ESC i d sets a persistent margin
      SETTING, not literally "feed N mm right now" -- how the printer
      applies that setting across a multi-page chain internally is exactly
      what's unverified).
    - "per label" (features.md:18's literal reading): the consumer FAQ
      describes "Chain" mode itself as still wasting ~22.6mm leader PLUS
      ~4mm margins PER LABEL -- i.e. even chained/low-margin printing may
      not fully avoid a per-label cost on real hardware.
  This module picks the once-per-job reading because it's the one directly
  traceable to this project's own byte-emission code (not a re-guess), and
  because features.md:44's recommendations section describes chaining's
  cost specifically as "once per chained job" -- but the FAQ evidence in
  (B) for a per-label reading is real and not resolved by either of us
  arguing about it from a spec doc. Checkpoint 2's physical measurement is
  what actually decides between these two, not this docstring.

- strip_marks: job.py's _build_strip_marks also emits the preamble exactly
  once (single page for the whole job) and separates adjacent labels with a
  gap/dash/gap block of cut-mark lines (default cut_mark_gap=4,
  cut_mark_width=4 raster lines each -- see driver.job.JobOptions; the
  constants below are hand-kept in lockstep with those defaults, not
  imported, since render/ can't import driver.job -- see
  test_estimate.py's drift-guard test). (n-1) such blocks separate n
  labels:
      total = content_mm + mark_columns_mm + MIN_FEED_MM
  No margin term (the brief's own strip_marks formula omits one, and this
  follows it literally) -- UNVERIFIED same as the other two branches;
  whether margin genuinely costs nothing extra for a single-page strip is
  untested against real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

from labelmaker.driver.geometry import MIN_FEED_MM, dots_to_mm

# Must stay in lockstep with driver.job.JobOptions' own cut_mark_gap/
# cut_mark_width defaults (4 raster lines each) -- see this module's
# docstring and test_estimate.py's drift-guard test.
_DEFAULT_CUT_MARK_GAP_DOTS = 4
_DEFAULT_CUT_MARK_WIDTH_DOTS = 4

_CUT_EACH = "cut_each"
_CHAIN_FF = "chain_ff"
_STRIP_MARKS = "strip_marks"
_VALID_CHAIN_MODES = frozenset({_CUT_EACH, _CHAIN_FF, _STRIP_MARKS})


@dataclass(frozen=True)
class TapeEstimate:
    label_lengths_mm: list[float]  # per label, as rendered (echoed verbatim)
    content_mm: float  # sum of label_lengths_mm
    feed_overhead_mm: float  # tape consumed that ISN'T label content (total - content)
    total_mm: float  # what actually gets consumed
    per_label_mm: float  # total / n -- convenience for the UI
    notes: list[str]  # human-readable explanations of the overhead


def estimate(label_lengths_mm: list[float], *, chain_mode: str, margin_mm: float) -> TapeEstimate:
    """Estimate the physical tape a job with these per-label rendered
    lengths (mm) will consume under `chain_mode`. `label_lengths_mm` must be
    non-empty (mirrors PrintRequest's own `labels` min_length=1 constraint
    at the API layer). `chain_mode` accepts either driver.protocol.
    ChainMode's plain string values or the enum member itself (it's
    str-valued -- see this module's docstring for why a plain str is used
    here instead of importing the enum type).
    """
    if not label_lengths_mm:
        raise ValueError("label_lengths_mm must be non-empty")
    if chain_mode not in _VALID_CHAIN_MODES:
        raise ValueError(
            f"unknown chain_mode {chain_mode!r}; valid values: {sorted(_VALID_CHAIN_MODES)}"
        )

    n = len(label_lengths_mm)
    content_mm = sum(label_lengths_mm)
    notes: list[str] = []

    if chain_mode == _CUT_EACH:
        # Additive per-label leader (features.md:44's "cost-estimate math"
        # reading) -- see module docstring's cut_each section for why this
        # replaced an earlier max()-floor reading. UNVERIFIED against the
        # physical printer either way.
        total_mm = sum(length + 2 * margin_mm + MIN_FEED_MM for length in label_lengths_mm)
        notes.append(
            f"UNVERIFIED: each cut-each label pays its own {MIN_FEED_MM:g}mm leader/cut "
            "allowance (features.md:44's per-label reading) in addition to its own content "
            "and margins -- to be confirmed at the physical checkpoint."
        )
        if n > 1:
            chained = estimate(label_lengths_mm, chain_mode=_CHAIN_FF, margin_mm=margin_mm)
            savings = total_mm - chained.total_mm
            if savings > 0:
                notes.append(
                    f"chaining these {n} labels (chain_ff) instead would use "
                    f"~{savings:.1f}mm less tape."
                )

    elif chain_mode == _CHAIN_FF:
        total_mm = content_mm + 2 * margin_mm + MIN_FEED_MM
        notes.append(
            f"one {MIN_FEED_MM:g}mm leader/cut allowance for the whole chained job "
            f"(vs. {n} x {MIN_FEED_MM:g}mm in cut-each mode) -- margin is set once for the "
            "whole chain, not once per label."
        )
        notes.append(
            "UNVERIFIED: whether the real printer's physical feed for a chained job matches "
            "this once-per-job software reading, or instead costs a per-label leader the way "
            "features.md:18's FAQ describes 'Chain' mode -- unconfirmed pending physical "
            "checkpoint 2; see module docstring for both competing readings."
        )

    else:  # _STRIP_MARKS
        mark_block_dots = 2 * _DEFAULT_CUT_MARK_GAP_DOTS + _DEFAULT_CUT_MARK_WIDTH_DOTS
        mark_columns_mm = dots_to_mm(mark_block_dots * max(n - 1, 0))
        total_mm = content_mm + mark_columns_mm + MIN_FEED_MM
        notes.append(
            "UNVERIFIED: no margin term is included for strip_marks (single job-wide "
            "preamble, per the brief's own formula) -- unconfirmed against the physical "
            "printer, same as the other two modes."
        )
        if n > 1:
            notes.append(
                f"{n - 1} cut-mark column(s) (~{mark_columns_mm:.1f}mm total) separate the "
                f"{n} labels sharing this single strip; one {MIN_FEED_MM:g}mm leader/cut "
                "allowance applies to the whole strip, not per label."
            )
        else:
            notes.append(
                f"a single {MIN_FEED_MM:g}mm leader/cut allowance applies; no cut-mark columns "
                "are needed for a single label."
            )

    feed_overhead_mm = total_mm - content_mm
    per_label_mm = total_mm / n

    return TapeEstimate(
        label_lengths_mm=list(label_lengths_mm),
        content_mm=content_mm,
        feed_overhead_mm=feed_overhead_mm,
        total_mm=total_mm,
        per_label_mm=per_label_mm,
        notes=notes,
    )
