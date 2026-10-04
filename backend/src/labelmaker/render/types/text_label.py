"""Label type "text": one to four lines of plain text, centered on the tape.

Layout summary (baseline math): the N-line block is vertically centered in
the tape's full print height (tape.print_dots -- text labels always use the
whole printable strip, never a sub-region). Each line gets a line box of
height `font_px * _LINE_SPACING`; within that box the font's own ascent/
descent (from the same TTF, read via Pillow) are centered, and the SVG
baseline is placed at `line_top + (line_box_height - (ascent+descent)) / 2
+ ascent` -- i.e. the leading is split evenly above and below the glyphs,
and the baseline sits `ascent` below wherever the glyphs actually start.

-- Leading art: `icon` (task 2.7) --

An optional `icon` (`{kind: "symbol", id}` from render/symbols.py's curated
library, or `{kind: "image", image_id, mode, threshold}` from an upload via
POST /api/images + render/images.py) renders SQUARE at the label's left
edge, sized to exactly `height_px - 2*padding_px` (the full print strip
minus the same top/bottom padding text already uses) -- i.e. it always
touches both the top and bottom padding lines, never independently sized.
The text block's own horizontal layout is unaffected in every OTHER
respect: it just gets pushed right by `icon_size_px + padding_px` (the icon
square plus one more padding-width gap before the text starts), via
`content_left_px` replacing every place `padding_px` alone used to mark the
label's left content edge (fixed/auto width_px, the fixed-width truncation
check, and all three `h_align` anchors). When `icon` is None,
`content_left_px == padding_px` exactly, so every formula below reduces
algebraically to its pre-2.7 form -- verified directly by golden byte-
identity on every pre-existing (iconless) golden fixture.

Unlike the text block (which clips-and-warns, or shrinks/drops, depending
on the label type -- see text_truncated below), the icon itself is NEVER
clipped or shrunk: it always renders at its full `icon_size_px` square. In
fixed `length_mm` mode this means `fixed_width_px` must be at least
`content_left_px + padding_px` (room for the icon + its two padding gaps,
even with zero-width text) -- if not, `render()` raises `ValueError` (422)
rather than letting resvg's default `overflow:hidden` on the root `<svg>`
silently clip most or all of the icon away with no warning anywhere
pointing at why (mirrors barcode_label.py's own fixed-length hard-fail: "a
barcode partially cut off is not a smaller barcode, it's an unscannable
one" -- the same is true of an icon).

Symbol ids are resolved (and validated) entirely at render() time via
render/symbols.py's `symbol_object()` -- NOT in a TextLabelParams field
validator, unlike `font_family` (which validates eagerly against a pure
in-memory constant, `_VALID_FAMILIES`, computed with zero filesystem I/O at
import time). `list_symbols()` reads `index.json` off disk; doing that
eagerly at every `text_label.py` import (i.e. whenever the render type
registry loads, unconditionally, not just when an icon is actually used)
would give this otherwise I/O-free module a filesystem dependency it
doesn't need for the common no-icon case. Image ids can ONLY be resolved at
render() time regardless -- they need a `data_dir`, which isn't available
until then. An unknown id of either kind raises `ValueError` here (same as
every other unknown-id case in this codebase, e.g. `Tape.resolve()`),
422-mapped by whichever router/worker path is rendering.
"""

from pathlib import Path
from typing import Annotated, Literal

from PIL import ImageFont
from pydantic import BaseModel, Field, field_validator

from labelmaker.driver.geometry import MIN_LABEL_MM, TapeSpec, mm_to_dots
from labelmaker.render.document import (
    ObjectRegion,
    RenderedLabel,
    RenderWarning,
    _svg_document,
    _text_element,
)
from labelmaker.render.fonts import fit_font_size, font_path, list_fonts, measure_text
from labelmaker.render.images import image_object
from labelmaker.render.symbols import symbol_object
from labelmaker.render.types.base import LabelRenderer, register

