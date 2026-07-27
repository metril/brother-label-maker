"""Tests for labelmaker.render.objects: QR/Code128/Code39/DataMatrix as
pixel-snapped SVG rect groups (task 2.5).

180dpi is marginal for barcodes (see objects.py's module docstring) -- the
point of this file is verifying every group lands EVERY module/bar on an
integer device pixel (section 0 below, run against every symbology), plus
each symbology's own content-specific geometry, hand-derived independently
of objects.py's implementation wherever the brief gives a concrete formula
to check against (not just "whatever the code happens to produce").
"""

from __future__ import annotations

import re

import barcode
import pytest
import qrcode
from PIL import Image

from labelmaker.render.document import RenderedLabel, RenderWarning, _svg_document
from labelmaker.render.objects import (
    CODE39_CHARSET,
    BarcodeResult,
    code39_object,
    code128_object,
    datamatrix_object,
    qr_object,
)
from labelmaker.render.rasterize import rasterize

_RECT_RE = re.compile(
    r'<rect x="(-?\d+(?:\.\d+)?)" y="(-?\d+(?:\.\d+)?)" '
    r'width="(-?\d+(?:\.\d+)?)" height="(-?\d+(?:\.\d+)?)"'
)


def _rasterize_result(result: BarcodeResult) -> Image.Image:
    label = RenderedLabel(
        svg=_svg_document(result.width_px, result.height_px, result.svg_group),
        width_px=result.width_px,
        height_px=result.height_px,
    )
    return rasterize(label)


def _ink(img: Image.Image, x: int, y: int) -> bool:
    """True if (x, y) is an "ink" (black) pixel in a mode "1" image --
    matches test_divided_blocks.py's own `_ink` convention."""
    assert img.mode == "1"
    return img.getpixel((x, y)) == 0


def _all_white(img: Image.Image, xs: range, ys: range) -> bool:
    return all(not _ink(img, x, y) for x in xs for y in ys)


# --- 0. Integer snapping: every group, every rect -- see objects.py's ------
# module docstring for why this is the core constraint of this whole task.

_SAMPLE_RESULTS: dict[str, BarcodeResult] = {
    "qr": qr_object("TEST", module_px=3, x=5, y=7),
    "code128": code128_object("ASSET-0042", x_dim_px=2, height_px=50, x=2, y=3),
    "code39": code39_object("ASSET-0042", x_dim_px=2, height_px=50),
    "datamatrix": datamatrix_object("T-01", module_px=4, x=1, y=1),
}


@pytest.mark.parametrize("name", sorted(_SAMPLE_RESULTS))
def test_every_rect_has_integer_coords_and_dims(name):
    result = _SAMPLE_RESULTS[name]
    matches = _RECT_RE.findall(result.svg_group)
    assert matches, f"{name}: no <rect> elements found"
    for x, y, width, height in matches:
        for value in (x, y, width, height):
            assert "." not in value, f"{name}: non-integer rect coordinate {value!r}"


@pytest.mark.parametrize("name", sorted(_SAMPLE_RESULTS))
def test_no_scale_transform_anywhere(name):
    assert "scale(" not in _SAMPLE_RESULTS[name].svg_group


@pytest.mark.parametrize("name", sorted(_SAMPLE_RESULTS))
def test_group_uses_crispedges_and_integer_translate(name):
    svg_group = _SAMPLE_RESULTS[name].svg_group
    assert 'shape-rendering="crispEdges"' in svg_group
    translate_match = re.search(r"translate\((-?\d+),(-?\d+)\)", svg_group)
    assert translate_match, f"{name}: no translate(...) found"


@pytest.mark.parametrize("name", sorted(_SAMPLE_RESULTS))
def test_only_black_fill_used(name):
    fills = set(re.findall(r'fill="([^"]*)"', _SAMPLE_RESULTS[name].svg_group))
    assert fills == {"black"}


# --- 1. QR --------------------------------------------------------------


def test_qr_lib_matrix_for_test_is_square_odd_at_least_21():
    # Hand-derived directly from the qrcode library itself (border=0, same
    # error correction qr_object uses), independent of objects.py.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data("TEST")
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    assert n == len(matrix[0])  # square
    assert n % 2 == 1  # odd
    assert n >= 21


def test_qr_width_is_matrix_plus_8_quiet_modules_times_module_px():
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data("TEST")
    qr.make(fit=True)
    n = len(qr.get_matrix())
    for module_px in (1, 2, 5):
        result = qr_object("TEST", module_px=module_px)
        assert result.width_px == (n + 8) * module_px
        assert result.height_px == result.width_px  # always square


def test_qr_quiet_zone_rows_and_cols_are_all_white():
    module_px = 2
    result = qr_object("TEST", module_px=module_px)
    img = _rasterize_result(result)
    quiet_px = 4 * module_px
    size = result.width_px
    # top band, bottom band, left band, right band.
    assert _all_white(img, range(size), range(quiet_px))
    assert _all_white(img, range(size), range(size - quiet_px, size))
    assert _all_white(img, range(quiet_px), range(size))
    assert _all_white(img, range(size - quiet_px, size), range(size))


