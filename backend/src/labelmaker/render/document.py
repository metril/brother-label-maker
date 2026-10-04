"""SVG document model: the canonical, renderer-agnostic label description.

Every label is expressed as one of these documents before it ever touches a
rasterizer. render/ never imports labelmaker.driver EXCEPT
labelmaker.driver.geometry -- TapeSpec/geometry is shared vocabulary between
the render stack and the printer driver, nothing else is.
"""

from typing import Literal

from pydantic import BaseModel

from labelmaker.driver.geometry import MediaFamily, TapeSpec, all_tapes

_FAMILY_MAP: dict[str, MediaFamily] = {
    "tze": MediaFamily.TZE,
    "hse_2_1": MediaFamily.HSE_2_1,
    "hse_3_1": MediaFamily.HSE_3_1,
}

# Reverse of _FAMILY_MAP -- built from it (not hand-duplicated) so the two
# vocabularies can never drift apart.
_FAMILY_NAMES: dict[MediaFamily, str] = {family: name for name, family in _FAMILY_MAP.items()}


def family_name(family: MediaFamily) -> str:
    """The short vocabulary string ("tze"/"hse_2_1"/"hse_3_1") Tape.family
    and LabelDefinition accept, for a driver MediaFamily -- used by GET
    /api/tapes (router_labels.py) to report each geometry.TapeSpec's family
    in the same vocabulary a client would send back in a Tape."""
    return _FAMILY_NAMES[family]


class ObjectRegion(BaseModel):
    """A rectangular region of a rasterized label with a non-default 1-bit
    conversion mode. Only "dither" regions need listing -- everywhere else
    on the label is thresholded by default."""

    x: int
    y: int
    width: int
    height: int
    mode: Literal["threshold", "dither"]


class RenderWarning(BaseModel):
    """A structured, machine-checkable warning a LabelRenderer can attach to
    its RenderedLabel (e.g. text_label.py's "auto font size hit the
    minimum" / "content wider than the fixed label length" / "explicit
    font size was clamped" cases). `code` is a stable identifier a caller
    can branch on programmatically; `message` is the human-readable text a
    UI shows verbatim (e.g. LabelPreview.tsx's warning chips) -- callers
    should prefer matching on `code`, never on `message` text, so wording
    can change freely without breaking anything downstream."""

    code: str
    severity: Literal["info", "warning"] = "warning"
    message: str
    object_id: str | None = None


class RenderedLabel(BaseModel):
    """The output of a LabelRenderer: an SVG document plus its device-pixel
    canvas size. This is the ONE artifact both the preview PNG and the
    printer bitmap are produced from -- see rasterize.py."""

    svg: str
    width_px: int
    height_px: int  # device pixels; height_px == tape.print_dots
    object_map: list[ObjectRegion] = []
    warnings: list[RenderWarning] = []


class Tape(BaseModel):
    """A tape selection as it comes from a label definition: nominal width in
    mm plus a media family. Resolved to a driver TapeSpec via .resolve()."""

    width_mm: float
    family: Literal["tze", "hse_2_1", "hse_3_1"] = "tze"

    def resolve(self) -> TapeSpec:
        """Resolve to the driver's TapeSpec by an EXACT nominal_mm match
        within this tape's family.

        Deliberately does NOT go through geometry.find_tape(), which matches
        on the printer's reported status_width_mm (an integer, rounded) --
        that would silently conflate e.g. a nominal 24mm hse_2_1 request with
        the real 23.6mm hse_2_1 tape, since both report status_width_mm==24.
        A label definition's tape width is a value the user chose, not a
        rounded status byte, so it must match exactly or fail loudly.
        """
        media_family = _FAMILY_MAP[self.family]
        for tape in all_tapes():
            if tape.family is media_family and tape.nominal_mm == self.width_mm:
                return tape
        valid = sorted(t.nominal_mm for t in all_tapes() if t.family is media_family)
        raise ValueError(
            f"no {self.family!r} tape with nominal width {self.width_mm}mm; valid widths: {valid}"
        )


class LabelDefinition(BaseModel):
    """A label as requested by a caller: a type name, a tape, and that
    type's own (not-yet-validated) params. See types/base.py's
    render_definition() for how params gets validated against the type's
    own Params model."""

    type: str
    tape: Tape
    params: dict


# --- SVG helpers (module-private) -------------------------------------------
#
# No external SVG library -- labels are simple enough (background rect +
# text elements) that hand-built strings are clearer and dependency-free.
# All coordinates are device px (1 SVG user unit == 1 output pixel, since
# RenderedLabel.svg's width/height attributes are unitless numbers and
# rasterize.py never asks resvg to rescale).


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _svg_document(width_px: int, height_px: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}">'
        f'<rect x="0" y="0" width="{width_px}" height="{height_px}" fill="white"/>'
        f"{body}"
        f"</svg>"
    )


def _fmt_num(value: float) -> str:
    """Format a coordinate/size with fixed 2-decimal precision, trimmed of
    trailing zeros -- keeps generated SVG (and therefore golden PNGs)
    deterministic across platforms instead of relying on Python's default
    float repr."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _text_element(
    x: float,
    y: float,
    text: str,
    font_family: str,
    font_size_px: float,
    text_anchor: str = "start",
    bold: bool = False,
) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'<text x="{_fmt_num(x)}" y="{_fmt_num(y)}" font-family="{_escape_xml(font_family)}" '
        f'font-size="{_fmt_num(font_size_px)}" text-anchor="{text_anchor}"{weight}>'
        f"{_escape_xml(text)}</text>"
    )
