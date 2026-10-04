"""Label type "punch_down": Brother's Punch-Down Block mode -- a row of
equal-width blocks spanning a fixed module width, auto-numbered by pair
count. A THIN config over divided_blocks.py's layout engine (task 2.1):
this module only computes each block's text content and translates into a
DividedBlocksParams (total-length-mm mode, for equal division across
module_width_mm); all boundary/rounding/font-fit/rotation math lives in
render_divided_blocks/layout_blocks and is not reimplemented here.

Param ranges mirror Brother's own Punch-Down Block tool (PT-E300 manual,
via docs/research/features.md): Module Width 50-300mm (default 8in/203mm),
Block Type 4/3/2/5-Pair/Blank, Sequence Type None/Horizontal/Backbone,
Start Value 1-99999.

`sequence` doubles as both the numbering switch AND the engine orientation
-- this mirrors Brother's own tool exactly (its "Sequence Type" control is
the same overload): "horizontal" -> Orientation.HORIZONTAL, "backbone" ->
Orientation.BACKBONE, "none" -> Orientation.HORIZONTAL (no vertical option
exists for this type; "none" just means "horizontal, unnumbered").

# UNVERIFIED: Brother's exact punch-down numbering semantics -- pair-count
increments per block assumed (matches 110-block pair numbering): block i's
first line is `start_value + i * pair_count` where pair_count is 2/3/4/5
for the matching block_type ("blank" disables auto-numbering entirely,
regardless of `sequence`). Verify at physical checkpoint 2.

There is no user-facing `separator` param for this type (Brother's own tool
doesn't expose one for Punch-Down Block, unlike Patch Panel) -- fixed to
Separator.LINE below.

font_family/bold/font_size_px are pure passthrough, same convention as
patch_panel.py (see its module docstring for the full reasoning) -- not
re-validated here, DividedBlocksParams is the single source of truth.
padding_mm gets its own `ge=0` Field bound though (also per patch_panel.py's
docstring: a bound cheap enough to express declaratively is, even when the
engine would also catch it) -- so is `build_divided_blocks_params`'s
outer-type-name error-message substitution (see divided_blocks.py).
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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

_MIN_MODULE_WIDTH_MM = 50.0
_MAX_MODULE_WIDTH_MM = 300.0
_MAX_BLOCKS = 50
_MIN_START_VALUE = 1
_MAX_START_VALUE = 99999

BlockType = Literal["4-pair", "3-pair", "2-pair", "5-pair", "blank"]
Sequence = Literal["none", "horizontal", "backbone"]

# "blank" maps to None: no pair count exists, so no auto-numbering is
# possible regardless of `sequence` (see module docstring).
_PAIR_COUNTS: dict[BlockType, int | None] = {
    "2-pair": 2,
    "3-pair": 3,
    "4-pair": 4,
    "5-pair": 5,
    "blank": None,
}


class PunchDownParams(BaseModel):
    module_width_mm: float = Field(203.0, ge=_MIN_MODULE_WIDTH_MM, le=_MAX_MODULE_WIDTH_MM)
    n_blocks: int = Field(6, ge=1, le=_MAX_BLOCKS)
    block_type: BlockType = "4-pair"
    sequence: Sequence = "horizontal"
    start_value: int = Field(1, ge=_MIN_START_VALUE, le=_MAX_START_VALUE)
    # 0-1 extra line, shown under the number (or alone, if unnumbered) in
    # EVERY block -- shared text, not per-block.
    extra_lines: list[str] = Field(default_factory=list, max_length=1)
    font_family: str = "Inter"
    bold: bool = False
    font_size_px: int | None = None
    padding_mm: float = Field(default=1.0, ge=0)


def _block_lines(params: PunchDownParams, index: int) -> list[str]:
    pair_count = _PAIR_COUNTS[params.block_type]
    numbering_active = params.sequence != "none" and pair_count is not None
    if not numbering_active:
        return list(params.extra_lines)
    number = str(params.start_value + index * pair_count)
    return [number, *params.extra_lines]


def _to_engine_params(params: PunchDownParams) -> DividedBlocksParams:
    orientation = Orientation.BACKBONE if params.sequence == "backbone" else Orientation.HORIZONTAL
    return build_divided_blocks_params(
        "PunchDownParams",
        blocks=[BlockSpec(lines=_block_lines(params, i)) for i in range(params.n_blocks)],
        total_length_mm=params.module_width_mm,
        separator=Separator.LINE,
        orientation=orientation,
        font_family=params.font_family,
        bold=params.bold,
        font_size_px=params.font_size_px,
        padding_mm=params.padding_mm,
    )


@register("punch_down")
class PunchDownRenderer(LabelRenderer):
    title = "Punch-Down Block"
    category = "network"
    Params = PunchDownParams

    def render(
        self, params: PunchDownParams, tape: TapeSpec, *, data_dir: Path | None = None
    ) -> RenderedLabel:
        return render_divided_blocks(_to_engine_params(params), tape)
