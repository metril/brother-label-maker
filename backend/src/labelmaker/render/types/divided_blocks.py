"""render/types/divided_blocks.py: the divided-blocks layout engine.

Pure layout math + SVG emission that powers task 2.2/2.3's five thin-config
label types (patch panel, punch-down, faceplate, terminal block, breaker
box) -- none of which exist yet. This module deliberately does NOT
@register a label type of its own: it has no Params model wired into
render_definition()/get_renderer() (see types/base.py); it only exposes
BlockLayout/layout_blocks/render_divided_blocks, called directly by
whichever config module wraps it (that module owns its own Params/registers
itself).

Layout model (see layout_blocks' docstring for the exact algorithm): a
label is divided into N contiguous blocks along its length, each spanning
the full print height. Block i's length is `block_length_mm *
multiplier_i` (per-block-length mode) or `total_length_mm *
(multiplier_i / sum(multipliers))` (total-length mode); exactly one of
those two length modes is configured (see DividedBlocksParams'
_check_exactly_one_length). Cumulative boundaries are computed in float mm
and only rounded to px at the boundary (not per-block-width), which is what
keeps the total exact while spreading rounding error (<=1px) evenly across
blocks -- see layout_blocks' docstring.

Text: one shared, auto-fit font size across every block (uniform look) --
render_divided_blocks fits each block's own content against its own
available box, then uses the narrowest (smallest) result as the size for
all blocks; any smaller size than a block's own natural fit still fits that
block too, since fit_font_size's search is monotonic (a size that satisfies
width+height at S also satisfies both at any S' < S).

Separators are drawn ON the block boundary, not as additional width -- see
_separator_body's docstring and each Separator member's pixel geometry.
"""

from enum import StrEnum
from typing import NamedTuple

from PIL import ImageFont
from pydantic import BaseModel, Field, field_validator, model_validator

from labelmaker.driver.geometry import MIN_LABEL_MM, TapeSpec, mm_to_dots
from labelmaker.render.document import (
    RenderedLabel,
    RenderWarning,
    _fmt_num,
    _svg_document,
    _text_element,
)
from labelmaker.render.fonts import fit_font_size, font_path, list_fonts

_LINE_SPACING = 1.15
_MIN_FONT_PX = 6
_MAX_FONT_PX = 128
_MAX_LINES = 4
_MAX_BLOCKS = 50
_VALID_FAMILIES = {f.family for f in list_fonts()}

# Separator pixel geometry -- see _separator_body's docstring.
_TIC_FRACTION = 0.15  # TIC: top/bottom fraction of print height a tic mark touches
_DASH_ON_PX = 4
_DASH_OFF_PX = 4
_LINE_WIDTH_PX = 1
_BOLD_WIDTH_PX = 3
_FRAME_BORDER_PX = 1


class Separator(StrEnum):
    TIC = "tic"
    DASH = "dash"
    LINE = "line"
    BOLD = "bold"
    FRAME = "frame"
    NONE = "none"


