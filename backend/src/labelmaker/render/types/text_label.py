"""Label type "text": one to four lines of plain text, centered on the tape.

Layout summary (baseline math): the N-line block is vertically centered in
the tape's full print height (tape.print_dots -- text labels always use the
whole printable strip, never a sub-region). Each line gets a line box of
height `font_px * _LINE_SPACING`; within that box the font's own ascent/
descent (from the same TTF, read via Pillow) are centered, and the SVG
baseline is placed at `line_top + (line_box_height - (ascent+descent)) / 2
+ ascent` -- i.e. the leading is split evenly above and below the glyphs,
and the baseline sits `ascent` below wherever the glyphs actually start.
"""

from typing import Literal

from PIL import ImageFont
from pydantic import BaseModel, Field, field_validator

from labelmaker.driver.geometry import MIN_LABEL_MM, TapeSpec, mm_to_dots
from labelmaker.render.document import RenderedLabel, _svg_document, _text_element
from labelmaker.render.fonts import fit_font_size, font_path, list_fonts, measure_text
from labelmaker.render.types.base import LabelRenderer, register

_LINE_SPACING = 1.15
_MIN_FONT_PX = 6
_MAX_FONT_PX = 128
_VALID_FAMILIES = {f.family for f in list_fonts()}
_MAX_LINE_CHARS = 200
_MAX_LINES = 4
_CLIP_ID = "label-clip"


class TextLabelParams(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=_MAX_LINES)
    font_family: str = "Inter"
    bold: bool = False
    font_size_px: int | None = None
    h_align: Literal["left", "center", "right"] = "center"
    length_mm: float | None = None
    padding_mm: float = 2.0

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
    Params = TextLabelParams

    def render(self, params: TextLabelParams, tape: TapeSpec) -> RenderedLabel:
        warnings: list[str] = []
        lines = params.lines
        n_lines = len(lines)
        height_px = tape.print_dots  # a text label always spans the full print strip
        padding_px = mm_to_dots(params.padding_mm)

        # -- resolve width_px (fixed vs auto) up front where fixed, since it
        # bounds the font-fitting width budget --
        fixed_width_px: int | None = None
        if params.length_mm is not None:
            clamped_length_mm = max(MIN_LABEL_MM, min(tape.max_length_mm, params.length_mm))
            fixed_width_px = mm_to_dots(clamped_length_mm)
            fit_width_budget: float | None = max(0, fixed_width_px - 2 * padding_px)
        else:
            fit_width_budget = None  # auto length: width grows to fit, nothing to fit against

        # -- font size: auto-fit, or explicit-but-clamped-to-the-print-area --
        if params.font_size_px is None:
            font_px = fit_font_size(
                lines, params.font_family, fit_width_budget, height_px, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            if font_px <= _MIN_FONT_PX:
                warnings.append(
                    "auto font size hit the minimum size; text may be cramped"
                )
        else:
            # Explicit size is already validated to [6, 128] by TextLabelParams;
            # additionally clamp it so the line block never exceeds the
            # physical print area (height is a hard constraint, unlike width
            # in auto-length mode, which just grows to accommodate it).
            height_fit_px = fit_font_size(
                lines, params.font_family, None, height_px,
                params.bold, line_spacing=_LINE_SPACING,
                min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            font_px = min(params.font_size_px, height_fit_px)

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
            available_px = width_px - 2 * padding_px
            if widest_px > available_px:
                warnings.append(
                    "text truncated: content is wider than the fixed label length"
                )
                needs_clip = True
        else:
            width_px = max(widest_px + 2 * padding_px, mm_to_dots(MIN_LABEL_MM))

        # -- vertical centering + per-line baseline (see module docstring) --
        font_obj = ImageFont.truetype(str(font_path(params.font_family, params.bold)), font_px)
        ascent, descent = font_obj.getmetrics()
        line_height_px = font_px * _LINE_SPACING
        block_height_px = n_lines * line_height_px
        block_top_px = (height_px - block_height_px) / 2
        leading_px = line_height_px - (ascent + descent)

        # -- horizontal anchor by h_align --
        if params.h_align == "left":
            x = float(padding_px)
            anchor = "start"
        elif params.h_align == "right":
            x = float(width_px - padding_px)
            anchor = "end"
        else:
            x = width_px / 2
            anchor = "middle"

        text_elements = []
        for i, line in enumerate(lines):
            line_top = block_top_px + i * line_height_px
            baseline_y = line_top + leading_px / 2 + ascent
            text_elements.append(
                _text_element(
                    x, baseline_y, line, params.font_family, font_px,
                    text_anchor=anchor, bold=params.bold,
                )
            )
        body = "".join(text_elements)

        if needs_clip:
            clip_defs = (
                f'<defs><clipPath id="{_CLIP_ID}">'
                f'<rect x="0" y="0" width="{width_px}" height="{height_px}"/>'
                f"</clipPath></defs>"
            )
            body = f'{clip_defs}<g clip-path="url(#{_CLIP_ID})">{body}</g>'

        svg = _svg_document(width_px, height_px, body)
        return RenderedLabel(svg=svg, width_px=width_px, height_px=height_px, warnings=warnings)
