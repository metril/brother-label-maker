"""Label type "cable_wrap": Brother's Cable Wrap mode -- a label that wraps
around a cable's circumference, its printed length driven entirely by the
cable's own diameter (never user-chosen, unlike text_label.py's optional
fixed length_mm) so the finished label always fits the cable it's made for.
Bespoke SVG layout -- NOT built on divided_blocks.py (there is no grid of
blocks here, just repeated instances of one text group), though it borrows
that module's own font-fit-with-swapped-constraints idea for rotated text
(see "-- Auto font size --" below) and its VERTICAL/BACKBONE orientation
convention for which way a 90-degree rotation turns.

-- Layout: length is DERIVED, not chosen --

length_mm = math.pi * cable_diameter_mm + overlap_mm -- circumference plus
a mandatory overlap so the two wrapped ends can actually stick to each
other once the label is wrapped around the cable (Brother's own spec, see
docs/research/features.md) -- rounded ONCE to device px via mm_to_dots,
the same single-rounding convention every other fixed-length path in this
codebase uses (e.g. text_label.py's fixed length_mm, barcode_label.py's).

Given cable_diameter_mm's Field bounds [3, 90] and overlap_mm's [5, 20],
length_mm is always in [3*pi+5 ~= 14.42, 90*pi+20 ~= 302.74]mm -- well
inside [MIN_LABEL_MM, tape.max_length_mm] for every tape this project
supports (max_length_mm is 500mm for HSe, 1000mm for TZe) -- so unlike
text_label.py's user-supplied length_mm, this never needs a clamp-to-range
step: there is no combination of the two Fields that produces an
out-of-range length.

-- Rotation: which way does the text read once wrapped? --

Per docs/research/features.md's account of Brother's own Cable Wrap mode,
text is rotated 90 degrees COUNTERCLOCKWISE -- the same direction
divided_blocks.py's Orientation.BACKBONE already uses (`rotate(-90, cx,
cy)` in SVG's y-down coordinate system), and that module's own docstring
already flags BACKBONE as "for a label meant to be read with the tape
itself mounted vertically (e.g. run down a cable)" -- this label type is
exactly that use case made concrete.

Physically: a tape's LENGTH axis (the feed direction -- `width_px` in this
codebase's vocabulary) is what wraps circumferentially around the cable;
the tape's WIDTH axis (`height_px`, the cross-tape print band) ends up
running AXIALLY, along the cable's own length. Un-rotated text reads along
the length axis, i.e. circumferentially -- legible only from the one
specific rotational angle you happen to be viewing the cable from, upside
down or sideways from any other. Rotating each text instance 90 degrees
swaps that: the text's own reading direction (each line's rendered width)
now runs across the tape -- i.e. axially along the cable once wrapped --
and the STACK of lines (their combined height) now runs along the tape's
length -- i.e. circumferentially. So each individual repeated instance
reads normally along the cable's own length (top-to-bottom for a 2-line
label), exactly like text printed straight along a pipe -- and because the
whole label wraps all the way around, several instances end up distributed
around the circumference (see "-- Repeat --" below), so at least one is
right-side-up and legible from any angle you view the cable from, without
needing to rotate it. This matches how real Brother cable-wrap labels look.

-- Auto font size: swapped constraints, like divided_blocks.py's rotated
`_avail` --

Each instance is authored PRE-rotation as ordinary horizontal text (same
per-line ascent/descent baseline centering as text_label.py/
divided_blocks.py), anchored at its own (cx, cy) with lines stacked
vertically around cy and each line horizontally centered on cx, then the
whole group is wrapped in a single `rotate(-90, cx, cy)`. Rotating -90
degrees about a point maps an offset (dx, dy) to (dy, -dx) -- so
pre-rotation dx (how far a glyph sits from the line's own horizontal
center, i.e. what makes up a LINE'S WIDTH) becomes post-rotation dy (an
extent along the tape's cross axis, `height_px`), and pre-rotation dy (how
far a LINE sits from the block's vertical center, i.e. what makes up the
N-LINE STACK's height) becomes post-rotation dx (an extent along the
tape's length axis, `width_px`). Concretely:

    max_width_px  (the LINE-WIDTH constraint fit_font_size checks)
        = height_px - 2*padding_px          (cross-tape budget -- HARD:
                                              the tape's own width can
                                              never grow)
    max_height_px (the LINE-STACK constraint fit_font_size checks)
        = width_px  - 2*padding_px          (the "length budget" -- see
                                              "-- Repeat --": one instance
                                              must fit inside it)

The cross-tape budget is the one dimension that can genuinely never be
satisfied within a single render call (there's no wider tape to grow
into) -- if even `_MIN_FONT_PX` doesn't fit it, this raises `ValueError`
(surfaced as a 422) rather than silently rendering unreadable/off-tape
text, mirroring barcode_label.py's fixed-dimension unfittable-code case.
Falling back to `_MIN_FONT_PX` while still (barely) fitting attaches the
same `text_cramped` warning text_label.py's own auto-fit floor case uses.

Both budgets -- cross-tape AND length -- are clamped identically whether
font_px came from auto-fit or an explicit `font_size_px`: an explicit size
is run through the SAME `fit_font_size(..., cross_budget_px,
length_budget_px, ...)` call auto-fit uses (min()'d with the requested
size, `font_clamped` warned if reduced), NOT just the length half of it.
This matters specifically because the cross-tape budget, unlike the length
budget, is otherwise a hard failure -- an explicit size only marginally
too wide for the tape is still a size a SMALLER font would satisfy, so it
must be clamped down like any other over-large explicit size, not left to
fall through to the unconditional ValueError below with "shorten or use
wider tape" advice that would be factually wrong (a smaller font is
exactly what fixes it, and the server can just pick one). The
unconditional cross-tape check right after the if/else therefore only
ever actually fires in the genuinely-unfittable case the brief describes:
even `_MIN_FONT_PX` -- fit_font_size's own last-resort fallback -- doesn't
satisfy the cross-tape budget, so there truly is no size left to clamp
to. The length budget, by contrast, was never a hard-failure axis to begin
with: for auto-fit it's simply the other half of the same search; for an
explicit size, being included in that same clamped `fit_px` guarantees a
single instance's stack height never exceeds it either -- so "-- Repeat
--" below never needs to handle "not even one instance fits".

-- Repeat --

`repeat=True` (default): as many identical instances as fit along the
label's length with >= 2mm gaps between them, evenly centered as one block
inside the (padded) length budget. `repeat=False`: exactly one instance,
centered on the whole label -- which is just the n=1 case of the same
tiling formula, not a separate code path.
"""