class Orientation(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    BACKBONE = "backbone"


# UNVERIFIED (mirror at physical checkpoint 2 if wrong): Brother's "backbone"
# mode is for a label meant to be read with the tape itself mounted
# vertically (e.g. run down a cable), as opposed to VERTICAL's per-block
# top-to-bottom reading on a horizontally-mounted tape. Implemented here as
# the mirror image of VERTICAL -- each block's text rotated 90deg
# counter-clockwise instead of VERTICAL's 90deg clockwise -- see
# render_divided_blocks' rotation of BACKBONE vs VERTICAL blocks below.


class BlockSpec(BaseModel):
    lines: list[str] = Field(default=[""], max_length=_MAX_LINES)
    width_multiplier: float = Field(1.0, ge=0.1, le=9.5)


class DividedBlocksParams(BaseModel):
    blocks: list[BlockSpec] = Field(min_length=1, max_length=_MAX_BLOCKS)
    block_length_mm: float | None = None  # per-block length (before multiplier)
    total_length_mm: float | None = None  # alternative: total, divided by multiplier weights
    separator: Separator = Separator.LINE
    orientation: Orientation = Orientation.HORIZONTAL
    reverse: bool = False  # reverse block order (see layout_blocks)
    font_family: str = "Inter"
    bold: bool = False
    font_size_px: int | None = None  # None = auto (shared across ALL blocks)
    padding_mm: float = Field(1.0, ge=0)  # inner text padding per block

    @field_validator("font_family")
    @classmethod
    def _check_font_family(cls, family: str) -> str:
        if family not in _VALID_FAMILIES:
            raise ValueError(f"unknown font_family {family!r}; valid: {sorted(_VALID_FAMILIES)}")
        return family

    @field_validator("font_size_px")
    @classmethod
    def _check_font_size_px(cls, size: int | None) -> int | None:
        if size is not None and not (_MIN_FONT_PX <= size <= _MAX_FONT_PX):
            raise ValueError(
                f"font_size_px must be in [{_MIN_FONT_PX}, {_MAX_FONT_PX}], got {size}"
            )
        return size

    @model_validator(mode="after")
    def _check_exactly_one_length(self) -> "DividedBlocksParams":
        if (self.block_length_mm is None) == (self.total_length_mm is None):
            raise ValueError("exactly one of block_length_mm/total_length_mm must be set")
        return self


class BlockLayout(NamedTuple):
    x_px: int
    width_px: int


def _per_unit_mm(params: DividedBlocksParams) -> float:
    """The mm-per-multiplier-unit both length modes reduce to: block i's
    length is always `_per_unit_mm(params) * blocks[i].width_multiplier`.
    In per-block-length mode this is block_length_mm itself (order-
    independent). In total-length mode it's total_length_mm divided by the
    sum of every block's multiplier -- computed once so
    boundary_mm(cum_weight) == total_length_mm * (cum_weight/total_weight)
    reaches EXACTLY total_length_mm at cum_weight==total_weight (float
    division of X/X is exactly 1.0 for any nonzero X), which is what keeps
    the final boundary drift-free (see layout_blocks)."""
    if params.block_length_mm is not None:
        return params.block_length_mm
    total_weight = sum(b.width_multiplier for b in params.blocks)
    return params.total_length_mm / total_weight  # type: ignore[operator]


def layout_blocks(params: DividedBlocksParams, tape: TapeSpec) -> list[BlockLayout]:
    """Per-block (x_px, width_px) in device px, indexed by INPUT order.

    Algorithm (rule 2's cumulative-rounding scheme): boundaries are
    computed as running sums of mm width in the PHYSICAL (display) order
    the blocks are actually drawn left-to-right -- `display_order` is
    `range(n)` normally, or reversed when params.reverse (see below) --
    then EACH boundary (not each per-block width) is rounded to px via
    mm_to_dots. width_px for a block is the difference between its two
    surrounding rounded boundaries. This is what keeps the total exact
    (the last boundary is total_mm, rounded once) while spreading any
    rounding error over individual blocks to at most +-1px, instead of
    letting per-block rounding drift the total away from mm_to_dots(total).

    reverse=True reverses the VISUAL (display) order only -- block 0 ends
    up rendered rightmost -- but this function still returns positions
    indexed by INPUT order: layout_blocks(...)[i] is always block i's own
    (x_px, width_px), wherever it ends up on the physical label. Rounding
    is computed walking the boundaries in display order (matching how the
    label is actually drawn), so which block "absorbs" the +-1px rounding
    error can differ between reverse=False and reverse=True for the same
    params -- both are valid, exact-total layouts, just not byte-identical
    to each other.

    Raises ValueError if the computed total length falls outside
    [MIN_LABEL_MM, tape.max_length_mm] (rule 7) -- named in the message so
    a caller can surface it as a 422.
    """
    n = len(params.blocks)
    display_order = list(range(n - 1, -1, -1)) if params.reverse else list(range(n))
    per_unit_mm = _per_unit_mm(params)

    total_weight = sum(b.width_multiplier for b in params.blocks)
    total_mm = per_unit_mm * total_weight
    if total_mm < MIN_LABEL_MM or total_mm > tape.max_length_mm:
        raise ValueError(
            f"divided-blocks total length {total_mm:.3f}mm is outside the valid range "
            f"[{MIN_LABEL_MM}, {tape.max_length_mm}]mm for this tape"
        )

    cum_weight = 0.0
    boundary_px = [0]
    for idx in display_order:
        cum_weight += params.blocks[idx].width_multiplier
        boundary_px.append(mm_to_dots(per_unit_mm * cum_weight))

    layouts_by_index: dict[int, BlockLayout] = {}
    for pos, idx in enumerate(display_order):
        x = boundary_px[pos]
        layouts_by_index[idx] = BlockLayout(x_px=x, width_px=boundary_px[pos + 1] - x)

    return [layouts_by_index[i] for i in range(n)]


def _rect(x: int, y: int, width: int, height: int) -> str:
    """A filled black rect, hinted crispEdges so an integer-pixel-aligned
    separator/frame rect rasterizes to exact pixel columns/rows with no
    antialiasing softening -- required for the bitmap-level pixel asserts
    test_divided_blocks.py makes against separator geometry."""
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'fill="black" shape-rendering="crispEdges"/>'
    )


