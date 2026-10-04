"""Label type "homebox_location": a HomeBox storage-location tag -- a QR code
(the location's own resolution URL) at the label's left edge, occupying the
full print height, with a name / breadcrumb-path text column to its right.

The sibling of homebox_asset.py -- same synchronous, pure-layout contract
(see that module's docstring for the full "why no I/O" reasoning: `name`/
`path` are already-resolved display strings, `qr_data` is already the full
URL HomeBox's own QR scheme expects, `https://{base}/location/{uuid}` per
docs/research/homebox.md #39 -- composed by the CALLER, rendered here
verbatim). Deliberately NOT built by importing homebox_asset.py's own
helpers: this codebase's convention for closely related "thin" label types
is each stays self-contained (see cable_flag.py's module docstring, which
reimplements cable_wrap.py's own `_text_group` locally rather than sharing
it -- "not a published shared utility") -- the two `_qr_group`/`_role_font_px`
helpers below are intentionally near-identical to homebox_asset.py's own,
not a divergence to fix.

-- Layout --

    [-------- QR ---------][gap][ Location Name (big, Roboto Condensed, bold) ]
    [   (square, full      ]    [ Ancestor › Path  (Roboto Condensed, smaller)]
    [    print height)     ]
    ^padding            ^padding                                     padding^

QR sizing, `show_qr=False`'s text-only fallback, and the width/height
layout math are IDENTICAL to homebox_asset.py's own (see that module's
docstring's "-- Layout --"/"-- Width --" sections) -- this type just has
two text ROLES instead of three: `name` (Roboto Condensed, BOLD -- unlike
homebox_asset's non-bold `name` role, this label's name IS the biggest,
most prominent element, so it gets the same bold weight `asset_id` has
there) and `path` (Roboto Condensed, regular, smaller -- the ancestor
breadcrumb, e.g. "Garage › Workshop"). `path` (default `""`, 0-160 chars --
a top-level location has no ancestors) is dropped from the role list
entirely when blank, exactly like homebox_asset's `location` -- the freed
height budget goes to `name` alone, which then gets the tape's FULL print
height to auto-fit against (a single-role render is just the n=1 case of
the same weighted-division formula, not a separate code path).

Weights: `name`=6, `path`=4 (60/40 when both show) -- a slightly more
lopsided split than homebox_asset's 5:3 asset_id:name (62.5:37.5) is close
enough that reusing the same two integers wasn't worth a second pair of
constants; 6:4 was chosen simply because it reduces to the same 60/40 ratio
with smaller integers.

-- min_tape_mm --

12.0, same reasoning and same advisory-only caveat as homebox_asset.py's
own `min_tape_mm` (see that module's docstring's "-- min_tape_mm --"
section) -- this type also defaults to `show_qr=True`.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from PIL import ImageFont
from pydantic import BaseModel, Field

from labelmaker.driver.geometry import MIN_LABEL_MM, TapeSpec, mm_to_dots
from labelmaker.render.document import RenderedLabel, RenderWarning, _svg_document, _text_element
from labelmaker.render.fonts import fit_font_size, font_path, measure_text
from labelmaker.render.objects import qr_object
from labelmaker.render.types.base import LabelRenderer, register

_LINE_SPACING = 1.15
_MIN_FONT_PX = 6
_MAX_FONT_PX = 128
_MIN_MODULE_PX = 1
_MAX_MODULE_PX = 20
_PADDING_MM = 2.0
_MIN_TAPE_MM = 12.0

_TEXT_FAMILY = "Roboto Condensed"

# Proportional height-weight per text role (see module docstring) -- summed
# only over roles actually present (path is dropped entirely, not just
# zero-weighted, when blank).
_NAME_WEIGHT = 6
_PATH_WEIGHT = 4


class HomeboxLocationParams(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="the location's display name")
    path: str = Field(
        "",
        max_length=160,
        description=(
            'pre-resolved ancestor breadcrumb (e.g. "Garage › Workshop"); omitted '
            "from the label entirely when blank"
        ),
    )
    qr_data: str = Field(
        min_length=1,
        max_length=512,
        description=(
            "the full URL to encode, already composed by the caller per HomeBox's own "
            "QR scheme -- rendered verbatim"
        ),
    )
    show_qr: bool = Field(
        True, description="render the QR code; False produces a text-only location tag"
    )


class _TextRole(NamedTuple):
    key: str
    text: str
    family: str
    bold: bool
    weight: int


def _qr_group(data: str, height_px: int) -> tuple[str, int, list[RenderWarning]]:
    """QR sized to the largest module that fits `height_px` -- see
    homebox_asset.py's own `_qr_group` (this module's docstring explains why
    it's duplicated rather than imported)."""
    total_modules = qr_object(data, module_px=1).width_px
    module_px = height_px // total_modules
    if module_px < _MIN_MODULE_PX:
        raise ValueError(
            f"QR code needs at least {total_modules}px of print height (only "
            f"{height_px}px available on this tape) -- try a taller tape"
        )
    module_px = min(module_px, _MAX_MODULE_PX)
    result = qr_object(data, module_px=module_px)
    return result.svg_group, result.width_px, result.warnings


