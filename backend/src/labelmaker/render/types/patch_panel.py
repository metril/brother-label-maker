"""Label type "patch_panel": Brother's Patch Panel mode -- a row of equal
(or per-block-weighted) blocks, one per port, laid end to end and separated
by a configurable mark. A THIN config over divided_blocks.py's layout
engine (task 2.1) -- this module owns only its own Params model and the
translation from that into a DividedBlocksParams; all layout math (boundary
rounding, separator geometry, font fitting, rotation) lives in
render_divided_blocks/layout_blocks and is not reimplemented here.

Param ranges mirror Brother's own Patch Panel tool (PT-E300 manual, via
docs/research/features.md): Block Length 5-300mm (default 15mm), 1-50
blocks, Separator style Tic/Dash/Line/Bold/Frame/None, Orientation
horizontal/vertical/backbone, a Reverse toggle, and an optional per-block
width-multiplier list (0.1-9.5x).

font_family/bold/font_size_px are pure passthrough: this module does not
re-validate them (no font-family allowlist, no font-size-range check) --
DividedBlocksParams is the single source of truth for what's legal there.
padding_mm DOES get its own `ge=0` bound here (matching
DividedBlocksParams' own), even though it's otherwise passthrough too --
Field(...) bounds (not validator-body logic) are what a future
params_schema-driven form generator can actually see, so every bound cheap
enough to express declaratively is, even when the engine would also catch
it. Either way, an invalid value still surfaces as a 422:
build_divided_blocks_params (divided_blocks.py) re-raises any
pydantic.ValidationError from the DividedBlocksParams construction inside
render() with THIS module's own Params class name substituted in for
"DividedBlocksParams", then that (a ValueError subclass) is caught the
same way render_definition's other ValueErrors are -- see
api/router_labels.py.
"""

from typing import Annotated

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

_MIN_BLOCK_LENGTH_MM = 5.0
_MAX_BLOCK_LENGTH_MM = 300.0
_MAX_BLOCKS = 50
_MIN_MULTIPLIER = 0.1
_MAX_MULTIPLIER = 9.5


class BlockText(BaseModel):
    lines: list[str] = Field(default_factory=lambda: [""], max_length=2)


class PatchPanelParams(BaseModel):
    block_length_mm: float = Field(15.0, ge=_MIN_BLOCK_LENGTH_MM, le=_MAX_BLOCK_LENGTH_MM)
    blocks: list[BlockText] = Field(min_length=1, max_length=_MAX_BLOCKS)
    separator: Separator = Separator.LINE
    orientation: Orientation = Orientation.HORIZONTAL
    reverse: bool = False
    # None = every block the same width (multiplier 1.0); when set, must
    # have exactly one entry per block (length checked below -- per-item
    # 0.1-9.5 range is on the annotation itself, not a validator body, so
    # the bound reaches params_schema AND each out-of-range item gets its
    # own error `loc` instead of one opaque message for the whole list).
    multipliers: (
        list[Annotated[float, Field(ge=_MIN_MULTIPLIER, le=_MAX_MULTIPLIER)]] | None
    ) = None
    font_family: str = "Inter"
    bold: bool = False
    font_size_px: int | None = None
    padding_mm: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _check_multipliers_length(self) -> "PatchPanelParams":
        if self.multipliers is not None and len(self.multipliers) != len(self.blocks):
            raise ValueError(
                f"multipliers length {len(self.multipliers)} must match "
                f"blocks length {len(self.blocks)}"
            )
        return self


def _to_engine_params(params: PatchPanelParams) -> DividedBlocksParams:
    multipliers = params.multipliers or [1.0] * len(params.blocks)
    return build_divided_blocks_params(
        "PatchPanelParams",
        blocks=[
            BlockSpec(lines=block.lines, width_multiplier=m)
            for block, m in zip(params.blocks, multipliers, strict=True)
        ],
        block_length_mm=params.block_length_mm,
        separator=params.separator,
        orientation=params.orientation,
        reverse=params.reverse,
        font_family=params.font_family,
        bold=params.bold,
        font_size_px=params.font_size_px,
        padding_mm=params.padding_mm,
    )


@register("patch_panel")
class PatchPanelRenderer(LabelRenderer):
    title = "Patch Panel"
    category = "network"
    Params = PatchPanelParams

    def render(self, params: PatchPanelParams, tape: TapeSpec) -> RenderedLabel:
        return render_divided_blocks(_to_engine_params(params), tape)
