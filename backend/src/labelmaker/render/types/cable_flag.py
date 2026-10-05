"""Label type "cable_flag": Brother's Cable Flag mode -- a label folded in
half around a cable, its two printed ends pressed together to form a small
flag while the blank middle wraps the cable itself. Bespoke SVG layout --
NOT built on divided_blocks.py (there are exactly two fixed-purpose regions
here, not an N-block grid), though it borrows that module's "shared,
narrowest-fit font size across every region" convention and its rotated
`_avail`-style constraint swap for `text_orientation="vertical"`.

-- Layout: three fixed regions along the label's length --

    [------- flag A -------][------- gap -------][------- flag B -------]
    0                    b1 (=flagA_px)      b2 (=b1+gap_px)      b3 (=total_px)

`flag_length_mm` (Field, 5-100) is the length of EACH printed end (both
ends share the same length); the blank middle ("gap") is sized to the
cable's own circumference plus a small slack allowance:

    gap_mm = pi * cable_diameter_mm + _GAP_SLACK_MM (1.0)

so the two flag ends, once folded together, meet with a little give rather
than being pulled taut against the tape's own limited flexibility.
Brother's spec (docs/research/features.md) only says the gap is "sized to
the cable" -- the 1mm slack figure is this project's own choice.
# UNVERIFIED: confirm the 1mm slack figure (or replace it) against a real
# physical Cable Flag print at checkpoint 2.

total_length_mm = 2 * flag_length_mm + gap_mm. Given flag_length_mm's Field
bounds [5, 100] and cable_diameter_mm's [3, 90], total_length_mm is always
in [2*5 + (3*pi+1) ~= 20.42, 2*100 + (90*pi+1) ~= 483.73]mm -- inside
[MIN_LABEL_MM, tape.max_length_mm] for every tape (500mm is the smallest
max_length_mm, for HSe) -- so, like cable_wrap.py, no clamp-to-range step
is ever needed.

Boundaries (b1, b2, b3 above) use the SAME cumulative-rounding scheme
layout_blocks (divided_blocks.py) uses for its own block boundaries: each
CUMULATIVE boundary, not each individual segment, is rounded once via
mm_to_dots, so the three regions' pixel widths always sum to exactly
mm_to_dots(total_length_mm) with any sub-pixel rounding error absorbed
into individual regions rather than drifting the total away from it.

-- Text: end A upright, end B rotated 180 (or 90/270 for vertical) --

End A's text sits at its own flag's center, unrotated (horizontal
orientation) -- reads normally. End B's text is rotated 180 degrees
relative to A: fold the label at the gap's midpoint and bring the two flag
faces together back-to-back -- B's 180-degree rotation is what makes IT
read upright too, from the opposite face, instead of upside-down. Same
idea as a paper tent-card printed once and folded in half: front and back
both come out right-side up only because the back's text was printed
upside-down relative to the front, before folding.

# GEOMETRY VERIFIED (review): a pixel-level simulated fold -- render both
# ends, fold the bitmap at the gap's midpoint, overlay the two faces --
# confirms ROTATE (not MIRROR) is the physically correct transform: the
# rotate(180) implementation's two faces align to within threshold-noise
# (51/815 differing px), while a mirror (scale(-1,1)) counterfactual does
# NOT align (403/815 differing px). This settles the rotate-vs-mirror
# GEOMETRY question on physical-folding grounds alone (a strip printed on
# one side and folded over is a point reflection through the fold line, by
# construction -- there is no second physically-consistent option),
# independent of Brother's own firmware. Genuinely still open: whether
# Brother's real Cable Flag mode agrees with this correct geometry, or
# does something else -- verify against a real Pro Label Tool / P-touch
# print at physical checkpoint 2.

`text_orientation="vertical"`: both ends' text is rotated an ADDITIONAL 90
degrees (same physical reasoning/direction as cable_wrap.py's own
`rotate(-90, ...)` -- text reading along the cable's length rather than
across the flag) -- concretely end A becomes `rotate(90, ...)` and end B
becomes `rotate(270, ...)` (still 180 relative to A, exactly like the
horizontal case, just composed with the extra 90).

-- Fold guides --

A thin 1px dashed line is drawn at each flag/gap boundary (2 lines total,
at x=b1 and x=b2) -- the same 4px-on/4px-off dash pattern
divided_blocks.py's own DASH separator uses, reimplemented locally here
(`_dashed_fold_guide`) rather than imported: divided_blocks.py's separator
helpers are internal to that module's own block-boundary concept, not a
published shared utility (see its module docstring: only
BlockLayout/layout_blocks/render_divided_blocks/build_divided_blocks_params
are meant for reuse). These print for real (not a preview-only overlay) --
"faint" here means thin-and-dashed, not partially transparent: the print
pipeline is strictly 1-bit (rasterize.py composites over white, converts
to grayscale, then thresholds at 128 -- see its own module docstring), so
an SVG `fill-opacity` below 1.0 would round to solid white or solid black
after thresholding, never an actual gray, and could vanish entirely rather
than reading as "faint". A solid black DASHED line reads as visually
subtle (intermittent, thin) without depending on any grayscale that this
pipeline can't actually preserve.

-- Font sizing --

Both ends share ONE font size (uniform look, exactly divided_blocks.py's
"shared narrowest fit" convention -- see its own module docstring): each
end is fit against its own flag box (width = that flag's own pixel width
minus padding, height = tape print height minus padding -- swapped for
`text_orientation="vertical"`, the same `_avail`-style swap
divided_blocks.py's VERTICAL/BACKBONE orientations use), and the SMALLER
of the two results is used for both. This full (width AND height) fit is
computed the SAME way whether font_size_px is None (auto) or explicit --
an explicit size is min()'d against it (with a `font_clamped` warning if
that reduces it), not just checked against the height/stack half of it:
an explicit size only marginally too wide for a flag's own WIDTH
constraint is still a size a smaller font satisfies, so it gets clamped
down like any other over-large explicit size rather than falling straight
through to the hard check below with "shorten text" advice that would be
wrong when shrinking the font was all that was needed (see
cable_wrap.py's own identical fix/reasoning).

Auto-fit hitting the floor attaches the standard `text_cramped` warning;
text that still doesn't fit its own flag's WIDTH constraint even at
`_MIN_FONT_PX` -- the one case the clamp above can't paper over, since
there's no smaller size left to try -- raises ValueError (422): mirrors
cable_wrap.py's unfittable-text case (a flag's own length, like
cable_wrap's overall length, is derived/fixed, never auto-grown to
accommodate content). This check applies identically whether font_px came
from auto-fit or an explicit font_size_px (now that both are clamped the
same way above, it only ever fires at the genuine floor case), for the
same reason cable_wrap.py's own hard width check does: an over-wide
flag's text would bleed into the blank gap region, not just clip its own
tail.


-- Optional QR --

`qr_data` (default None -> output unchanged) puts a QR on the flag(s):
`qr_placement="flag_a"` (default) puts it alone on flag A and the text on
flag B; "both" puts a QR beside the text on both flags. The QR is sized to
the flag's printable height (and width, if the flag is shorter than tall),
sits at the flag's outer edge (left on A; right on B, rotated 180 like B's
text), and the text is fitted into the remaining width.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from PIL import ImageFont
from pydantic import BaseModel, Field, field_validator

from labelmaker.driver.geometry import TapeSpec, mm_to_dots
from labelmaker.render.document import (
    RenderedLabel,
    RenderWarning,
    _fmt_num,
    _svg_document,
    _text_element,
)
from labelmaker.render.fonts import fit_font_size, font_path, list_fonts, measure_text
from labelmaker.render.objects import qr_fit_group
from labelmaker.render.types.base import LabelRenderer, register

_LINE_SPACING = 1.15
_MIN_FONT_PX = 6
_MAX_FONT_PX = 128
_MAX_LINE_CHARS = 30
_MAX_LINES = 2
_GAP_SLACK_MM = 1.0  # UNVERIFIED -- see module docstring
_VALID_FAMILIES = {f.family for f in list_fonts()}

# Fold-guide dash geometry -- matches divided_blocks.py's own DASH
# separator pixel pattern (see module docstring's "-- Fold guides --").
_DASH_ON_PX = 4
_DASH_OFF_PX = 4
_GUIDE_WIDTH_PX = 1


class CableFlagParams(BaseModel):
    cable_diameter_mm: float = Field(
        4.0,
        ge=3.0,
        le=90.0,
        description=(
            "cable diameter in mm (3-90); sizes the blank gap between the two "
            "printed flag ends so it wraps the cable with a little slack"
        ),
    )
    flag_length_mm: float = Field(
        20.0,
        ge=5.0,
        le=100.0,
        description="length in mm of EACH printed flag end (both ends share this length)",
    )
    lines: list[str] = Field(
        min_length=1,
        max_length=_MAX_LINES,
        description="1-2 lines of text, each <= 30 chars; at least one must be non-empty",
    )
    qr_data: str | None = Field(
        None, description="optional QR payload; adds a QR to the flag(s), see qr_placement"
    )
    qr_placement: Literal["flag_a", "both"] = Field(
        "flag_a",
        description="flag_a: QR on flag A, text on flag B; both: QR beside the text on both flags",
    )
    text_orientation: Literal["horizontal", "vertical"] = Field(
        "horizontal",
        description=(
            "horizontal: text reads along the flag; vertical: text reads across the "
            "tape (rotated 90/270 -- see module docstring)"
        ),
    )
    font_family: str = Field("Inter", description="font family name (see GET /api/fonts)")
    bold: bool = Field(False, description="bold text weight")
    font_size_px: int | None = Field(None, description="fixed font size in px; omit for auto-fit")
    padding_mm: float = Field(
        default=1.0, ge=0, description="inner text padding on every side of each flag end"
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


def _boundaries_px(params: CableFlagParams) -> tuple[int, int, int]:
    """(b1, b2, b3) device-px boundaries -- see module docstring's layout
    diagram. Each is a CUMULATIVE mm value rounded once via mm_to_dots
    (layout_blocks' own convention), not a per-segment width rounded and
    summed, so b3 always equals mm_to_dots(total_length_mm) exactly."""
    gap_mm = math.pi * params.cable_diameter_mm + _GAP_SLACK_MM
    b1 = mm_to_dots(params.flag_length_mm)
    b2 = mm_to_dots(params.flag_length_mm + gap_mm)
    b3 = mm_to_dots(2 * params.flag_length_mm + gap_mm)
    return b1, b2, b3


def _text_group(
    cx: float, cy: float, lines: list[str], family: str, font_px: int, bold: bool
) -> str:
    """One end's PRE-rotation SVG: `lines` centered (both axes) on (cx, cy)
    as ordinary horizontal text -- identical convention to
    cable_wrap.py's own `_text_group` (not shared: see this module's
    docstring on why divided_blocks.py's own helpers aren't imported
    either)."""
    font_obj = ImageFont.truetype(str(font_path(family, bold)), font_px)
    ascent, descent = font_obj.getmetrics()
    line_height_px = font_px * _LINE_SPACING
    block_height_px = len(lines) * line_height_px
    block_top = cy - block_height_px / 2
    leading_px = line_height_px - (ascent + descent)
    parts = []
    for i, line in enumerate(lines):
        if not line:
            continue
        line_top = block_top + i * line_height_px
        baseline_y = line_top + leading_px / 2 + ascent
        parts.append(
            _text_element(cx, baseline_y, line, family, font_px, text_anchor="middle", bold=bold)
        )
    return "".join(parts)


def _avail(
    flag_width_px: int, height_px: int, padding_px: int, vertical: bool
) -> tuple[float, float]:
    """(max_width_px, max_height_px) fit_font_size should fit one flag end
    against -- swapped for `vertical`, exactly divided_blocks.py's own
    rotated `_avail` helper (see its docstring): un-rotated, a line's own
    width is bounded by the flag's pixel width and the line-stack's height
    by the tape's print height; rotated 90, those two swap."""
    w = max(0, flag_width_px - 2 * padding_px)
    h = max(0, height_px - 2 * padding_px)
    return (h, w) if vertical else (w, h)