from __future__ import annotations

import math

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
from labelmaker.render.fonts import extent_ratio, fit_font_size, font_path, list_fonts, measure_text
from labelmaker.render.types.base import LabelRenderer, register

_LINE_SPACING = 1.15
_MIN_FONT_PX = 6
_MAX_FONT_PX = 128
_MAX_LINE_CHARS = 30
_MAX_LINES = 2
_MIN_GAP_MM = 2.0  # minimum edge-to-edge gap between repeated instances
_VALID_FAMILIES = {f.family for f in list_fonts()}


class CableWrapParams(BaseModel):
    cable_diameter_mm: float = Field(
        6.0,
        ge=3.0,
        le=90.0,
        description=(
            "cable diameter in mm (3-90); label length is derived from this as "
            "circumference (pi * diameter) plus overlap_mm. TZe-FX Flexible ID tape "
            "or TZe-SL Self-Laminating tape is recommended for cable-wrap applications."
        ),
    )
    overlap_mm: float = Field(
        5.0,
        ge=5.0,
        le=20.0,
        description=(
            "extra length beyond the cable's own circumference so the two wrapped "
            "ends overlap and stick to each other (Brother's spec requires >= 5mm)"
        ),
    )
    lines: list[str] = Field(
        min_length=1,
        max_length=_MAX_LINES,
        description="1-2 lines of text, each <= 30 chars; at least one must be non-empty",
    )
    repeat: bool = Field(
        True,
        description=(
            "repeat the text as many times as fit around the wrap with >= 2mm gaps; "
            "False prints a single instance centered on the label"
        ),
    )
    font_family: str = Field("Inter", description="font family name (see GET /api/fonts)")
    bold: bool = Field(False, description="bold text weight")
    font_size_px: int | None = Field(None, description="fixed font size in px; omit for auto-fit")
    padding_mm: float = Field(
        default=1.0,
        ge=0,
        description="inner text padding, applied both across the tape and along its length",
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


def _wrap_length_mm(params: CableWrapParams) -> float:
    """pi * cable_diameter_mm + overlap_mm -- see module docstring. Private:
    tests hand-derive this same value independently via math.pi rather than
    calling it, the same "don't just assert whatever the code produces"
    convention test_divided_blocks.py's own docstring documents."""
    return math.pi * params.cable_diameter_mm + params.overlap_mm


def _effective_line_spacing(family: str, bold: bool) -> float:
    """max(_LINE_SPACING, extent_ratio(family, bold)) -- the per-line box
    multiplier actually used for layout (both `_text_group`'s rendering and
    `instance_len_px`'s tiling reservation below), NOT what's passed to
    fit_font_size (which keeps using the plain `_LINE_SPACING` constant --
    see its own docstring: fit_font_size already multiplies its internally-
    computed extent_ratio BY the line_spacing it's given, so feeding it this
    already-bumped value would double-count the ratio and needlessly shrink
    the chosen font).

    Why bump it at all: `_LINE_SPACING=1.15` is a fixed constant, not
    derived from any particular font's real metrics. For a font whose real
    (ascent+descent)/em -- `extent_ratio` -- exceeds 1.15 (Inter ~1.211,
    JetBrains Mono ~1.32), a per-line box sized at `font_px * 1.15` is
    SMALLER than that font's actual rendered glyph height, i.e. negative
    leading: real ink for one line can extend past its own nominal box,
    into where the tiling math assumes the NEXT instance's >=2mm gap
    begins (measured directly: an adversarial case shrank the real
    on-tape gap to ~1.83mm). Using max(1.15, extent_ratio) as the
    multiplier instead guarantees `line_height_px >= real ascent+descent`
    always, i.e. leading_px >= 0 -- eliminating that encroachment at the
    root (the layout box itself), not just papering over its symptom."""
    return max(_LINE_SPACING, extent_ratio(family, bold))


def _text_group(
    cx: float, cy: float, lines: list[str], family: str, font_px: int, bold: bool,
    line_spacing: float,
) -> str:
    """One instance's PRE-rotation SVG: `lines` centered (both axes) on
    (cx, cy) as ordinary horizontal text, using the same per-line
    ascent/descent baseline centering text_label.py/divided_blocks.py both
    use for their own line stacks. `line_spacing` is the caller's
    `_effective_line_spacing(...)` (NOT the bare `_LINE_SPACING` constant)
    -- see that function's docstring."""
    font_obj = ImageFont.truetype(str(font_path(family, bold)), font_px)
    ascent, descent = font_obj.getmetrics()
    line_height_px = font_px * line_spacing
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


def _tile_centers(n: int, instance_len_px: float, budget_px: float, padding_px: int) -> list[float]:
    """n evenly-spaced instance centers (each instance `instance_len_px`
    wide), packed with exactly the caller-computed gap between them,
    centered as one block inside `padding_px..padding_px+budget_px`. n=1 is
    just "one instance, centered" -- the same formula, no special case
    (see module docstring's "-- Repeat --")."""
    gap_px = 0.0 if n <= 1 else (budget_px - n * instance_len_px) / (n - 1)
    content_span = n * instance_len_px + (n - 1) * gap_px
    start_x = padding_px + (budget_px - content_span) / 2
    return [start_x + instance_len_px / 2 + i * (instance_len_px + gap_px) for i in range(n)]


@register("cable_wrap")
class CableWrapRenderer(LabelRenderer):
    title = "Cable Wrap"
    category = "network"
    Params = CableWrapParams

    def render(self, params: CableWrapParams, tape: TapeSpec) -> RenderedLabel:
        warnings: list[RenderWarning] = []
        lines = params.lines
        height_px = tape.print_dots
        width_px = mm_to_dots(_wrap_length_mm(params))  # forced length, see module docstring
        padding_px = mm_to_dots(params.padding_mm)

        cross_budget_px = max(0, height_px - 2 * padding_px)  # HARD: the tape's own width
        length_budget_px = max(0, width_px - 2 * padding_px)  # one instance must fit inside it

        if params.font_size_px is None:
            font_px = fit_font_size(
                lines, params.font_family, cross_budget_px, length_budget_px, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            if font_px <= _MIN_FONT_PX:
                warnings.append(
                    RenderWarning(
                        code="text_cramped",
                        message="auto font size hit the minimum size; text may be cramped",
                    )
                )
        else:
            # Explicit size clamped against BOTH budgets (the same call
            # auto-fit above makes) -- NOT just the length budget: an
            # explicit size only marginally too wide for the cross-tape
            # budget is still a size the server CAN satisfy by shrinking a
            # little, so it must be clamped-and-warned here too, not left
            # to fall through to the unconditional hard check below and
            # 422 with "shorten or use wider tape" advice that's factually
            # wrong (a smaller font would have fit fine). That hard check
            # remains -- see module docstring -- but now only ever fires
            # when even `_MIN_FONT_PX` (fit_font_size's own fallback when
            # NOTHING in range satisfies both constraints) still doesn't
            # satisfy the cross-tape budget, i.e. genuinely unfittable.
            fit_px = fit_font_size(
                lines, params.font_family, cross_budget_px, length_budget_px, params.bold,
                line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
            )
            font_px = min(params.font_size_px, fit_px)
            if font_px < params.font_size_px:
                warnings.append(
                    RenderWarning(
                        code="font_clamped",
                        message=(
                            f"font size {params.font_size_px}px was reduced to {font_px}px "
                            "to fit this wrap"
                        ),
                    )
                )

        # -- cross-tape (width) hard check, both paths -- see module docstring --
        widest_px = max(
            (
                measure_text(line, params.font_family, font_px, params.bold)[0]
                for line in lines
                if line
            ),
            default=0,
        )
        if widest_px > cross_budget_px:
            raise ValueError(
                f"text too long for {tape.nominal_mm}mm tape -- shorten or use wider tape"
            )

        line_spacing = _effective_line_spacing(params.font_family, params.bold)
        line_height_px = font_px * line_spacing
        instance_len_px = len(lines) * line_height_px
        gap_px = mm_to_dots(_MIN_GAP_MM)

        if params.repeat:
            n = max(1, math.floor((length_budget_px + gap_px) / (instance_len_px + gap_px)))
        else:
            n = 1

        cy = height_px / 2
        body_parts = []
        for cx in _tile_centers(n, instance_len_px, length_budget_px, padding_px):
            group = _text_group(
                cx, cy, lines, params.font_family, font_px, params.bold, line_spacing
            )
            body_parts.append(
                f'<g transform="rotate(-90, {_fmt_num(cx)}, {_fmt_num(cy)})">{group}</g>'
            )

        svg = _svg_document(width_px, height_px, "".join(body_parts))
        return RenderedLabel(svg=svg, width_px=width_px, height_px=height_px, warnings=warnings)
