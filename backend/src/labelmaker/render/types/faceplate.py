"""Label type "faceplate": Brother's Faceplate mode -- text blocks evenly
divided across a fixed total label length. A THIN config over
divided_blocks.py's layout engine (task 2.1): this module only pads
`blocks` out to `n_blocks` and translates into a DividedBlocksParams
(total-length-mm mode, for even division); all boundary/rounding/font-fit
math lives in render_divided_blocks/layout_blocks and is not reimplemented
here.

Per docs/research/features.md, Brother's own Faceplate mode is
"conceptually identical" to Patch Panel's block-splitting mechanism, just
driven by a fixed total length divided into even blocks rather than a
per-block length -- hence total_length_mm (not block_length_mm) here.
total_length_mm's own validated range (5-1000mm) is a broad sanity bound,
not a tape-specific one: the engine itself additionally enforces the
ACTUAL tape's max_length_mm (500mm for HSe, 1000mm for TZe) at render time
via layout_blocks' own ValueError -- e.g. a 1000mm total on a 500mm-max HSe
tape passes this Params-level check but still 422s from the engine.

font_family/bold/font_size_px are pure passthrough, same convention as
patch_panel.py (see its module docstring for the full reasoning) -- not
re-validated here, DividedBlocksParams is the single source of truth.
padding_mm gets its own `ge=0` Field bound though (also per patch_panel.py's
docstring: a bound cheap enough to express declaratively is, even when the
engine would also catch it) -- so is `build_divided_blocks_params`'s
outer-type-name error-message substitution (see divided_blocks.py).
"""

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

_MIN_TOTAL_LENGTH_MM = 5.0
_MAX_TOTAL_LENGTH_MM = 1000.0
_MAX_BLOCKS = 50


class BlockText(BaseModel):
    lines: list[str] = Field(default_factory=lambda: [""], max_length=2)


class FaceplateParams(BaseModel):
    total_length_mm: float = Field(70.0, ge=_MIN_TOTAL_LENGTH_MM, le=_MAX_TOTAL_LENGTH_MM)
    n_blocks: int = Field(2, ge=1, le=_MAX_BLOCKS)
    # Fewer entries than n_blocks is padded with blank blocks (see
    # _pad_blocks_to_n_blocks below); more than n_blocks is rejected.
    blocks: list[BlockText] = Field(default_factory=list, max_length=_MAX_BLOCKS)
    separator: Separator = Separator.NONE
    orientation: Orientation = Orientation.HORIZONTAL
    font_family: str = "Inter"
    bold: bool = False
    font_size_px: int | None = None
    padding_mm: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _pad_blocks_to_n_blocks(self) -> "FaceplateParams":
        if len(self.blocks) > self.n_blocks:
            raise ValueError(
                f"blocks length {len(self.blocks)} exceeds n_blocks {self.n_blocks}"
            )
        if len(self.blocks) < self.n_blocks:
            self.blocks = [
                *self.blocks,
                *(BlockText() for _ in range(self.n_blocks - len(self.blocks))),
            ]
        return self


def _to_engine_params(params: FaceplateParams) -> DividedBlocksParams:
    return build_divided_blocks_params(
        "FaceplateParams",
        blocks=[BlockSpec(lines=block.lines) for block in params.blocks],
        total_length_mm=params.total_length_mm,
        separator=params.separator,
        orientation=params.orientation,
        font_family=params.font_family,
        bold=params.bold,
        font_size_px=params.font_size_px,
        padding_mm=params.padding_mm,
    )


@register("faceplate")
class FaceplateRenderer(LabelRenderer):
    title = "Faceplate"
    category = "network"
    Params = FaceplateParams

    def render(self, params: FaceplateParams, tape: TapeSpec) -> RenderedLabel:
        return render_divided_blocks(_to_engine_params(params), tape)
