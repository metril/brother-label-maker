"""Label type "terminal_block": DIN-rail terminal strip labeling -- one
block per terminal, pitch-driven. A THIN config over divided_blocks.py's
layout engine (task 2.1): this module only computes each terminal's text
content and translates into a DividedBlocksParams (per-block-length mode,
one block per terminal); all boundary/rounding/font-fit/rotation math lives
in render_divided_blocks/layout_blocks and is not reimplemented here.

Unlike patch_panel/punch_down/faceplate (task 2.2), Brother's own software
has NO wizard for this label shape -- there is no manual page to mirror
param ranges from. This module's docstrings and Field(description=...) text
ARE the spec: every field below carries its own description, not just the
numeric ones, so a future params_schema-driven form (or a user reading the
API schema directly) has the full semantics without needing this file.

Terminal pitch (`pitch_mm`) is DIN-rail terminal-block terminology for the
fixed center-to-center spacing between adjacent terminals on a strip (e.g.
5.2mm/6.2mm/8.2mm are common real hardware pitches) -- it plays the exact
role patch_panel.py's `block_length_mm` does (per-block length before any
multiplier; terminal blocks have no multiplier concept, so it IS the block
length), just under the name an electrician actually uses.

font_family/bold/font_size_px/padding_mm are pure passthrough, same
convention as patch_panel.py (see its module docstring for the full
reasoning) -- not re-validated here, DividedBlocksParams is the single
source of truth. padding_mm still gets its own `ge=0` Field bound (a bound
cheap enough to express declaratively is, even when the engine would also
catch it) -- so does `build_divided_blocks_params`'s outer-type-name
error-message substitution (see divided_blocks.py).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from labelmaker.driver.geometry import TapeSpec
from labelmaker.render.document import RenderedLabel
from labelmaker.render.types.base import LabelRenderer, register
from labelmaker.render.types.divided_blocks import (
    BlockSpec,
    DividedBlocksParams,
    Separator,
    build_divided_blocks_params,
    render_divided_blocks,
)

_MIN_PITCH_MM = 3.0
_MAX_PITCH_MM = 50.0
_MIN_TERMINALS = 1
_MAX_TERMINALS = 50
_MIN_START_VALUE = 0
_MAX_START_VALUE = 99999
_MIN_STEP = 1
_MAX_STEP = 100
_MAX_LABEL_CHARS = 20
_MAX_LABELS = 50

# No "backbone" option here (unlike divided_blocks.py's full Orientation
# enum, which patch_panel/faceplate expose as-is): a terminal strip is read
# the same way regardless of which axis the DIN rail runs, so there's no
# second rotation direction worth exposing. A plain Literal (not the engine's
# Orientation enum reused directly) keeps this restriction Field-visible in
# params_schema -- a validator-body check would hide it from a future
# schema-driven form (see patch_panel.py's module docstring on this
# convention) -- and its two string values coerce straight into
# Orientation.HORIZONTAL/VERTICAL when DividedBlocksParams validates them.
TerminalOrientation = Literal["horizontal", "vertical"]


class TerminalBlockParams(BaseModel):
    pitch_mm: float = Field(
        6.0,
        ge=_MIN_PITCH_MM,
        le=_MAX_PITCH_MM,
        description="center-to-center terminal width",
    )
    n_terminals: int = Field(
        12,
        ge=_MIN_TERMINALS,
        le=_MAX_TERMINALS,
        description="number of terminals on the strip -- one block per terminal",
    )
    numbering: bool = Field(
        True,
        description=(
            "auto-number every terminal that isn't overridden by `labels`; "
            "when False, an unlabeled terminal renders blank"
        ),
    )
    start_value: int = Field(
        1,
        ge=_MIN_START_VALUE,
        le=_MAX_START_VALUE,
        description="number shown on terminal 0 when numbering is on",
    )
    step: int = Field(
        1,
        ge=_MIN_STEP,
        le=_MAX_STEP,
        description="increment between consecutive terminals' numbers",
    )
    # Entry i REPLACES the auto-generated number on terminal i; a shorter
    # list than n_terminals leaves the remaining terminals numbered (or
    # blank, if numbering is off) -- see _terminal_text below. Per-item
    # max_length (not a validator-body loop) so an out-of-range item gets
    # its own error `loc`, matching patch_panel.py's `multipliers` convention.
    labels: list[Annotated[str, Field(max_length=_MAX_LABEL_CHARS)]] = Field(
        default_factory=list,
        max_length=_MAX_LABELS,
        description=(
            "per-terminal text overrides, by position (entry i replaces terminal "
            "i's number); shorter than n_terminals leaves the rest numbered"
        ),
    )
    # Terminal strips are narrow and tall in their usual mounting -- vertical
    # text (reading top-to-bottom along the tape) is the standard look,
    # unlike patch_panel/faceplate/punch_down's horizontal default.
    orientation: TerminalOrientation = Field(
        "vertical",
        description="text direction: vertical (default -- narrow strip) or horizontal",
    )
    separator: Separator = Field(
        Separator.LINE, description="mark drawn on each terminal boundary"
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
    def _check_labels_length(self) -> "TerminalBlockParams":
        if len(self.labels) > self.n_terminals:
            raise ValueError(
                f"labels length {len(self.labels)} exceeds n_terminals {self.n_terminals}"
            )
        return self


def _terminal_text(params: TerminalBlockParams, index: int) -> list[str]:
    """Terminal `index`'s block text: `labels[index]` if that entry exists
    (a shorter labels list leaves later terminals on the numbering path
    below); else its auto-number if `numbering`; else blank. The number is
    always derived from `index` itself (`start_value + index * step`), never
    from how many earlier terminals happened to have a label -- a labeled
    terminal does not shift its numbered neighbors' own numbers."""
    if index < len(params.labels):
        return [params.labels[index]]
    if params.numbering:
        return [str(params.start_value + index * params.step)]
    return []


def _to_engine_params(params: TerminalBlockParams) -> DividedBlocksParams:
    return build_divided_blocks_params(
        "TerminalBlockParams",
        blocks=[
            BlockSpec(lines=_terminal_text(params, i)) for i in range(params.n_terminals)
        ],
        block_length_mm=params.pitch_mm,
        separator=params.separator,
        orientation=params.orientation,
        font_family=params.font_family,
        bold=params.bold,
        font_size_px=params.font_size_px,
        padding_mm=params.padding_mm,
    )


@register("terminal_block")
class TerminalBlockRenderer(LabelRenderer):
    title = "Terminal Block"
    category = "electrical"
    Params = TerminalBlockParams

    def render(self, params: TerminalBlockParams, tape: TapeSpec) -> RenderedLabel:
        return render_divided_blocks(_to_engine_params(params), tape)