def _separator_body(kind: Separator, boundary_x: int, height_px: int) -> str:
    """SVG for one inner boundary's separator mark, kind-specific pixel
    geometry (rule 3), each centered as closely as an integer pixel grid
    allows on `boundary_x` (the boundary's own rounded px coordinate, i.e.
    the first column of the block to its right):

    - TIC: 1px wide, drawn only across the top and bottom
      round(height_px * 0.15) rows (a short tic mark, not a full line).
    - DASH: 1px wide, full height, alternating 4px-on/4px-off vertical
      segments starting at y=0.
    - LINE / FRAME's per-boundary mark: 1px wide, solid, full height.
    - BOLD: 3px wide, solid, full height.
    - NONE: nothing.
    """
    if kind is Separator.NONE:
        return ""
    if kind is Separator.TIC:
        seg_h = round(height_px * _TIC_FRACTION)
        rx = boundary_x - _LINE_WIDTH_PX // 2
        return _rect(rx, 0, _LINE_WIDTH_PX, seg_h) + _rect(
            rx, height_px - seg_h, _LINE_WIDTH_PX, seg_h
        )
    if kind is Separator.DASH:
        rx = boundary_x - _LINE_WIDTH_PX // 2
        parts = []
        y = 0
        while y < height_px:
            seg_h = min(_DASH_ON_PX, height_px - y)
            parts.append(_rect(rx, y, _LINE_WIDTH_PX, seg_h))
            y += _DASH_ON_PX + _DASH_OFF_PX
        return "".join(parts)
    if kind in (Separator.LINE, Separator.FRAME):
        rx = boundary_x - _LINE_WIDTH_PX // 2
        return _rect(rx, 0, _LINE_WIDTH_PX, height_px)
    if kind is Separator.BOLD:
        rx = boundary_x - _BOLD_WIDTH_PX // 2
        return _rect(rx, 0, _BOLD_WIDTH_PX, height_px)
    raise AssertionError(f"unhandled separator kind {kind!r}")  # pragma: no cover