def _dashed_fold_guide(x: int, height_px: int) -> str:
    """A 1px-wide, full-height dashed vertical line at device-px column x
    (4px-on / 4px-off, starting at y=0) -- see module docstring's
    "-- Fold guides --"."""
    parts = []
    y = 0
    rx = x - _GUIDE_WIDTH_PX // 2
    while y < height_px:
        seg_h = min(_DASH_ON_PX, height_px - y)
        parts.append(
            f'<rect x="{rx}" y="{y}" width="{_GUIDE_WIDTH_PX}" height="{seg_h}" '
            f'fill="black" shape-rendering="crispEdges"/>'
        )
        y += _DASH_ON_PX + _DASH_OFF_PX
    return "".join(parts)


@register("cable_flag")
class CableFlagRenderer(LabelRenderer):
    title = "Cable Flag"
    category = "network"
    Params = CableFlagParams

    def render(
        self, params: CableFlagParams, tape: TapeSpec, *, data_dir: Path | None = None
    ) -> RenderedLabel:
        warnings: list[RenderWarning] = []
        lines = params.lines
        vertical = params.text_orientation == "vertical"
        height_px = tape.print_dots
        padding_px = mm_to_dots(params.padding_mm)

        b1, b2, b3 = _boundaries_px(params)
        width_px = b3
        width_a_px, width_b_px = b1, b3 - b2

        qr_group = ""
        qr_size_px = 0
        qr_both = params.qr_placement == "both"
        if params.qr_data is not None:
            qr_budget_px = min(height_px, min(width_a_px, width_b_px)) - 2 * padding_px
            qr_group, qr_size_px, qr_warnings = qr_fit_group(params.qr_data, qr_budget_px)
            warnings.extend(qr_warnings)
        use_a = not qr_group or qr_both  # flag A carries text
        qr_text_px = qr_size_px if qr_both else 0

        avail_a = _avail(width_a_px - qr_text_px, height_px, padding_px, vertical)
        avail_b = _avail(width_b_px - qr_text_px, height_px, padding_px, vertical)

        if params.font_size_px is None:
            fit_a = fit_font_size(
                lines, params.font_family, *avail_a, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            fit_b = fit_font_size(
                lines, params.font_family, *avail_b, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            font_px = min(fit_a, fit_b) if use_a else fit_b
            if font_px <= _MIN_FONT_PX:
                warnings.append(
                    RenderWarning(
                        code="text_cramped",
                        message="auto font size hit the minimum size; text may be cramped",
                    )
                )
        else:
            # Explicit size clamped against EACH end's full (width AND
            # height) constraint pair -- the same calls the auto-fit branch
            # above makes, not just the height/stack half of it. An
            # explicit size only marginally too wide for a flag's own WIDTH
            # constraint is still a size a smaller font would satisfy, so it
            # must be clamped-and-warned here too (font_clamped), not left
            # to fall through to the unconditional hard check below with
            # "shorten text" advice that would be factually wrong when
            # shrinking the font was all that was needed. See module
            # docstring and cable_wrap.py's own identical fix.
            fit_a = fit_font_size(
                lines, params.font_family, *avail_a, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            fit_b = fit_font_size(
                lines, params.font_family, *avail_b, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            font_px = min(params.font_size_px, *((fit_a, fit_b) if use_a else (fit_b,)))
            if font_px < params.font_size_px:
                warnings.append(
                    RenderWarning(
                        code="font_clamped",
                        message=(
                            f"font size {params.font_size_px}px was reduced to {font_px}px "
                            "to fit the flag"
                        ),
                    )
                )

        # -- hard width check, both ends, both auto and explicit paths --
        widest_px = max(
            (
                measure_text(line, params.font_family, font_px, params.bold)[0]
                for line in lines
                if line
            ),
            default=0,
        )
        for max_width_px in (avail_a[0], avail_b[0]) if use_a else (avail_b[0],):
            if widest_px > max_width_px:
                raise ValueError(
                    f"text too long for a {params.flag_length_mm}mm flag on a "
                    f"{tape.nominal_mm}mm tape -- shorten text, increase flag_length_mm, "
                    "or use a wider tape"
                )

        cy = height_px / 2
        cx_a = b1 / 2
        cx_b = (b2 + b3) / 2
        qr_a_svg = qr_b_svg = ""
        if qr_group:
            qy = _fmt_num(cy - qr_size_px / 2)
            qx_a = padding_px if qr_both else _fmt_num((b1 - qr_size_px) / 2)
            qr_a_svg = f'<g transform="translate({qx_a},{qy})">{qr_group}</g>'
            if qr_both:
                qx_b = b3 - padding_px - qr_size_px
                qr_b_svg = (
                    f'<g transform="rotate(180, {_fmt_num(qx_b + qr_size_px / 2)}, '
                    f'{_fmt_num(cy)})"><g transform="translate({qx_b},{qy})">{qr_group}</g></g>'
                )
                cx_a += qr_size_px / 2  # text region right of flag A's QR
                cx_b -= qr_size_px / 2  # text region left of flag B's QR
        group_a = _text_group(cx_a, cy, lines, params.font_family, font_px, params.bold)
        group_b = _text_group(cx_b, cy, lines, params.font_family, font_px, params.bold)

        angle_a = 90 if vertical else 0
        angle_b = 270 if vertical else 180
        svg_a = (
            group_a
            if angle_a == 0
            else f'<g transform="rotate({angle_a}, {_fmt_num(cx_a)}, {_fmt_num(cy)})">{group_a}</g>'
        )
        svg_b = f'<g transform="rotate({angle_b}, {_fmt_num(cx_b)}, {_fmt_num(cy)})">{group_b}</g>'

        fold_guides = _dashed_fold_guide(b1, height_px) + _dashed_fold_guide(b2, height_px)

        if not use_a:
            svg_a = ""  # flag A carries only the QR
        body = qr_a_svg + svg_a + qr_b_svg + svg_b + fold_guides
        svg = _svg_document(width_px, height_px, body)
        return RenderedLabel(svg=svg, width_px=width_px, height_px=height_px, warnings=warnings)
