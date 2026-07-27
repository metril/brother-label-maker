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

Model, one term at a time (constants documented with their provenance from
docs/research/features.md):

- MIN_FEED_MM = 24.5mm (geometry.MIN_FEED_MM): the mechanical head-to-cutter
  gap -- confirmed by Brother's own raster manual AND independently
  corroborated by a Brother consumer FAQ ("why does a one inch piece of
  blank tape feed prior to every label"). Any print, however short,
  physically consumes at least this much tape before/around the cut. NOT
  marked UNVERIFIED -- this one figure is the best-sourced number in the
  whole model.

- cut_each: every label is its own independent job (job.py's _build_chained
  CUT_EACH branch: fresh preamble + page_header + page_end per image, its
  own feed/cut every time) -- so each label pays MIN_FEED_MM independently:
  per-label tape = max(label_len_mm + 2*margin_mm, MIN_FEED_MM). Content
  narrower than the floor (plus its own two margins) still consumes the
  full 24.5mm; content wider than the floor consumes exactly its own
  length+margins, no floor waste.

- chain_ff: job.py's _build_chained CHAIN_FF branch emits `strategy.
  preamble(...)` -- which is where margin (ESC i d) gets set -- exactly
  ONCE for the whole chain, not once per page (see strategies.py:
  ClassicStrategy.preamble/E310BTStrategy.preamble, called a single time
  before the per-page loop in job.py). So this model treats margin as
  consumed once for the whole job, not per label:
      total = content_mm + 2*margin_mm + MIN_FEED_MM
  (one job-wide margin allowance, one trailing feed/cut). This DEVIATES
  from the brief's own literal draft ("margin_mm each side per label,
  since ESC i d applies per page") -- that premise is factually wrong
  against job.py's actual CHAIN_FF code path (margin is emitted once, in
  the job-level preamble; page_header only emits ESC i z, no margin bytes)
  and, taken literally, produces a chain_ff estimate that is WORSE than
  cut_each for realistic inputs (see test_estimate.py's derivation
  comment), defeating the entire point of a "tape-saving" chain mode. The
  brief itself flags this branch `# UNVERIFIED: exact chained feed
  behavior -- confirm at checkpoint 2 and correct this model`, explicitly
  inviting a correction; this is that correction, grounded in the actual
  driver code rather than re-guessed. Still UNVERIFIED against the
  physical printer (whether the printer's real mechanical feed for a
  chained job matches the single-preamble software model) -- to be
  confirmed at the physical checkpoint.

- strip_marks: job.py's _build_strip_marks also emits the preamble exactly
  once (single page for the whole job) and separates adjacent labels with a
  gap/dash/gap block of cut-mark lines (default cut_mark_gap=4,
  cut_mark_width=4 raster lines each -- see driver.job.JobOptions; the
  constants below are hand-kept in lockstep with those defaults, not
  imported, since render/ can't import driver.job -- see
  test_estimate.py's drift-guard test). (n-1) such blocks separate n
  labels. Per the (unflagged) brief formula:
      total = content_mm + mark_columns_mm + MIN_FEED_MM
  No margin term -- the brief's own strip_marks formula omits one (unlike
  chain_ff, this branch isn't flagged UNVERIFIED), so it's followed
  literally here.
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
        total_mm = sum(max(length + 2 * margin_mm, MIN_FEED_MM) for length in label_lengths_mm)
        short = sum(1 for length in label_lengths_mm if length + 2 * margin_mm < MIN_FEED_MM)
        if short:
            notes.append(
                f"{MIN_FEED_MM:g}mm minimum feed applies once per label in cut-each mode -- "
                f"{short} of {n} label(s) are shorter than that floor (content + margins) and "
                f"still consume the full {MIN_FEED_MM:g}mm each."
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
            "UNVERIFIED: exact chained feed behavior on the real printer is unconfirmed "
            "pending physical checkpoint 2 -- this estimate may need correcting once verified."
        )

    else:  # _STRIP_MARKS
        mark_block_dots = 2 * _DEFAULT_CUT_MARK_GAP_DOTS + _DEFAULT_CUT_MARK_WIDTH_DOTS
        mark_columns_mm = dots_to_mm(mark_block_dots * max(n - 1, 0))
        total_mm = content_mm + mark_columns_mm + MIN_FEED_MM
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