def test_qr_finder_pattern_corner_present_at_expected_pixels():
    # Standard QR finder pattern (7x7 modules): a solid dark 7x7 ring border,
    # a white 5x5 ring just inside it, and a solid dark 3x3 center -- see
    # qrcode's own get_matrix() output for "TEST" (checked directly here,
    # independent of objects.py): module (0,0) dark, (1,1) white (inside the
    # ring), (3,3) dark (finder center), (6,6) dark (ring's far corner).
    module_px = 2
    result = qr_object("TEST", module_px=module_px)
    img = _rasterize_result(result)
    quiet_px = 4 * module_px

    def _module_ink(row: int, col: int) -> bool:
        x = quiet_px + col * module_px
        y = quiet_px + row * module_px
        return _ink(img, x, y)

    assert _module_ink(0, 0) is True
    assert _module_ink(1, 1) is False
    assert _module_ink(3, 3) is True
    assert _module_ink(6, 6) is True


def test_qr_module_px_1_warns_small_module():
    result = qr_object("TEST", module_px=1)
    codes = [w.code for w in result.warnings]
    assert "barcode_small_module" in codes
    warning = next(w for w in result.warnings if w.code == "barcode_small_module")
    assert isinstance(warning, RenderWarning)
    assert warning.severity == "warning"


def test_qr_module_px_2_has_no_small_module_warning():
    result = qr_object("TEST", module_px=2)
    assert "barcode_small_module" not in [w.code for w in result.warnings]


def test_qr_object_id_threaded_into_warnings():
    result = qr_object("TEST", module_px=1, object_id="my-qr")
    assert result.warnings[0].object_id == "my-qr"


def test_qr_large_code_warns():
    # A long data string forces a high QR version -- comfortably past
    # _MAX_HEAD_DOTS (128px) even at module_px=2.
    long_data = "A" * 400
    result = qr_object(long_data, module_px=2)
    assert "barcode_large" in [w.code for w in result.warnings]


@pytest.mark.parametrize("module_px", [1, 2, 3, 5])
def test_qr_rect_geometry_is_exact_multiples_of_module_px(module_px):
    # "module boundaries exact multiples of module_px" (task brief) --
    # every rect's x/y/width/height, not just integer (section 0 already
    # covers that), but an exact multiple of module_px specifically: a
    # module-grid cell can never start or end mid-module.
    result = qr_object("TEST", module_px=module_px)
    for x, y, width, height in _RECT_RE.findall(result.svg_group):
        for value in (x, y, width, height):
            assert int(value) % module_px == 0


# --- 2. Code128 -----------------------------------------------------------


def test_code128_bar_structure_consumed_width_matches_hand_derivation():
    # Independent of objects.py: build the SAME module string via
    # python-barcode directly (never mocked) and hand-derive total width.
    built = barcode.get_barcode_class("code128")("ASSET-0042").build()[0]
    total_modules = len(built)  # each char is exactly 1 module
    for x_dim in (1, 2, 4):
        result = code128_object("ASSET-0042", x_dim_px=x_dim, height_px=40)
        assert result.width_px == total_modules * x_dim + 20 * x_dim
        assert result.height_px == 40


def test_code128_x_dim_1_warns_small_module():
    result = code128_object("ASSET-0042", x_dim_px=1, height_px=40)
    assert "barcode_small_module" in [w.code for w in result.warnings]


def test_code128_x_dim_2_has_no_small_module_warning():
    result = code128_object("ASSET-0042", x_dim_px=2, height_px=40)
    assert result.warnings == []


def test_code128_rects_confined_to_declared_height():
    result = code128_object("ASSET-0042", x_dim_px=3, height_px=17)
    heights = {int(h) for h in re.findall(r'height="(\d+)"', result.svg_group)}
    assert heights == {17}


@pytest.mark.parametrize("x_dim", [1, 2, 3, 5])
def test_code128_bar_geometry_is_exact_multiples_of_x_dim(x_dim):
    result = code128_object("ASSET-0042", x_dim_px=x_dim, height_px=40)
    for x, _y, width, _height in _RECT_RE.findall(result.svg_group):
        assert int(x) % x_dim == 0
        assert int(width) % x_dim == 0


# --- 3. Code39 --------------------------------------------------------------


def test_code39_charset_matches_python_barcodes_own_reference_set():
    # Cross-check objects.py's duplicated CODE39_CHARSET constant (see its
    # own docstring for why it's duplicated rather than imported) against
    # the library's own reference tuple.
    from barcode.charsets import code39 as _code39_charset_module

    assert CODE39_CHARSET == set(_code39_charset_module.REF)


def test_code39_invalid_chars_raises_value_error_listing_them():
    with pytest.raises(ValueError) as exc_info:
        code39_object("lower!", x_dim_px=2, height_px=40)
    message = str(exc_info.value)
    for bad_char in "lower!":
        assert bad_char in message