def render_divided_blocks(params: DividedBlocksParams, tape: TapeSpec) -> RenderedLabel:
    warnings: list[RenderWarning] = []
    layouts = layout_blocks(params, tape)  # raises ValueError per rule 7
    height_px = tape.print_dots
    padding_px = mm_to_dots(params.padding_mm)
    rotated = params.orientation is not Orientation.HORIZONTAL

    def _avail(layout: BlockLayout) -> tuple[float, float]:
        """(max_width_px, max_height_px) fit_font_size should fit this
        block's lines against. HORIZONTAL: normal (block width, print
        height). VERTICAL/BACKBONE: swapped -- the rotated text's "width"
        (each line's horizontal extent, pre-rotation) is bounded by print
        height, and its "height" (line-stacking extent, pre-rotation) is
        bounded by the block's own width (rule 6)."""
        w = max(0, layout.width_px - 2 * padding_px)
        h = max(0, height_px - 2 * padding_px)
        return (h, w) if rotated else (w, h)

    # -- shared font size: fit each block against its own box, use the
    # narrowest result for all of them (module docstring) --
    per_block_fit_px = [
        fit_font_size(
            block.lines,
            params.font_family,
            *_avail(layout),
            params.bold,
            line_spacing=_LINE_SPACING,
            min_px=_MIN_FONT_PX,
            max_px=_MAX_FONT_PX,
        )
        for block, layout in zip(params.blocks, layouts, strict=True)
    ]

    if params.font_size_px is None:
        font_px = min(per_block_fit_px)
        for i, size in enumerate(per_block_fit_px):
            if size <= _MIN_FONT_PX:
                warnings.append(
                    RenderWarning(
                        code="text_cramped",
                        message=(
                            f"block {i}: auto font size hit the minimum size; "
                            "text may be cramped"
                        ),
                        object_id=f"block-{i}",
                    )
                )
    else:
        # Explicit size, height-clamped across every block's own (orientation-
        # swapped) height budget -- mirrors text_label.py's explicit-size
        # clamp, but as ONE shared value (font_size_px is shared, not
        # per-block) so it's a single global warning, not per-block.
        height_fit_px = [
            fit_font_size(
                block.lines,
                params.font_family,
                None,
                _avail(layout)[1],
                params.bold,
                line_spacing=_LINE_SPACING,
                min_px=_MIN_FONT_PX,
                max_px=_MAX_FONT_PX,
            )
            for block, layout in zip(params.blocks, layouts, strict=True)
        ]
        font_px = min(params.font_size_px, min(height_fit_px))
        if font_px < params.font_size_px:
            warnings.append(
                RenderWarning(
                    code="font_clamped",
                    message=(
                        f"font size {params.font_size_px}px was reduced to {font_px}px "
                        "to fit the print area"
                    ),
                )
            )

    # -- per-block text, centered in the block minus padding (rule 5/6) --
    font_obj = ImageFont.truetype(str(font_path(params.font_family, params.bold)), font_px)
    ascent, descent = font_obj.getmetrics()
    line_height_px = font_px * _LINE_SPACING
    leading_px = line_height_px - (ascent + descent)

    text_parts: list[str] = []
    for block, layout in zip(params.blocks, layouts, strict=True):
        lines = block.lines or [""]
        if not any(lines):
            continue  # empty lines list or [""] -> block renders empty, no error (rule 5)

        cx = layout.x_px + layout.width_px / 2
        cy = height_px / 2
        text_block_height_px = len(lines) * line_height_px
        block_top = cy - text_block_height_px / 2

        elements = []
        for li, line in enumerate(lines):
            if not line:
                continue
            line_top = block_top + li * line_height_px
            baseline_y = line_top + leading_px / 2 + ascent
            elements.append(
                _text_element(
                    cx,
                    baseline_y,
                    line,
                    params.font_family,
                    font_px,
                    text_anchor="middle",
                    bold=params.bold,
                )
            )
        group = "".join(elements)
        if params.orientation is Orientation.VERTICAL:
            group = f'<g transform="rotate(90, {_fmt_num(cx)}, {_fmt_num(cy)})">{group}</g>'
        elif params.orientation is Orientation.BACKBONE:
            group = f'<g transform="rotate(-90, {_fmt_num(cx)}, {_fmt_num(cy)})">{group}</g>'
        text_parts.append(group)

    # -- separators, drawn on top of text so they're never occluded (rule 3) --
    total_width_px = sum(layout.width_px for layout in layouts)
    sep_parts: list[str] = []
    if params.separator is not Separator.NONE:
        sorted_layouts = sorted(layouts, key=lambda bl: bl.x_px)
        inner_boundaries = [bl.x_px for bl in sorted_layouts[1:]]
        for boundary_x in inner_boundaries:
            sep_parts.append(_separator_body(params.separator, boundary_x, height_px))
        if params.separator is Separator.FRAME:
            sep_parts.append(_rect(0, 0, total_width_px, _FRAME_BORDER_PX))
            sep_parts.append(
                _rect(0, height_px - _FRAME_BORDER_PX, total_width_px, _FRAME_BORDER_PX)
            )
            sep_parts.append(_rect(0, 0, _FRAME_BORDER_PX, height_px))
            sep_parts.append(
                _rect(total_width_px - _FRAME_BORDER_PX, 0, _FRAME_BORDER_PX, height_px)
            )

    body = "".join(text_parts) + "".join(sep_parts)
    svg = _svg_document(total_width_px, height_px, body)
    return RenderedLabel(svg=svg, width_px=total_width_px, height_px=height_px, warnings=warnings)
