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
"""

import io

import resvg_py
from PIL import Image

from labelmaker.render.document import RenderedLabel
from labelmaker.render.fonts import FONTS_DIR

_THRESHOLD = 128  # matches the docstring above: pixel value >= 128 -> white


def rasterize(label: RenderedLabel) -> Image.Image:
    # skip_system_fonts=True + font_dirs=[FONTS_DIR]: resvg resolves every
    # font-family in the SVG exclusively against the bundled TTFs, never
    # whatever happens to be installed on the host -- this is what makes
    # preview and print deterministic across machines/containers.
    png_bytes = resvg_py.svg_to_bytes(
        svg_string=label.svg,
        skip_system_fonts=True,
        font_dirs=[str(FONTS_DIR)],
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