def test_code39_full_charset_string_renders():
    full_charset_data = "".join(sorted(CODE39_CHARSET))
    result = code39_object(full_charset_data, x_dim_px=2, height_px=40)
    assert result.width_px > 0
    assert result.height_px == 40


def test_code39_bar_structure_width_matches_hand_derivation():
    built = barcode.get_barcode_class("code39")("ASSET-0042", add_checksum=False).build()[0]
    total_modules = len(built)
    result = code39_object("ASSET-0042", x_dim_px=2, height_px=40)
    assert result.width_px == total_modules * 2 + 20 * 2


def test_code39_x_dim_1_warns_small_module():
    result = code39_object("ASSET-0042", x_dim_px=1, height_px=40)
    assert "barcode_small_module" in [w.code for w in result.warnings]


@pytest.mark.parametrize("x_dim", [1, 2, 3, 5])
def test_code39_bar_geometry_is_exact_multiples_of_x_dim(x_dim):
    result = code39_object("ASSET-0042", x_dim_px=x_dim, height_px=40)
    for x, _y, width, _height in _RECT_RE.findall(result.svg_group):
        assert int(x) % x_dim == 0
        assert int(width) % x_dim == 0


# --- 4. DataMatrix ----------------------------------------------------------


def test_datamatrix_lib_matrix_is_square():
    from ppf.datamatrix import DataMatrix

    dm = DataMatrix("T-01")
    matrix = dm.matrix
    assert len(matrix) == len(matrix[0])


def test_datamatrix_width_is_matrix_plus_4_quiet_modules_times_module_px():
    from ppf.datamatrix import DataMatrix

    n = len(DataMatrix("T-01").matrix)
    for module_px in (1, 3, 5):
        result = datamatrix_object("T-01", module_px=module_px)
        assert result.width_px == (n + 4) * module_px  # 2 quiet modules/side
        assert result.height_px == result.width_px


def test_datamatrix_quiet_zone_is_2_modules_white_in_bitmap():
    module_px = 4
    result = datamatrix_object("T-01", module_px=module_px)
    img = _rasterize_result(result)
    quiet_px = 2 * module_px
    size = result.width_px
    assert _all_white(img, range(size), range(quiet_px))
    assert _all_white(img, range(size), range(size - quiet_px, size))
    assert _all_white(img, range(quiet_px), range(size))
    assert _all_white(img, range(size - quiet_px, size), range(size))


def test_datamatrix_module_px_1_warns_small_module():
    result = datamatrix_object("T-01", module_px=1)
    assert "barcode_small_module" in [w.code for w in result.warnings]


def test_datamatrix_module_px_2_has_no_small_module_warning():
    result = datamatrix_object("T-01", module_px=2)
    assert "barcode_small_module" not in [w.code for w in result.warnings]


@pytest.mark.parametrize("module_px", [1, 2, 3, 5])
def test_datamatrix_rect_geometry_is_exact_multiples_of_module_px(module_px):
    # "module boundaries exact multiples of module_px" (task brief) -- same
    # convention as test_qr_rect_geometry_is_exact_multiples_of_module_px.
    result = datamatrix_object("T-01", module_px=module_px)
    for x, y, width, height in _RECT_RE.findall(result.svg_group):
        for value in (x, y, width, height):
            assert int(value) % module_px == 0


# --- 5. Scannability regression guard: decode a rendered code with a real -
# reader (zxing-cpp, a DEV-only dependency -- see pyproject.toml's
# [dependency-groups] dev). Everything above proves the SVG geometry is
# pixel-snapped/well-formed; it does NOT prove a real scanner could read the
# result -- that's what this section guards, permanently, against any
# future change to objects.py's rect emission. `pytest.importorskip`
# per-test (not module-level) so only THESE two tests skip in an
# environment without zxing-cpp's wheel installed (verified available for
# linux x86_64/aarch64, macOS, and Windows, cp310-cp314, at the time this
# dependency was added) -- every other test in this file still runs.


def test_qr_object_decodes_back_to_its_data_at_device_resolution():
    zxingcpp = pytest.importorskip("zxingcpp")
    result = qr_object("https://example.com/a/000-001", module_px=2)
    img = _rasterize_result(result)
    barcode_read = zxingcpp.read_barcode(img.convert("L"))
    assert barcode_read is not None, "zxing-cpp could not decode the rendered QR at all"
    assert barcode_read.text == "https://example.com/a/000-001"
    assert barcode_read.format == zxingcpp.BarcodeFormat.QRCode


def test_code128_object_decodes_back_to_its_data_at_device_resolution():
    zxingcpp = pytest.importorskip("zxingcpp")
    result = code128_object("ASSET-0042", x_dim_px=2, height_px=40)
    img = _rasterize_result(result)
    barcode_read = zxingcpp.read_barcode(img.convert("L"))
    assert barcode_read is not None, "zxing-cpp could not decode the rendered Code128 at all"
    assert barcode_read.text == "ASSET-0042"
    assert barcode_read.format == zxingcpp.BarcodeFormat.Code128
