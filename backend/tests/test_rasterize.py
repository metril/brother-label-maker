"""Tests for labelmaker.render.rasterize: SVG -> PIL mode "1" -> preview PNG.

Synthetic SVGs are built directly in this file (not through a LabelRenderer)
per the brief -- these tests exercise the rasterizer/binarizer in isolation.
"""

import io

import pytest
from PIL import Image

from labelmaker.render import fonts as fonts_module
from labelmaker.render.document import ObjectRegion, RenderedLabel
from labelmaker.render.rasterize import preview_png, rasterize


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    )


# --- 1. rasterize(): mode, exact dimensions ---


def test_rasterize_output_mode_is_1():
    svg = _svg(20, 10, '<rect width="20" height="10" fill="white"/>')
    label = RenderedLabel(svg=svg, width_px=20, height_px=10)
    img = rasterize(label)
    assert img.mode == "1"


def test_rasterize_output_dimensions_exact():
    svg = _svg(37, 53, '<rect width="37" height="53" fill="white"/>')
    label = RenderedLabel(svg=svg, width_px=37, height_px=53)
    img = rasterize(label)
    assert img.size == (37, 53)


def test_rasterize_mismatched_declared_size_raises():
    # SVG declares 10x10 but RenderedLabel claims 99x99 -- must fail loudly,
    # never silently resize.
    svg = _svg(10, 10, '<rect width="10" height="10" fill="white"/>')
    label = RenderedLabel(svg=svg, width_px=99, height_px=99)
    with pytest.raises(ValueError, match="99"):
        rasterize(label)


# --- 1b. Font guards: missing FONTS_DIR / unbundled font-family both fail
# loudly (RuntimeError / ValueError), never degrade to a silent blank
# bitmap -- resvg itself raises nothing for either case. ---


def test_rasterize_missing_fonts_dir_raises_runtime_error(monkeypatch, tmp_path):
    svg = _svg(20, 10, '<rect width="20" height="10" fill="white"/>')
    label = RenderedLabel(svg=svg, width_px=20, height_px=10)
    monkeypatch.setattr(fonts_module, "FONTS_DIR", tmp_path / "does-not-exist")
    with pytest.raises(RuntimeError, match="fonts directory not found"):
        rasterize(label)


def test_rasterize_unbundled_font_family_raises_not_blank_bitmap():
    # Verified failure mode this guards against: without it, resvg silently
    # renders this as a blank canvas (skip_system_fonts=True means it won't
    # even fall back to a host "Arial" -- it just draws nothing) and
    # rasterize() would happily hand back an all-white bitmap with no error.
    body = (
        '<rect width="100" height="40" fill="white"/>'
        '<text x="5" y="30" font-family="Arial" font-size="24">HELLO</text>'
    )
    svg = _svg(100, 40, body)
    label = RenderedLabel(svg=svg, width_px=100, height_px=40)
    with pytest.raises(ValueError, match="Arial"):
        rasterize(label)


def test_rasterize_bundled_font_family_in_text_does_not_raise():
    body = (
        '<rect width="100" height="40" fill="white"/>'
        '<text x="5" y="30" font-family="Inter" font-size="24">HI</text>'
    )
    svg = _svg(100, 40, body)
    label = RenderedLabel(svg=svg, width_px=100, height_px=40)
    img = rasterize(label)
    # actual text rendered -- not a blank bitmap
    assert img.getextrema() != (255, 255)


# --- 2. All-white SVG -> all-white bitmap; black rect -> those pixels black ---


def test_rasterize_all_white_svg_is_all_white_bitmap():
    svg = _svg(30, 20, '<rect width="30" height="20" fill="white"/>')
    label = RenderedLabel(svg=svg, width_px=30, height_px=20)
    img = rasterize(label)
    assert img.getextrema() == (255, 255)


