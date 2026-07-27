"""Label type "barcode": a single QR/Code128/Code39/DataMatrix code, with the
encoded data string itself doubling as an optional caption underneath.
Built on top of render/objects.py's four `*_object()` functions (task 2.5) --
this module owns layout (where the code and caption sit on the canvas) and
sizing (how big the code gets), not the code's own module geometry, which is
entirely objects.py's responsibility.

-- Sizing: `size_mode` --

`size_mode="module"`: `module_px` (1-20, default 2) is used directly as the
code's own module size (QR/DataMatrix) or bar x-dimension (Code128/Code39).
Fully manual -- the caller picked an exact size and gets exactly that,
mirroring text_label.py's explicit `font_size_px` path (no auto-fit
search).

`size_mode="auto"` (default) -- the code's height budget is the tape's full
print height (`tape.print_dots`) minus the caption's own reserved band
(`caption_block_px`, 0 if `caption="none"`; see "-- Caption --" below):

- QR/DataMatrix (2D, fixed aspect ratio -- can't stretch to fill an
  arbitrary height): `module_px` is the LARGEST integer such that
  `module_px * total_modules <= available_height_px`, where
  `total_modules` is the code's own module count (matrix size + its quiet
  zone) -- content-dependent (QR's matrix size grows with `data`'s length),
  so it's measured with a throwaway `module_px=1` probe call before the
  real one (cheap: both calls are pure-python, no I/O). This is exactly
  "the largest module that fits" the task brief asks for -- e.g. a QR
  version-1 code (21 modules + 8 quiet = 29) on a 24mm tape's 128px-tall
  print strip with no caption: `module_px = 128 // 29 = 4`.
  If even `module_px=1` doesn't fit (`available_height_px < total_modules`)
  a caption is dropped first if one was reserved (see below) rather than
  failing outright; if it STILL doesn't fit with the caption gone, this
  raises `ValueError` (surfaced as a 422 -- there is no smaller code to
  fall back to).
- Code128/Code39 (1D, no fixed aspect -- bars can be any height): there is
  nothing to search for. `x_dim_px` is simply `module_px` (the SAME field,
  default 2 -- 1D codes don't get their own "auto width" concept, per the
  task brief), and the bar HEIGHT stretches to fill the entire available
  budget (`height_px = available_height_px`, clamped to >= 1px). If a
  reserved caption would leave less than `_MIN_1D_HEIGHT_PX` for the bars,
  the caption is dropped the same way as the 2D case (never a hard error --
  a 1D code can always physically render at any positive height).

`size_mode="module"` never drops or resizes the caption to make room --
consistent with the rest of this codebase's convention that an explicit,
manually-chosen size is honored as given (see text_label.py's explicit
`font_size_px`, which clamps only against the OUTER print-height bound, not
against anything else on the label); a module_px/caption combination that
overflows the print strip is the caller's own choice, not something this
module second-guesses. The code's own `barcode_large`/`barcode_small_module`
warnings (from objects.py) still fire regardless of size_mode -- this module
never re-implements that check.

-- Caption --

`caption="below"` (default): the caption text is `data` itself -- there is
no separate caption-text field, since a barcode label's caption exists to
let a human read what the code encodes, and that IS `data`. Caption font
size is `max(_CAPTION_MIN_PX, round(0.20 * tape.print_dots))` -- "~20% of
print height, min 8px" per the task brief -- using this module's own
`font_family`/`bold` fields (the same two fields, not caption-prefixed
ones: there's exactly one piece of text on this label type, so no need for
a second namespaced pair). The caption's reserved vertical band
(`caption_block_px`, `math.ceil(caption_font_px * _LINE_SPACING)`, the same
1.15 line-spacing convention text_label.py/divided_blocks.py both use) is
"only rendered when it fits" (the task brief's phrase): in `size_mode=
"auto"` ONLY, if reserving it wouldn't leave room for even the smallest
legal code, it's dropped and a `caption_omitted` info-level warning is
attached instead of failing the whole render. Caption text itself is NOT
clamped/shrunk/wrapped to fit the code's own width -- `data` can be up to
500 chars (an entire URL), and a caption much wider than its code WILL
visibly overflow the canvas (center-anchored, so it overflows both edges,
showing only its middle slice -- the same trade-off text_label.py's fixed-
length `length_mm` makes for ordinary text, just without a length_mm knob
to fix it here since the label's width is driven by the code, not the
caption). Unlike a silent bleed past the canvas edge, this case IS flagged:
a `caption_truncated` warning fires whenever the caption's measured width
exceeds the available (padded) width, mirroring text_label.py's own
`text_truncated` convention -- see golden fixture (a) (a full URL caption
under a compact QR code) for exactly this case.

-- Layout --

The code sits inside a `padding_mm`-bordered content area, HORIZONTALLY
centered (`code_x = (width_px - code_width_px) // 2`, always an exact
integer -- see objects.py's module docstring for why fractional placement
of an already pixel-snapped code group would be self-defeating). Vertically:
the top `available_height_px` rows are the code's own band (2D: centered
within it; 1D: fills it exactly by construction) and, when present, the
caption occupies the remaining band at the bottom, itself vertically
centered within that band using the same ascent/descent centering
text_label.py uses. `padding_mm` only ever affects WIDTH (matching every
other label type in this codebase -- text_label.py's `padding_px` is
likewise width-only): label `width_px` is either `code_width_px + 2 *
padding_px` (auto, `length_mm=None`) or the resolved fixed `length_mm`
(clamped to `[MIN_LABEL_MM, tape.max_length_mm]`, same as text_label.py) --
in the fixed case, if the code doesn't fit inside `width_px - 2*padding_px`
this raises `ValueError` (422) rather than clipping it (unlike
text_label.py's fixed-length text, which clips-and-warns: a barcode
partially cut off is not a smaller barcode, it's an unscannable one).
"""

