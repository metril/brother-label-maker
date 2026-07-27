"""SVG -> PIL mode "1" bitmap -> preview PNG: the ONE render path.

Pipeline: SVG string -> RGBA (resvg) -> composite over white -> grayscale
("L") -> per-pixel threshold at 128 (>= 128 -> white) -> mode "1". Any
ObjectRegion with mode "dither" gets Floyd-Steinberg error-diffusion dither
instead of a hard threshold for that rectangle (crop -> convert("1",
dither=FLOYDSTEINBERG) -> paste back). No dither regions exist in any
bundled label type yet -- the mechanism ships now, exercised by synthetic
tests in test_rasterize.py, so a future photo/logo object type can opt in
without touching this module.

preview_png() encodes the EXACT same mode "1" image rasterize() produced --
never a second render path -- as a lossless PNG, optionally upscaled with
nearest-neighbor resampling (never smoothed: on-screen preview must show
literal print pixels, not an interpolated approximation of them).

Font-family guard: resvg fails silent, not loud, for fonts it can't find --
an unreadable/missing font_dirs entry, or a font-family with no matching
loaded font, both render as blank whitespace with no exception. That would
mean a missing/misplaced backend/assets/fonts (a real risk: FONTS_DIR's
"sibling to backend/src/" layout assumption doesn't hold for every install
shape, e.g. a bare wheel install) or a future label type emitting an
unbundled font-family produces a label whose preview and print are both
silently blank instead of an error surfaced to the caller. rasterize()
guards both failure modes before ever calling resvg: fonts.ensure_fonts_dir()
for the first, and extracting every font-family the SVG references (regex
over the SVG string -- document.py's _text_element always emits a plain
font-family="..." attribute, so this is exact for every SVG this package
produces, and it protects any future renderer's output too, not just ones
that remember to declare their fonts via some separate metadata field) for
the second.
"""

import io
import re

import resvg_py
from PIL import Image

from labelmaker.render import fonts
from labelmaker.render.document import RenderedLabel

_FONT_FAMILY_ATTR_RE = re.compile(r'font-family="([^"]*)"')


def _referenced_font_families(svg: str) -> set[str]:
    return set(_FONT_FAMILY_ATTR_RE.findall(svg))


def rasterize(label: RenderedLabel) -> Image.Image:
    fonts.ensure_fonts_dir()

    bundled_families = {f.family for f in fonts.list_fonts()}
    unknown_families = _referenced_font_families(label.svg) - bundled_families
    if unknown_families:
        raise ValueError(
            f"SVG references unbundled font-family(ies): {sorted(unknown_families)}; "
            f"bundled families: {sorted(bundled_families)}"
        )

    # skip_system_fonts=True + font_dirs=[FONTS_DIR]: resvg resolves every
    # font-family in the SVG exclusively against the bundled TTFs, never
    # whatever happens to be installed on the host -- this is what makes
    # preview and print deterministic across machines/containers.
    png_bytes = resvg_py.svg_to_bytes(
        svg_string=label.svg,
        skip_system_fonts=True,
        font_dirs=[str(fonts.FONTS_DIR)],
    )
    rgba = Image.open(io.BytesIO(bytes(png_bytes))).convert("RGBA")
    if rgba.size != (label.width_px, label.height_px):
        raise ValueError(
            f"resvg rendered {rgba.size}, expected ({label.width_px}, {label.height_px}) "
            "-- the SVG's width/height attributes must match RenderedLabel exactly"
        )

    white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, rgba)
    grayscale = composited.convert("L")

    thresholded = grayscale.convert("1", dither=Image.Dither.NONE)
    result = thresholded.copy()
    for region in label.object_map:
        if region.mode != "dither":
            continue
        box = (region.x, region.y, region.x + region.width, region.y + region.height)
        crop = grayscale.crop(box)
        dithered = crop.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        result.paste(dithered, box)
    return result


def preview_png(img_1bit: Image.Image, scale: int = 1) -> bytes:
    if img_1bit.mode != "1":
        raise ValueError(f"image mode must be '1', got {img_1bit.mode!r}")
    if scale < 1:
        raise ValueError(f"scale must be >= 1, got {scale}")

    img = img_1bit
    if scale > 1:
        img = img.resize(
            (img.width * scale, img.height * scale), resample=Image.Resampling.NEAREST
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