def test_rasterize_black_rect_pixels_are_black_background_stays_white():
    body = (
        '<rect width="40" height="20" fill="white"/>'
        '<rect x="10" y="5" width="20" height="10" fill="black"/>'
    )
    svg = _svg(40, 20, body)
    label = RenderedLabel(svg=svg, width_px=40, height_px=20)
    img = rasterize(label)
    # inside the black rect
    assert img.getpixel((20, 10)) == 0
    # outside it, on the white background
    assert img.getpixel((1, 1)) == 255
    assert img.getpixel((38, 18)) == 255


# --- 3. Dither mechanism (synthetic gradient + ObjectRegion) ---


def _vertical_gradient_svg(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="black"/><stop offset="1" stop-color="white"/>'
        "</linearGradient></defs>"
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="url(#g)"/>'
        "</svg>"
    )


def test_dither_region_has_scattered_pixels_threshold_region_has_uniform_rows():
    width, height = 100, 64
    svg = _vertical_gradient_svg(width, height)
    dither_region = ObjectRegion(x=0, y=0, width=50, height=height, mode="dither")
    label = RenderedLabel(
        svg=svg, width_px=width, height_px=height, object_map=[dither_region]
    )
    img = rasterize(label)
    assert img.size == (width, height)

    # Dithered half (x in [0, 50)): a real mix of black and white, not solid.
    black = 0
    total = 0
    for y in range(height):
        for x in range(50):
            total += 1
            if img.getpixel((x, y)) == 0:
                black += 1
    fraction_black = black / total
    assert 0.05 < fraction_black < 0.95

    # Thresholded half (x in [50, 100)): every row is a single uniform value.
    for y in range(height):
        row_values = {img.getpixel((x, y)) for x in range(50, 100)}
        assert len(row_values) == 1, f"row {y} not uniform: {row_values}"


def test_dither_mechanism_is_noop_without_object_map():
    # No ObjectRegion at all -> whole image thresholded, every row uniform.
    width, height = 40, 30
    svg = _vertical_gradient_svg(width, height)
    label = RenderedLabel(svg=svg, width_px=width, height_px=height)
    img = rasterize(label)
    for y in range(height):
        row_values = {img.getpixel((x, y)) for x in range(width)}
        assert len(row_values) == 1


# --- 4. Determinism ---


def test_rasterize_is_deterministic():
    body = (
        '<rect width="50" height="30" fill="white"/>'
        '<circle cx="25" cy="15" r="10" fill="black"/>'
    )
    svg = _svg(50, 30, body)
    label = RenderedLabel(svg=svg, width_px=50, height_px=30)
    img1 = rasterize(label)
    img2 = rasterize(label)
    assert img1.tobytes() == img2.tobytes()


# --- 5. preview_png() ---


def test_preview_png_scale_1_is_lossless_same_size():
    svg = _svg(20, 10, '<rect width="20" height="10" fill="white"/>')
    label = RenderedLabel(svg=svg, width_px=20, height_px=10)
    img = rasterize(label)
    png_bytes = preview_png(img, scale=1)
    decoded = Image.open(io.BytesIO(png_bytes))
    assert decoded.size == (20, 10)
    assert decoded.convert("1").tobytes() == img.tobytes()


def test_preview_png_scale_upscales_nearest_neighbor():
    body = (
        '<rect width="10" height="8" fill="white"/>'
        '<rect x="0" y="0" width="5" height="4" fill="black"/>'
    )
    svg = _svg(10, 8, body)
    label = RenderedLabel(svg=svg, width_px=10, height_px=8)
    img = rasterize(label)
    png_bytes = preview_png(img, scale=4)
    decoded = Image.open(io.BytesIO(png_bytes))
    assert decoded.size == (40, 32)
    # nearest-neighbor: a 4x4 block should be uniform, matching the source pixel
    decoded_l = decoded.convert("L")
    block = {decoded_l.getpixel((x, y)) for x in range(4) for y in range(4)}
    assert len(block) == 1


def test_preview_png_rejects_non_1_mode():
    img = Image.new("L", (10, 10), 128)
    with pytest.raises(ValueError, match="mode"):
        preview_png(img)


def test_preview_png_rejects_scale_below_1():
    img = Image.new("1", (10, 10), 1)
    with pytest.raises(ValueError, match="scale"):
        preview_png(img, scale=0)
