"""Label type "breaker_box": electrical panel schedule labeling -- one block
per breaker, sized by how many panel positions it occupies, numbered with
real-world panel-schedule conventions. A THIN config over divided_blocks.py's
layout engine (task 2.1): this module only computes each breaker's slot
number/text and its width_multiplier, then translates into a
DividedBlocksParams (per-block-length mode: block_length_mm=pitch_mm,
multipliers=[breaker.poles, ...]); all boundary/rounding/font-fit math lives
in render_divided_blocks/layout_blocks and is not reimplemented here.

Like terminal_block.py, Brother's own software has NO wizard for this label
shape -- there is no manual page to mirror param ranges from. This module's
docstrings and Field(description=...) text ARE the spec.

-- Panel-position numbering (the part worth deriving carefully) --

A real breaker panel numbers its two columns of positions independently:
odd numbers (1, 3, 5, ...) down the left column, even numbers (2, 4, 6, ...)
down the right column, both columns read top-to-bottom in parallel. A label
strip covers ONE column, so consuming N positions in that column advances
the displayed slot number by 2*N (the other column's numbers sit in the
gaps). `numbering_scheme="sequential"` instead numbers straight down a
single column with no interleaving (every position, not every other one).

For breaker `i` (0-indexed), let `positions_consumed_before_i` be the sum of
`poles` over every EARLIER breaker (0 for the first breaker). Then:

    slot_i = start_value + increment * positions_consumed_before_i
    increment = 1 if numbering_scheme == "sequential" else 2  (odd/even)

A multi-pole breaker's displayed number is `slot_i` -- its FIRST position
only (real panel schedules print a range like "1,3" for a 2-pole breaker at
odd positions 1 and 3; v1 keeps this simple and shows just the first number,
documented here rather than silently guessed at by a caller). `poles` itself
still drives the breaker's physical WIDTH via width_multiplier (a 2-pole
breaker's block is 2x a 1-pole breaker's), independent of what number gets
printed on it.

Worked example (`numbering_scheme="odd"`, `start_value=1`, breakers
2-pole/1-pole/1-pole): positions_consumed_before is 0, then 2 (after the
2-pole breaker), then 3 (after the next 1-pole) -- slots = 1 + 2*[0, 2, 3] =
[1, 5, 7]. "odd" and "even" differ only in `start_value` (an odd-column
strip starts at 1, an even-column strip starts at 2) -- both use the same
increment=2, so a caller who leaves `start_value` at its default (1) while
picking `numbering_scheme="even"` would silently get ODD numbers back (1, 5,
7, ...) that read as a valid-looking but WRONG panel schedule, not an error.
`_check_start_value_parity` closes that gap: "odd" REQUIRES an odd
`start_value`, "even" REQUIRES an even one (checked via `% 2`), rejected
with a message naming both schemes' requirement -- the API itself stays
self-consistent instead of relying on a future caller/UI to remember to
pick the right starting number for the scheme it also picked.

`show_numbers` toggles whether the computed slot number is prepended to each
breaker's own `lines` (circuit descriptions) at all; when it's off, only
`lines` renders (no numbering math has any visible effect). This module's
own content model caps a block at 2 visible lines -- number + 1 description
(NOT an engine limit: divided_blocks.py's BlockSpec itself allows up to 4)
-- so a breaker validating `show_numbers=True` with 2 description lines
already fills both of THIS module's lines before the number even goes in --
rejected explicitly (see `_check_show_numbers_leaves_room`) rather than
silently dropping the second description line.

`orientation` has no user-facing param (v1 only supports the standard
panel-schedule horizontal layout, hardcoded to Orientation.HORIZONTAL below)
-- same convention as punch_down.py's fixed `separator` (see its module
docstring): there is no real-world breaker-panel-schedule strip that reads
vertically or backbone-style, so exposing the choice would just be surface
area with no correct non-default answer.

font_family/bold/font_size_px/padding_mm are pure passthrough, same
convention as patch_panel.py (see its module docstring for the full
reasoning) -- not re-validated here, DividedBlocksParams is the single
source of truth. padding_mm still gets its own `ge=0` Field bound (a bound
cheap enough to express declaratively is, even when the engine would also
catch it) -- so does `build_divided_blocks_params`'s outer-type-name
error-message substitution (see divided_blocks.py).
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from labelmaker.driver.geometry import TapeSpec
from labelmaker.render.document import RenderedLabel
from labelmaker.render.types.base import LabelRenderer, register
from labelmaker.render.types.divided_blocks import (
    BlockSpec,
    DividedBlocksParams,
    Orientation,
    Separator,
    build_divided_blocks_params,
    render_divided_blocks,
)

_MIN_PITCH_MM = 10.0
_MAX_PITCH_MM = 60.0
_MIN_BREAKERS = 1
_MAX_BREAKERS = 50
_MIN_START_VALUE = 1
_MAX_START_VALUE = 999
_MIN_POLES = 1
_MAX_POLES = 4
_MAX_DESCRIPTION_LINES = 2
# Guardrail, not decoration: render_divided_blocks fits ONE shared font size
# across every block in the strip (see divided_blocks.py's module
# docstring), using the narrowest per-block fit as that shared size. Without
# a per-item bound here, one overly long circuit description wouldn't just
# clip/warn on its OWN block -- fit_font_size would shrink toward its
# min_px floor trying to fit that one line, and that shrunk size then
# applies to EVERY OTHER breaker's block too (text_cramped, silently, not a
# 422 -- the whole strip becomes unreadable because of one long word).
_MAX_DESCRIPTION_CHARS = 30

NumberingScheme = Literal["sequential", "odd", "even"]


class BreakerSpec(BaseModel):
    poles: int = Field(
        1,
        ge=_MIN_POLES,
        le=_MAX_POLES,
        description="breaker width in panel positions (2 = double-pole)",
    )
    # Per-item max_length (not a validator-body loop) so an out-of-range
    # item gets its own error `loc`, matching terminal_block.py's `labels`
    # convention -- see _MAX_DESCRIPTION_CHARS above for why this bound
    # exists at all.
    lines: list[Annotated[str, Field(max_length=_MAX_DESCRIPTION_CHARS)]] = Field(
        default_factory=list,
        max_length=_MAX_DESCRIPTION_LINES,
        description="circuit description under the number",
    )


class BreakerBoxParams(BaseModel):
    pitch_mm: float = Field(
        25.4,
        ge=_MIN_PITCH_MM,
        le=_MAX_PITCH_MM,
        description="width of one panel position (1in standard, 12.7mm half-size)",
    )
    breakers: list[BreakerSpec] = Field(
        min_length=_MIN_BREAKERS,
        max_length=_MAX_BREAKERS,
        description="breakers left-to-right, in panel order",
    )
    numbering_scheme: NumberingScheme = Field(
        "sequential",
        description=(
            "sequential 1,2,3...; odd = left panel column 1,3,5...; "
            "even = right column 2,4,6..."
        ),
    )
    start_value: int = Field(
        1,
        ge=_MIN_START_VALUE,
        le=_MAX_START_VALUE,
        description=(
            "slot number of the first breaker's first position -- must be odd for "
            "numbering_scheme='odd', even for 'even'"
        ),
    )
    show_numbers: bool = Field(
        True, description="prepend the computed panel-position number to each breaker's text"
    )
    separator: Separator = Field(
        Separator.LINE, description="mark drawn on each breaker boundary"
    )
    font_family: str = Field("Inter", description="font family name (see GET /api/fonts)")
    bold: bool = Field(False, description="bold text weight")
    font_size_px: int | None = Field(
        None, description="fixed font size in px; omit for auto-fit"
    )
    padding_mm: float = Field(
        default=1.0, ge=0, description="inner text padding on every side of each block"
    )

    @model_validator(mode="after")
    def _check_show_numbers_leaves_room(self) -> "BreakerBoxParams":
        if self.show_numbers and any(len(b.lines) == 2 for b in self.breakers):
            raise ValueError(
                "with numbering enabled, at most 1 description line fits "
                "(the panel-position number takes the other line)"
            )
        return self

    @model_validator(mode="after")
    def _check_start_value_parity(self) -> "BreakerBoxParams":
        # See the module docstring's worked-example paragraph: "odd" and
        # "even" share the same increment=2, so without this check a caller
        # could pick numbering_scheme="even" and leave start_value at its
        # default (1) and silently get back ODD numbers -- a wrong panel
        # schedule that looks valid. Reject the mismatch outright instead
        # (message names BOTH schemes' requirement, not just the one that
        # failed, so the fix is obvious either way).
        if self.numbering_scheme == "odd" and self.start_value % 2 == 0:
            raise ValueError(
                f"numbering_scheme='odd' requires an odd start_value, got {self.start_value} "
                "('even' requires an even start_value)"
            )
        if self.numbering_scheme == "even" and self.start_value % 2 == 1:
            raise ValueError(
                f"numbering_scheme='even' requires an even start_value, got {self.start_value} "
                "('odd' requires an odd start_value)"
            )
        return self


def _breaker_slots(params: BreakerBoxParams) -> list[int]:
    """slot_i = start_value + increment * positions_consumed_before_i, per
    this module's docstring -- increment is 1 for "sequential" (every panel
    position numbered) or 2 for "odd"/"even" (this strip's column only,
    interleaved with the other column's numbers in between)."""
    increment = 1 if params.numbering_scheme == "sequential" else 2
    slots = []
    positions_consumed = 0
    for breaker in params.breakers:
        slots.append(params.start_value + increment * positions_consumed)
        positions_consumed += breaker.poles
    return slots


def _breaker_lines(breaker: BreakerSpec, slot: int, show_numbers: bool) -> list[str]:
    return [str(slot), *breaker.lines] if show_numbers else list(breaker.lines)


def _to_engine_params(params: BreakerBoxParams) -> DividedBlocksParams:
    slots = _breaker_slots(params)
    return build_divided_blocks_params(
        "BreakerBoxParams",
        blocks=[
            BlockSpec(
                lines=_breaker_lines(breaker, slot, params.show_numbers),
                width_multiplier=float(breaker.poles),
            )
            for breaker, slot in zip(params.breakers, slots, strict=True)
        ],
        block_length_mm=params.pitch_mm,
        separator=params.separator,
        orientation=Orientation.HORIZONTAL,
        font_family=params.font_family,
        bold=params.bold,
        font_size_px=params.font_size_px,
        padding_mm=params.padding_mm,
    )


@register("breaker_box")
class BreakerBoxRenderer(LabelRenderer):
    title = "Breaker Box"
    category = "electrical"
    Params = BreakerBoxParams

    def render(
        self, params: BreakerBoxParams, tape: TapeSpec, *, data_dir: Path | None = None
    ) -> RenderedLabel:
        return render_divided_blocks(_to_engine_params(params), tape)