def _role_font_px(role: _TextRole, band_height_px: float, warnings: list[RenderWarning]) -> int:
    """One role's own auto-fit font size against its proportional height
    band -- see homebox_asset.py's own `_role_font_px` for the full
    reasoning (width is never a fitting constraint here either)."""
    font_px = fit_font_size(
        [role.text], role.family, None, band_height_px, role.bold,
        line_spacing=_LINE_SPACING, min_px=_MIN_FONT_PX, max_px=_MAX_FONT_PX,
    )
    if font_px <= _MIN_FONT_PX:
        warnings.append(
            RenderWarning(
                code="text_cramped",
                severity="info",
                message=f"{role.key} auto font size hit the minimum size; text may be cramped",
                object_id=role.key,
            )
        )
    return font_px


@register("homebox_location")
class HomeboxLocationRenderer(LabelRenderer):
    title = "HomeBox Location"
    category = "homebox"
    min_tape_mm = _MIN_TAPE_MM
    Params = HomeboxLocationParams

    def render(
        self, params: HomeboxLocationParams, tape: TapeSpec, *, data_dir: Path | None = None
    ) -> RenderedLabel:
        warnings: list[RenderWarning] = []
        height_px = tape.print_dots
        padding_px = mm_to_dots(_PADDING_MM)

        qr_svg = ""
        if params.show_qr:
            qr_group, qr_size_px, qr_warnings = _qr_group(params.qr_data, height_px)
            warnings.extend(qr_warnings)
            qr_y = (height_px - qr_size_px) // 2
            qr_svg = f'<g transform="translate({padding_px},{qr_y})">{qr_group}</g>'
            content_left_px = padding_px + qr_size_px + padding_px
        else:
            content_left_px = padding_px

        roles = [_TextRole("name", params.name, _TEXT_FAMILY, True, _NAME_WEIGHT)]
        if params.path.strip():
            roles.append(_TextRole("path", params.path, _TEXT_FAMILY, False, _PATH_WEIGHT))

        total_weight = sum(role.weight for role in roles)
        font_px_by_role = {
            role.key: _role_font_px(role, height_px * role.weight / total_weight, warnings)
            for role in roles
        }

        widest_px = max(
            measure_text(role.text, role.family, font_px_by_role[role.key], role.bold)[0]
            for role in roles
        )
        width_px = max(content_left_px + widest_px + padding_px, mm_to_dots(MIN_LABEL_MM))

        block_height_px = sum(font_px_by_role[role.key] * _LINE_SPACING for role in roles)
        cursor_px = (height_px - block_height_px) / 2
        text_parts = []
        for role in roles:
            font_px = font_px_by_role[role.key]
            font_obj = ImageFont.truetype(str(font_path(role.family, role.bold)), font_px)
            ascent, descent = font_obj.getmetrics()
            line_height_px = font_px * _LINE_SPACING
            leading_px = line_height_px - (ascent + descent)
            baseline_y = cursor_px + leading_px / 2 + ascent
            text_parts.append(
                _text_element(
                    content_left_px, baseline_y, role.text, role.family, font_px,
                    text_anchor="start", bold=role.bold,
                )
            )
            cursor_px += line_height_px

        body = qr_svg + "".join(text_parts)
        svg = _svg_document(width_px, height_px, body)
        return RenderedLabel(svg=svg, width_px=width_px, height_px=height_px, warnings=warnings)
