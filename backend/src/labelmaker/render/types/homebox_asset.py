"""Label type "homebox_asset": a HomeBox inventory asset tag -- a QR code
(the asset's own resolution URL) at the label's left edge, occupying the
full print height, with an asset-id / name / location text column to its
right.

Like every other type in this package, this renders SYNCHRONOUSLY -- it
cannot itself resolve a HomeBox asset id to a display name, or walk
HomeBox's location tree for a breadcrumb (see render/document.py's module
docstring: render/ never does I/O). All of that resolution happens
CLIENT-SIDE (the browse page, task 3.4) before a LabelDefinition is ever
built: `asset_id`/`name`/`location` are already the exact display strings
to print, and `qr_data` is already the full URL HomeBox's own QR scheme
expects (`https://{base}/a/{asset_id}` per docs/research/homebox.md #39/#40
-- composed by the CALLER, never re-derived here from `asset_id`, since
HomeBox asset ids aren't guaranteed unique on their own). This module is
therefore pure layout: a handful of strings in, an SVG out -- no different
in kind from text_label.py.

-- Layout --

    [-------- QR ---------][gap][ ASSET-ID   (big, JetBrains Mono, bold)  ]
    [   (square, full      ]    [ Name        (Roboto Condensed)          ]
    [    print height)     ]    [ Location    (Roboto Condensed, smaller) ]
    ^padding            ^padding                                  padding^

QR sizing directly mirrors barcode_label.py's own 2D `size_mode="auto"`
formula (see that module's docstring's "-- Sizing --" section): a
`module_px=1` probe call measures `total_modules` (content-dependent -- a
QR's own matrix size grows with `qr_data`'s length), then `module_px =
height_px // total_modules` (the largest integer module size that still
fits the tape's full print height), clamped to `_MAX_MODULE_PX` (20, same
ceiling barcode_label.py uses), raising `ValueError` if even `module_px=1`
doesn't fit (no smaller code to fall back to -- surfaced as a 422). Unlike
barcode_label.py there is no caption band to reserve first: the QR always
gets the tape's FULL print-height budget. It is vertically centered in that
budget (`qr_y = (height_px - qr_size_px) // 2`), exactly like
barcode_label.py's own 2D `code_y` centering, since a floor-rounded
`module_px` can leave the code a few px shorter than the full height.
`objects.qr_object`'s own `barcode_small_module`/`barcode_large` warnings
bubble up unchanged -- this module never re-implements that check (the same
convention barcode_label.py documents for itself).

With `show_qr=False` the QR is omitted entirely and this becomes a
text-only asset tag: `content_left_px` (the text column's left edge --
exactly text_label.py's own icon convention, "text shifts right to make
room") reduces to plain `padding_px`.

-- Text column: three ROLES, not N uniform lines --

Unlike text_label.py's `lines` (any number of same-size, same-font lines)
or divided_blocks.py's per-block stack (each block gets ONE shared size),
this label has three semantically distinct, differently-sized ROLES:
`asset_id` (JetBrains Mono, bold -- an identifier meant to be read back
character-for-character, hence a monospace face) is the largest; `name`
beneath it in Roboto Condensed (a human-readable label, condensed to leave
more width for longer names); `location` beneath THAT, same face, smaller
still (a secondary breadcrumb, shown only when the caller resolved one).

Each role's own font size is auto-fit independently via `fit_font_size` --
the SAME helper text_label.py/barcode_label.py/divided_blocks.py all use --
against a single-line budget `(None, role_band_height_px)`: `None` because,
exactly like text_label.py's own auto-length mode, WIDTH is never a fitting
constraint here (the label's width grows to fit whatever the text measures
at its chosen size, never the reverse). `role_band_height_px` is
`height_px * role_weight / total_weight`, a proportional division of the
tape's full print height among however many roles are actually present,
using fixed integer weights (`asset_id`=5, `name`=3, `location`=2 -- roughly
50/30/20% when all three show) -- the same weighted-proportional-division
idea divided_blocks.py's own `layout_blocks` uses to split a label's LENGTH
among blocks, applied here to HEIGHT among text roles instead. Each role
individually landing inside its own budget (via `fit_font_size`'s own
height check) means the stacked line-heights never exceed the tape's full
print height in total. A role whose budget is too small even at
`fit_font_size`'s `_MIN_FONT_PX` floor gets the standard `text_cramped` info
warning (same code/convention as every other auto-fit-floor case in this
codebase), named by `object_id` (`"asset_id"`/`"name"`/`"location"`) so a
caller can tell which role is cramped.

`location` (default `""`, 0-160 chars -- a HomeBox item isn't always filed
under a resolved location) is DROPPED from the role list entirely when
blank, rather than reserved-but-empty: the weighted division above then
splits the full height between just `asset_id` and `name` (5:3, not 5:3:2),
so dropping location gives the remaining two roles MORE room, not a wasted
blank band -- the label auto-adapts, not just auto-omits.

The (2 or 3) lines are stacked and vertically centered as one block
(`block_top_px = (height_px - block_height_px) / 2`, `block_height_px =
sum(role_font_px * _LINE_SPACING)`) using the same per-line ascent/descent
baseline centering text_label.py/divided_blocks.py both use, just with a
DIFFERENT font/size per line instead of one shared pair. Left-aligned
(`text_anchor="start"` at `content_left_px`) -- an asset tag reads like a
shipping label, not centered prose.

-- Width: auto (content-fit), never fixed --

There is no `length_mm` param at all (unlike text_label.py/
barcode_label.py): this type has no fixed-length mode. `width_px =
content_left_px + widest_role_px + padding_px` (clamped up to
`MIN_LABEL_MM`), where `widest_role_px` is the widest of the present roles'
own measured widths at their own chosen font/size -- exactly
text_label.py's own auto-length formula, generalized from "widest LINE" to
"widest ROLE".

-- min_tape_mm --

12.0 (not None): this type defaults to `show_qr=True`, and a QR rendered too
small to scan reliably is the dominant failure mode on very narrow tape, so
it advertises a sensible floor for a future type picker (task 2.10) --
unlike barcode_label.py (whose QR is one of several caller-chosen
symbologies, most without a comparable floor, so it leaves
`min_tape_mm=None` and lets a too-narrow render simply 422). `min_tape_mm`
is advisory metadata only (see `LabelTypeInfo`'s own docstring: "grouping
for a future type picker") -- nothing in `render_definition()` enforces it,
so a caller can still request (and get a 422 from) a narrower tape; it also
says nothing about `show_qr=False` renders, which have no QR size
constraint at all.
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

_ID_FAMILY = "JetBrains Mono"
_TEXT_FAMILY = "Roboto Condensed"

# Proportional height-weight per text role (see module docstring's "-- Text
# column --" section) -- summed only over roles actually present (location
# is dropped entirely, not just zero-weighted, when blank).
_ID_WEIGHT = 5
_NAME_WEIGHT = 3
_LOCATION_WEIGHT = 2


class HomeboxAssetParams(BaseModel):
    asset_id: str = Field(
        min_length=1,
        max_length=32,
        description='the asset\'s display id (e.g. "000-042"); rendered in JetBrains Mono',
    )
    name: str = Field(min_length=1, max_length=120, description="the asset's display name")
    location: str = Field(
        "",
        max_length=160,
        description=(
            'pre-resolved location breadcrumb (e.g. "Garage › Shelf B"); omitted '
            "from the label entirely when blank"
        ),
    )
    qr_data: str = Field(
        min_length=1,
        max_length=512,
        description=(
            "the full URL to encode, already composed by the caller per HomeBox's own "
            "QR scheme -- rendered verbatim, never re-derived from asset_id"
        ),
    )
    show_qr: bool = Field(
        True, description="render the QR code; False produces a text-only asset tag"
    )


class _TextRole(NamedTuple):
    key: str
    text: str
    family: str
    bold: bool
    weight: int


def _qr_group(data: str, height_px: int) -> tuple[str, int, list[RenderWarning]]:
    """QR sized to the largest module that fits `height_px` -- barcode_label.py's
    own 2D `size_mode="auto"` formula (see this module's docstring), minus
    its caption-band reservation (there is none here). Returns the code's
    own (0,0)-relative SVG group, its square pixel size, and
    `objects.qr_object`'s own warnings, unchanged."""
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
    band (see module docstring's "-- Text column --" section) -- width is
    never a fitting constraint (auto-length mode, exactly text_label.py's
    own auto-length convention: `max_width_px=None`). Appends the standard
    `text_cramped` info warning, named by `role.key`, if `fit_font_size`
    fell back to its own `_MIN_FONT_PX` floor."""
    font_px = fit_font_size(
        [role.text],
        role.family,
        None,
        band_height_px,
        role.bold,
        line_spacing=_LINE_SPACING,
        min_px=_MIN_FONT_PX,
        max_px=_MAX_FONT_PX,
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


@register("homebox_asset")
class HomeboxAssetRenderer(LabelRenderer):
    title = "HomeBox Asset"
    category = "homebox"
    min_tape_mm = _MIN_TAPE_MM
    Params = HomeboxAssetParams

    def render(
        self, params: HomeboxAssetParams, tape: TapeSpec, *, data_dir: Path | None = None
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

        roles = [
            _TextRole("asset_id", params.asset_id, _ID_FAMILY, True, _ID_WEIGHT),
            _TextRole("name", params.name, _TEXT_FAMILY, False, _NAME_WEIGHT),
        ]
        if params.location.strip():
            roles.append(
                _TextRole("location", params.location, _TEXT_FAMILY, False, _LOCATION_WEIGHT)
            )

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
                    content_left_px,
                    baseline_y,
                    role.text,
                    role.family,
                    font_px,
                    text_anchor="start",
                    bold=role.bold,
                )
            )
            cursor_px += line_height_px

        body = qr_svg + "".join(text_parts)
        svg = _svg_document(width_px, height_px, body)
        return RenderedLabel(svg=svg, width_px=width_px, height_px=height_px, warnings=warnings)