from __future__ import annotations

import math
from typing import Literal

from PIL import ImageFont
from pydantic import BaseModel, Field, field_validator, model_validator

from labelmaker.driver.geometry import MIN_LABEL_MM, TapeSpec, mm_to_dots
from labelmaker.render.document import RenderedLabel, RenderWarning, _svg_document, _text_element
from labelmaker.render.fonts import font_path, list_fonts, measure_text
from labelmaker.render.objects import (
    CODE39_CHARSET,
    BarcodeResult,
    code39_object,
    code128_object,
    datamatrix_object,
    qr_object,
)
from labelmaker.render.types.base import LabelRenderer, register

Symbology = Literal["qr", "code128", "code39", "datamatrix"]

_MAX_DATA_CHARS = 500
_MIN_MODULE_PX = 1
_MAX_MODULE_PX = 20
_DEFAULT_MODULE_PX = 2

_CAPTION_FRACTION = 0.20
_CAPTION_MIN_PX = 8
_LINE_SPACING = 1.15  # matches text_label.py/divided_blocks.py's own convention
_MIN_1D_HEIGHT_PX = 4  # a 1D barcode shorter than this isn't usefully a barcode anymore

_VALID_FAMILIES = {f.family for f in list_fonts()}

_2D_SYMBOLOGIES = frozenset({"qr", "datamatrix"})


class BarcodeLabelParams(BaseModel):
    symbology: Symbology = Field("qr", description="which barcode type to encode data as")
    data: str = Field(
        min_length=1,
        max_length=_MAX_DATA_CHARS,
        description="the value encoded in the code (also the caption text, when shown)",
    )
    caption: Literal["none", "below"] = Field(
        "below", description="show the encoded data as text under the code, or not"
    )
    size_mode: Literal["auto", "module"] = Field(
        "auto",
        description=(
            "auto: largest module size that fits the tape (2D) / stretch to fill "
            "height (1D); module: use module_px exactly"
        ),
    )
    module_px: int = Field(
        _DEFAULT_MODULE_PX,
        ge=_MIN_MODULE_PX,
        le=_MAX_MODULE_PX,
        description=(
            "module size in px (QR/DataMatrix) or bar x-dimension (Code128/Code39); "
            "used directly when size_mode='module', and always for 1D x-dimension"
        ),
    )
    length_mm: float | None = Field(
        None, description="fixed label length in mm; omit for auto (content-fit) width"
    )
    font_family: str = Field("Inter", description="caption font family name (see GET /api/fonts)")
    bold: bool = Field(False, description="bold caption text weight")
    padding_mm: float = Field(
        default=2.0, ge=0, description="content padding on the left/right of the code"
    )

    @field_validator("font_family")
    @classmethod
    def _check_font_family(cls, family: str) -> str:
        if family not in _VALID_FAMILIES:
            raise ValueError(f"unknown font_family {family!r}; valid: {sorted(_VALID_FAMILIES)}")
        return family

    @model_validator(mode="after")
    def _check_code39_charset(self) -> BarcodeLabelParams:
        if self.symbology == "code39":
            invalid = sorted({ch for ch in self.data if ch not in CODE39_CHARSET})
            if invalid:
                raise ValueError(
                    f"code39 data contains invalid character(s) {invalid}; valid charset is "
                    "digits, uppercase A-Z, and -. $/+% and space"
                )
        return self


def _caption_omitted_warning(symbology: str) -> RenderWarning:
    return RenderWarning(
        code="caption_omitted",
        severity="info",
        message=(
            f"caption omitted: this tape isn't tall enough to fit both a caption and a "
            f"readable {symbology} code"
        ),
    )