_LINE_SPACING = 1.15
_MIN_FONT_PX = 6
_MAX_FONT_PX = 128
_VALID_FAMILIES = {f.family for f in list_fonts()}
_MAX_LINE_CHARS = 200
_MAX_LINES = 4
_CLIP_ID = "label-clip"


class SymbolIcon(BaseModel):
    kind: Literal["symbol"] = "symbol"
    id: str = Field(description="a symbol id from GET /api/symbols")


class ImageIcon(BaseModel):
    kind: Literal["image"] = "image"
    image_id: str = Field(description="an image_id returned by POST /api/images")
    mode: Literal["threshold", "dither"] = Field(
        "threshold",
        description=(
            "threshold: binarized at a fixed cutoff, hard edges; dither: "
            "Floyd-Steinberg halftone (better for photos/gradients)"
        ),
    )
    threshold: int = Field(128, ge=0, le=255, description="threshold mode's cutoff (0-255)")


Icon = Annotated[SymbolIcon | ImageIcon, Field(discriminator="kind")]


class TextLabelParams(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=_MAX_LINES)
    font_family: str = "Inter"
    bold: bool = False
    font_size_px: int | None = None
    h_align: Literal["left", "center", "right"] = "center"
    length_mm: float | None = None
    padding_mm: float = Field(default=2.0, ge=0)
    icon: Icon | None = Field(
        default=None,
        description=(
            "optional leading art at the left of the text block, square, sized to "
            "(print height - 2*padding); text shifts right to make room"
        ),
    )

    @field_validator("lines")
    @classmethod
    def _check_lines(cls, lines: list[str]) -> list[str]:
        for line in lines:
            if len(line) > _MAX_LINE_CHARS:
                raise ValueError(f"each line must be <= {_MAX_LINE_CHARS} chars, got {len(line)}")
        if not any(line.strip() for line in lines):
            raise ValueError("at least one line must be non-empty")
        return lines

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