@register("barcode")
class BarcodeLabelRenderer(LabelRenderer):
    title = "Barcode"
    category = "general"
    Params = BarcodeLabelParams

    def render(self, params: BarcodeLabelParams, tape: TapeSpec) -> RenderedLabel:
        warnings: list[RenderWarning] = []
        height_px = tape.print_dots
        padding_px = mm_to_dots(params.padding_mm)
        is_2d = params.symbology in _2D_SYMBOLOGIES

        caption_enabled = params.caption == "below"
        caption_font_px = 0
        caption_block_px = 0
        if caption_enabled:
            caption_font_px = max(_CAPTION_MIN_PX, round(_CAPTION_FRACTION * height_px))
            caption_block_px = math.ceil(caption_font_px * _LINE_SPACING)

        available_height_px = height_px - caption_block_px if caption_enabled else height_px

        def _drop_caption() -> None:
            nonlocal caption_enabled, caption_block_px, available_height_px
            caption_enabled = False
            caption_block_px = 0
            available_height_px = height_px
            warnings.append(_caption_omitted_warning(params.symbology))

        code_result: BarcodeResult
        if is_2d:
            build_2d = qr_object if params.symbology == "qr" else datamatrix_object
            if params.size_mode == "auto":
                total_modules = build_2d(params.data, module_px=1).width_px
                if caption_enabled and available_height_px < total_modules:
                    _drop_caption()
                module_px = available_height_px // total_modules
                if module_px < _MIN_MODULE_PX:
                    raise ValueError(
                        f"{params.symbology} code needs at least {total_modules}px of print "
                        f"height (only {available_height_px}px available on this tape) -- "
                        "try a taller tape"
                    )
                module_px = min(module_px, _MAX_MODULE_PX)
            else:
                module_px = params.module_px
            code_result = build_2d(params.data, module_px=module_px)
        else:
            build_1d = code128_object if params.symbology == "code128" else code39_object
            x_dim_px = params.module_px
            if (
                params.size_mode == "auto"
                and caption_enabled
                and available_height_px < _MIN_1D_HEIGHT_PX
            ):
                _drop_caption()
            barcode_height_px = max(1, available_height_px)
            code_result = build_1d(params.data, x_dim_px=x_dim_px, height_px=barcode_height_px)

        warnings.extend(code_result.warnings)
        code_width_px = code_result.width_px
        code_height_px = code_result.height_px

        # -- label width_px: auto content-fit, or fixed with a hard 422 if the
        # code doesn't fit (see module docstring's "-- Layout --" section) --
        if params.length_mm is None:
            width_px = code_width_px + 2 * padding_px
        else:
            clamped_length_mm = max(MIN_LABEL_MM, min(tape.max_length_mm, params.length_mm))
            width_px = mm_to_dots(clamped_length_mm)
            available_width_px = width_px - 2 * padding_px
            if code_width_px > available_width_px:
                raise ValueError(
                    f"{params.symbology} code is {code_width_px}px wide; does not fit within "
                    f"the fixed label length {params.length_mm}mm ({available_width_px}px "
                    f"available after {params.padding_mm}mm padding on each side)"
                )

        code_x = (width_px - code_width_px) // 2
        code_y = (available_height_px - code_height_px) // 2 if is_2d else 0
        body = f'<g transform="translate({code_x},{code_y})">{code_result.svg_group}</g>'

        if caption_enabled:
            available_caption_width_px = max(0, width_px - 2 * padding_px)
            caption_width_px = measure_text(
                params.data, params.font_family, caption_font_px, params.bold
            )[0]
            if caption_width_px > available_caption_width_px:
                warnings.append(
                    RenderWarning(
                        code="caption_truncated",
                        message=(
                            "caption text is wider than the label and will be visually "
                            "cut off; use a fixed length_mm to widen the label"
                        ),
                    )
                )

            font_obj = ImageFont.truetype(
                str(font_path(params.font_family, params.bold)), caption_font_px
            )
            ascent, descent = font_obj.getmetrics()
            line_height_px = caption_font_px * _LINE_SPACING
            band_top_px = available_height_px
            band_height_px = height_px - available_height_px
            leading_px = line_height_px - (ascent + descent)
            baseline_y = (
                band_top_px
                + max(0, band_height_px - line_height_px) / 2
                + leading_px / 2
                + ascent
            )
            body += _text_element(
                width_px / 2,
                baseline_y,
                params.data,
                params.font_family,
                caption_font_px,
                text_anchor="middle",
                bold=params.bold,
            )

        svg = _svg_document(width_px, height_px, body)
        return RenderedLabel(svg=svg, width_px=width_px, height_px=height_px, warnings=warnings)