@register("text")
class TextLabelRenderer(LabelRenderer):
    title = "Text"
    category = "general"
    Params = TextLabelParams

    def render(
        self, params: TextLabelParams, tape: TapeSpec, *, data_dir: Path | None = None
    ) -> RenderedLabel:
        warnings: list[RenderWarning] = []
        lines = params.lines
        n_lines = len(lines)
        height_px = tape.print_dots  # a text label always spans the full print strip
        padding_px = mm_to_dots(params.padding_mm)

        # -- icon reserved space (see module docstring's "-- Leading art --"
        # section): icon_size_px is fixed by the print area alone (never by
        # content), so it's resolved up front, before font-fitting, exactly
        # like fixed_width_px below -- content_left_px replaces every bare
        # padding_px used elsewhere as "the label's left content edge", and
        # reduces to padding_px exactly when there is no icon.
        icon_size_px = 0
        if params.icon is not None:
            icon_size_px = height_px - 2 * padding_px
            if icon_size_px < 1:
                raise ValueError(
                    f"icon requested but the print area ({height_px}px tall, "
                    f"{padding_px}px padding on each side) leaves no room for a square "
                    "icon -- reduce padding_mm or use a taller tape"
                )
        content_left_px = padding_px + (icon_size_px + padding_px if params.icon else 0)

        # -- resolve width_px (fixed vs auto) up front where fixed, since it
        # bounds the font-fitting width budget --
        fixed_width_px: int | None = None
        if params.length_mm is not None:
            clamped_length_mm = max(MIN_LABEL_MM, min(tape.max_length_mm, params.length_mm))
            fixed_width_px = mm_to_dots(clamped_length_mm)
            if params.icon is not None and fixed_width_px < content_left_px + padding_px:
                # The icon square is placed unconditionally at (padding_px,
                # padding_px) -- it is never itself clipped or shrunk (only
                # the TEXT block has a text_truncated/clip-path escape
                # hatch). If the fixed canvas isn't even wide enough for
                # the icon + its two padding gaps (with ZERO width left for
                # text), the icon would render past the SVG root's right
                # edge and get silently clipped away by resvg's default
                # overflow:hidden -- a requested icon that's mostly/entirely
                # invisible, with no warning anywhere pointing at why. Hard
                # 422 instead (mirrors barcode_label.py's fixed-length code
                # check: "a barcode partially cut off is not a smaller
                # barcode, it's an unscannable one" -- the same is true of
                # an icon).
                raise ValueError(
                    f"icon does not fit within the fixed label length ({fixed_width_px}px): "
                    f"needs at least {content_left_px + padding_px}px just for the icon and "
                    "its padding, before any text -- increase length_mm, reduce padding_mm, "
                    "or remove the icon"
                )
            fit_width_budget: float | None = max(0, fixed_width_px - content_left_px - padding_px)
        else:
            fit_width_budget = None  # auto length: width grows to fit, nothing to fit against

        # -- font size: auto-fit, or explicit-but-clamped-to-the-print-area --
        if params.font_size_px is None:
            font_px = fit_font_size(
                lines,
                params.font_family,
                fit_width_budget,
                height_px,
                params.bold,
                line_spacing=_LINE_SPACING,
                min_px=_MIN_FONT_PX,
                max_px=_MAX_FONT_PX,
            )
            if font_px <= _MIN_FONT_PX:
                warnings.append(
                    RenderWarning(
                        code="text_cramped",
                        message="auto font size hit the minimum size; text may be cramped",
                    )
                )
        else:
            # Explicit size is already validated to [6, 128] by TextLabelParams;
            # additionally clamp it so the line block never exceeds the
            # physical print area (height is a hard constraint, unlike width
            # in auto-length mode, which just grows to accommodate it).
            height_fit_px = fit_font_size(
                lines,
                params.font_family,
                None,
                height_px,
                params.bold,
                line_spacing=_LINE_SPACING,
                min_px=_MIN_FONT_PX,
                max_px=_MAX_FONT_PX,
            )
            font_px = min(params.font_size_px, height_fit_px)
            if font_px < params.font_size_px:
                warnings.append(
                    RenderWarning(
                        code="font_clamped",
                        message=(
                            f"font size {params.font_size_px}px was reduced to "
                            f"{font_px}px to fit the print area"
                        ),
                    )
                )

        # -- measure widest line at the chosen font size --
        widest_px = max(
            (
                measure_text(line, params.font_family, font_px, params.bold)[0]
                for line in lines
                if line
            ),
            default=0,
        )

        # -- width_px: fixed (already resolved above) or auto (content-fit) --
        needs_clip = False
        if fixed_width_px is not None:
            width_px = fixed_width_px
            available_px = width_px - content_left_px - padding_px
            if widest_px > available_px:
                warnings.append(
                    RenderWarning(
                        code="text_truncated",
                        message="text truncated: content is wider than the fixed label length",
                    )
                )
                needs_clip = True
        else:
            width_px = max(widest_px + content_left_px + padding_px, mm_to_dots(MIN_LABEL_MM))

        # -- vertical centering + per-line baseline (see module docstring) --
        font_obj = ImageFont.truetype(str(font_path(params.font_family, params.bold)), font_px)
        ascent, descent = font_obj.getmetrics()
        line_height_px = font_px * _LINE_SPACING
        block_height_px = n_lines * line_height_px
        block_top_px = (height_px - block_height_px) / 2
        leading_px = line_height_px - (ascent + descent)

        # -- horizontal anchor by h_align (content_left_px, not padding_px,
        # marks the left content edge -- see module docstring) --
        if params.h_align == "left":
            x = float(content_left_px)
            anchor = "start"
        elif params.h_align == "right":
            x = float(width_px - padding_px)
            anchor = "end"
        else:
            x = (content_left_px + width_px - padding_px) / 2
            anchor = "middle"

        text_elements = []
        for i, line in enumerate(lines):
            line_top = block_top_px + i * line_height_px
            baseline_y = line_top + leading_px / 2 + ascent
            text_elements.append(
                _text_element(
                    x,
                    baseline_y,
                    line,
                    params.font_family,
                    font_px,
                    text_anchor=anchor,
                    bold=params.bold,
                )
            )
        text_body = "".join(text_elements)

        if needs_clip:
            # Coordinator review fix-up: this clip rect used to start at
            # x=0 (the whole canvas) -- correct for LEFT-aligned overflow
            # (anchor="start" at content_left_px only ever extends
            # RIGHTWARD, so it can never bleed left of the content edge
            # anyway), but WRONG for center/right-aligned overflow: a
            # center anchor extends BOTH directions from its midpoint, and
            # a right anchor (anchor="end") extends leftward from
            # width_px-padding_px -- either can spill ink past
            # content_left_px, INTO the icon's reserved square, with only
            # this clip-path standing between "truncated text" and "text
            # drawn on top of the icon" (measured directly: 590/749
            # text-ink pixels landed inside the icon square before this
            # fix, for a center-aligned overflow case). Starting the clip
            # at content_left_px instead of 0 closes that gap -- and, since
            # content_left_px reduces to padding_px exactly when there's no
            # icon (see module docstring), this is a strict tightening of
            # the SAME bug for the no-icon case too (center/right overflow
            # could already bleed into the left padding margin), not a
            # new icon-only special case.
            clip_defs = (
                f'<defs><clipPath id="{_CLIP_ID}">'
                f'<rect x="{content_left_px}" y="0" '
                f'width="{max(0, width_px - content_left_px)}" height="{height_px}"/>'
                f"</clipPath></defs>"
            )
            text_body = f'{clip_defs}<g clip-path="url(#{_CLIP_ID})">{text_body}</g>'

        # -- icon SVG + object_map (see module docstring's "-- Leading art --"
        # section) -- always positioned at (padding_px, padding_px), which is
        # always fully within the canvas by construction (content_left_px's
        # own definition guarantees width_px >= padding_px + icon_size_px +
        # padding_px), so it never needs the text-only clip-path above.
        icon_svg = ""
        object_map: list[ObjectRegion] = []
        if params.icon is not None:
            icon_x = padding_px
            icon_y = padding_px
            if params.icon.kind == "symbol":
                icon_svg = symbol_object(params.icon.id, size_px=icon_size_px, x=icon_x, y=icon_y)
            else:
                if data_dir is None:
                    raise ValueError(
                        "icon.kind='image' requires a configured data_dir to resolve the "
                        "uploaded image -- this renderer was called without one (internal "
                        "error: render_definition()/renderer.render() must be given data_dir)"
                    )
                image_svg, _img_w, _img_h, region = image_object(
                    params.icon.image_id,
                    target_h_px=icon_size_px,
                    target_w_px=icon_size_px,
                    mode=params.icon.mode,
                    threshold=params.icon.threshold,
                    data_dir=data_dir,
                )
                icon_svg = f'<g transform="translate({icon_x},{icon_y})">{image_svg}</g>'
                if region is not None:
                    # image_object()'s region is (0,0)-relative to the
                    # fragment it returned -- offset by the same (icon_x,
                    # icon_y) this fragment got wrapped in, since
                    # ObjectRegion coordinates are absolute canvas
                    # coordinates (see render/images.py's module docstring).
                    object_map.append(
                        ObjectRegion(
                            x=icon_x + region.x,
                            y=icon_y + region.y,
                            width=region.width,
                            height=region.height,
                            mode=region.mode,
                        )
                    )

        body = icon_svg + text_body
        svg = _svg_document(width_px, height_px, body)
        return RenderedLabel(
            svg=svg,
            width_px=width_px,
            height_px=height_px,
            object_map=object_map,
            warnings=warnings,
        )
