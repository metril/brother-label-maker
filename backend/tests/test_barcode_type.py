"""Tests for labelmaker.render.types.barcode_label: the "barcode" label type
(task 2.5) -- QR/Code128/Code39/DataMatrix, plus an optional caption, laid
out and sized on top of render/objects.py's four `*_object()` functions.

Sizing numbers below are hand-derived from the formula barcode_label.py's
own module docstring documents ("-- Sizing --" section), independent of its
implementation:

    module_px = available_height_px // total_modules   (2D, size_mode=auto)
    available_height_px = tape.print_dots - caption_block_px (if captioned)
    caption_font_px = max(8, round(0.20 * tape.print_dots))
    caption_block_px = ceil(caption_font_px * 1.15)

For "TEST" on a 24mm tape (tape.print_dots == 128): the qrcode library
itself (checked directly, not assumed) produces a 21x21 matrix for "TEST" at
ERROR_CORRECT_M/border=0, so total_modules == 21 + 8 (quiet zone) == 29 --
matching the task brief's own worked example (module_px = 128 // 29 == 4,
caption off).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
import qrcode
from golden_fixtures import BARCODE_TYPE_FIXTURES, GOLDEN_SCALE
from pydantic import ValidationError

from labelmaker.render.document import Tape
from labelmaker.render.objects import CODE39_CHARSET
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.barcode_label import BarcodeLabelParams, BarcodeLabelRenderer

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


def _qr_total_modules(data: str) -> int:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return len(qr.get_matrix()) + 8  # +4-module quiet zone each side


def _caption_block_px(print_dots: int) -> int:
    caption_font_px = max(8, round(0.20 * print_dots))
    return math.ceil(caption_font_px * 1.15)


# --- 0. Registration: "barcode", category "general" ------------------------


def test_barcode_registered_under_general_category():
    by_type = {t.type: t for t in list_types()}
    assert "barcode" in by_type
    assert by_type["barcode"].category == "general"
    assert by_type["barcode"].min_tape_mm is None


def test_get_renderer_returns_barcode_label_renderer():
    assert isinstance(get_renderer("barcode"), BarcodeLabelRenderer)


# --- 1. Params validation ----------------------------------------------


def test_barcode_label_defaults():
    p = BarcodeLabelParams(data="TEST")
    assert p.symbology == "qr"
    assert p.caption == "below"
    assert p.size_mode == "auto"
    assert p.module_px == 2
    assert p.length_mm is None
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.padding_mm == 2.0


def test_data_empty_string_rejected():
    with pytest.raises(ValidationError):
        BarcodeLabelParams(data="")


def test_data_over_500_chars_rejected():
    with pytest.raises(ValidationError):
        BarcodeLabelParams(data="A" * 501)


def test_data_exactly_500_chars_accepted():
    BarcodeLabelParams(data="A" * 500)


@pytest.mark.parametrize("module_px", [1, 20])
def test_module_px_boundaries_accepted(module_px):
    BarcodeLabelParams(data="TEST", module_px=module_px)


@pytest.mark.parametrize("module_px", [0, 21])
def test_module_px_out_of_range_rejected(module_px):
    with pytest.raises(ValidationError):
        BarcodeLabelParams(data="TEST", module_px=module_px)


def test_unknown_font_family_rejected():
    with pytest.raises(ValidationError):
        BarcodeLabelParams(data="TEST", font_family="Comic Sans")


def test_unknown_symbology_rejected():
    with pytest.raises(ValidationError):
        BarcodeLabelParams(data="TEST", symbology="pdf417")


# --- 2. code39 charset validation (model_validator, only when selected) ----


def test_code39_invalid_chars_rejected_with_message_listing_them():
    with pytest.raises(ValidationError, match=r"\['!', 'a'\]"):
        BarcodeLabelParams(symbology="code39", data="a!")


def test_code39_valid_charset_accepted():
    BarcodeLabelParams(symbology="code39", data="ASSET-01 $/+%.")


def test_code39_charset_check_skipped_for_other_symbologies():
    # Lowercase/invalid-for-code39 characters are fine for every OTHER
    # symbology -- the charset check is gated on symbology=="code39".
    BarcodeLabelParams(symbology="qr", data="lower case! ok")
    BarcodeLabelParams(symbology="code128", data="lower case! ok")
    BarcodeLabelParams(symbology="datamatrix", data="lower case! ok")


def test_code39_charset_matches_objects_module_constant():
    assert CODE39_CHARSET  # sanity: non-empty, imported successfully


# --- 3. Auto sizing: 2D (QR/DataMatrix) -- the point of this task ----------


def test_qr_auto_sizing_no_caption_hand_computed_24mm():
    # Task brief's own worked example: QR "TEST" -> v1, 21 modules + 8 quiet
    # = 29 total; 24mm tape print_dots=128 -> module_px = 128 // 29 = 4.
    total_modules = _qr_total_modules("TEST")
    assert total_modules == 29
    tape = _tape(24)
    params = BarcodeLabelParams(symbology="qr", data="TEST", caption="none")
    label = BarcodeLabelRenderer().render(params, tape)
    expected_module_px = tape.print_dots // total_modules
    assert expected_module_px == 4
    expected_code_width_px = total_modules * expected_module_px
    # width_px == code width + 2*padding_px (padding_mm=2.0 default).
    from labelmaker.driver.geometry import mm_to_dots

    padding_px = mm_to_dots(2.0)
    assert label.width_px == expected_code_width_px + 2 * padding_px
    assert label.height_px == 128


def test_qr_auto_sizing_caption_reduces_module_px_24mm():
    # Same data/tape as above, caption="below" (default) this time: the
    # caption's reserved band shrinks available_height_px, which shrinks
    # the largest module_px that still fits -- hand-computed via
    # barcode_label.py's own documented formula (see this file's module
    # docstring), independent of re-deriving it from source.
    total_modules = _qr_total_modules("TEST")
    tape = _tape(24)
    caption_block_px = _caption_block_px(tape.print_dots)
    available_height_px = tape.print_dots - caption_block_px
    expected_module_px = available_height_px // total_modules

    params_no_caption = BarcodeLabelParams(symbology="qr", data="TEST", caption="none")
    params_with_caption = BarcodeLabelParams(symbology="qr", data="TEST", caption="below")
    label_no_caption = BarcodeLabelRenderer().render(params_no_caption, tape)
    label_with_caption = BarcodeLabelRenderer().render(params_with_caption, tape)

    module_px_no_caption = (label_no_caption.width_px - 2 * _padding_px()) // total_modules
    module_px_with_caption = (
        label_with_caption.width_px - 2 * _padding_px()
    ) // total_modules

    assert expected_module_px == 3
    assert module_px_with_caption == expected_module_px
    assert module_px_with_caption < module_px_no_caption == 4


def _padding_px() -> int:
    from labelmaker.driver.geometry import mm_to_dots

    return mm_to_dots(2.0)


def test_datamatrix_auto_sizing_no_caption_hand_computed_12mm():
    # Golden fixture (c)'s own numbers: DataMatrix "T-01" -> 10x10 matrix
    # (checked directly against the library), +4 quiet modules = 14 total;
    # 12mm tape print_dots=70 -> module_px = 70 // 14 = 5 exactly.
    from ppf.datamatrix import DataMatrix

    total_modules = len(DataMatrix("T-01").matrix) + 4
    assert total_modules == 14
    tape = _tape(12)
    params = BarcodeLabelParams(symbology="datamatrix", data="T-01", caption="none")
    label = BarcodeLabelRenderer().render(params, tape)
    expected_module_px = tape.print_dots // total_modules
    assert expected_module_px == 5
    expected_code_width_px = total_modules * expected_module_px
    assert label.width_px == expected_code_width_px + 2 * _padding_px()


def test_qr_size_mode_module_uses_module_px_directly_ignoring_caption():
    tape = _tape(24)
    params = BarcodeLabelParams(
        symbology="qr", data="TEST", size_mode="module", module_px=3, caption="below"
    )
    label = BarcodeLabelRenderer().render(params, tape)
    total_modules = _qr_total_modules("TEST")
    expected_code_width_px = total_modules * 3
    assert label.width_px == expected_code_width_px + 2 * _padding_px()


# --- 4. 1D (Code128/Code39): x_dim from module_px, height stretches --------


def test_code128_auto_sizing_stretches_height_to_available_budget():
    tape = _tape(24)
    caption_block_px = _caption_block_px(tape.print_dots)
    expected_barcode_height_px = tape.print_dots - caption_block_px

    params = BarcodeLabelParams(symbology="code128", data="ASSET-0042")
    label = BarcodeLabelRenderer().render(params, tape)
    # Every bar <rect> shares the SAME height (the whole point of "1D codes
    # stretch height") -- extract only the black (bar) rects, so the white
    # background rect's own height="128" (the whole label, from
    # document.py's _svg_document) doesn't get swept in too.
    rect_heights = {
        int(h)
        for h in re.findall(
            r'<rect x="\d+" y="\d+" width="\d+" height="(\d+)" fill="black"', label.svg
        )
    }
    assert rect_heights == {expected_barcode_height_px}


def test_code128_x_dim_always_module_px_regardless_of_size_mode():
    tape = _tape(24)
    for size_mode in ("auto", "module"):
        params = BarcodeLabelParams(
            symbology="code128", data="A", size_mode=size_mode, module_px=3, caption="none"
        )
        label = BarcodeLabelRenderer().render(params, tape)
        widths = sorted(
            {
                int(w)
                for w in re.findall(
                    r'<rect x="\d+" y="\d+" width="(\d+)" height="\d+" fill="black"', label.svg
                )
            }
        )
        # Every bar width is a multiple of x_dim_px (3) -- exact multiples
        # is what "module boundaries exact multiples of module_px" means.
        assert widths
        assert all(w % 3 == 0 for w in widths)


# --- 5. Caption sizing/placement --------------------------------------------


def test_caption_font_px_is_20_percent_of_print_height_min_8():
    # 24mm tape: round(0.2*128) = 26 (> 8, so the floor never engages).
    tape = _tape(24)
    params = BarcodeLabelParams(symbology="qr", data="TEST", caption="below")
    label = BarcodeLabelRenderer().render(params, tape)
    assert 'font-size="26"' in label.svg


def test_caption_min_8px_floor_engages_on_a_narrow_tape():
    # 6mm tape: print_dots=32 -> round(0.2*32)=6, floored up to 8. DataMatrix
    # (not QR) here -- its 10x10 minimum matrix (+4 quiet = 14 total modules)
    # still leaves room for the caption at this tape height (unlike QR's
    # larger 29-module minimum, which would trip the caption_omitted drop
    # instead -- see test_caption_omitted_warning_when_... below), so this
    # isolates just the min-8px floor without also exercising the drop path.
    tape = _tape(6)
    assert round(0.20 * tape.print_dots) < 8
    params = BarcodeLabelParams(symbology="datamatrix", data="1", caption="below")
    label = BarcodeLabelRenderer().render(params, tape)
    assert 'font-size="8"' in label.svg


def test_caption_text_is_the_data_string():
    params = BarcodeLabelParams(symbology="code128", data="ASSET-0042", caption="below")
    label = BarcodeLabelRenderer().render(params, _tape(24))
    assert "ASSET-0042" in label.svg


def test_caption_none_omits_any_text_element():
    params = BarcodeLabelParams(symbology="code128", data="ASSET-0042", caption="none")
    label = BarcodeLabelRenderer().render(params, _tape(24))
    assert "<text" not in label.svg


def test_caption_wider_than_label_auto_length_shrinks_then_drops():
    # A long URL caption under a compact QR code -- see golden fixture (a).
    # Auto-length mode: width is sized to the CODE, so an over-wide caption
    # is the flexible element -- it's tried at shrinking sizes down to the
    # 8px floor (still ~1.6x too wide even there, hand-checked against
    # fonts.measure_text independently below) and, failing that, dropped
    # entirely -- never silently rendered overflowing.
    from labelmaker.render.fonts import measure_text

    url = "https://example.com/a/000-001"
    # Independent check that shrinking genuinely can't rescue this case: the
    # QR itself (v3, 29 modules + 8 quiet = 37 total, hand-derived earlier
    # in this file) at auto module_px=2 (98px available height // 37) is
    # only 74px wide -- narrower than the caption's own text even at the
    # 8px floor (120px, measured directly, independent of barcode_label.py).
    total_modules = _qr_total_modules(url)
    assert total_modules == 37
    code_width_px = total_modules * 2  # module_px = 98 // 37 = 2
    assert measure_text(url, "Inter", 8, False)[0] > code_width_px

    params = BarcodeLabelParams(symbology="qr", data=url, caption="below")
    label = BarcodeLabelRenderer().render(params, _tape(24))
    assert "caption_omitted" in [w.code for w in label.warnings]
    assert "caption_truncated" not in [w.code for w in label.warnings]
    assert "<text" not in label.svg  # dropped, not rendered overflowing


def test_caption_wider_than_fixed_length_warns_truncated_not_dropped():
    # Fixed length_mm: width IS the caller's own pinned hard constraint (the
    # same role tape height plays for size_mode) -- an over-wide caption is
    # clipped-and-warned instead, exactly text_label.py's fixed-length
    # text_truncated behavior, never shrunk or dropped.
    url = "https://example.com/a/000-001"
    params = BarcodeLabelParams(
        symbology="qr", data=url, caption="below", length_mm=20.0
    )
    label = BarcodeLabelRenderer().render(params, _tape(24))
    assert "caption_truncated" in [w.code for w in label.warnings]
    assert "caption_omitted" not in [w.code for w in label.warnings]
    assert "<text" in label.svg  # still rendered (just visually cut off)


def test_short_caption_that_fits_has_no_truncation_warning():
    params = BarcodeLabelParams(symbology="datamatrix", data="T-01", caption="below")
    label = BarcodeLabelRenderer().render(params, _tape(24))
    assert "caption_truncated" not in [w.code for w in label.warnings]


# --- 6. Caption dropped when it doesn't leave room (auto mode only) --------


def test_caption_omitted_when_tape_too_short_for_code_plus_caption():
    # A big QR (long data -> many modules) on a narrow tape: with the
    # caption's ~20%-of-height band reserved, module_px would floor to 0 --
    # auto mode drops the caption instead of failing.
    tape = _tape(6)  # print_dots == 32
    long_data = "A" * 60
    total_modules = _qr_total_modules(long_data)
    assert tape.print_dots < total_modules  # can't even fit module_px=1
    params = BarcodeLabelParams(symbology="qr", data=long_data, caption="below")
    with pytest.raises(ValueError):
        # Even WITHOUT the caption this data doesn't fit a 6mm tape -- both
        # branches (drop caption, then still fail) are exercised together;
        # the narrower case below isolates the "drop only" branch.
        BarcodeLabelRenderer().render(params, tape)


def test_caption_omitted_warning_when_caption_alone_blocks_a_fitting_code():
    # Pick data/tape where the code WOULD fit at module_px=1 without a
    # caption, but the caption's reserved band alone pushes
    # available_height_px below total_modules.
    tape = _tape(9)  # print_dots == 50
    data = "T" * 70  # data-dependent QR version -- probe below (v4 -> 41 total modules)
    total_modules = _qr_total_modules(data)
    caption_block_px = _caption_block_px(tape.print_dots)
    assert tape.print_dots - caption_block_px < total_modules <= tape.print_dots
    params = BarcodeLabelParams(symbology="qr", data=data, caption="below")
    label = BarcodeLabelRenderer().render(params, tape)
    assert "caption_omitted" in [w.code for w in label.warnings]
    assert "<text" not in label.svg  # caption really was dropped, not just warned about


def test_size_mode_module_never_drops_caption_but_raises_when_impossible():
    # size_mode="module" is fully manual -- caption is NEVER auto-dropped,
    # even in the exact combination that triggers the auto-mode drop above
    # (same tape/data/available_height_px as
    # test_caption_omitted_warning_when_caption_alone_blocks_a_fitting_code:
    # 38px available, needs 41). Since the caller pinned module_px=1
    # (already the smallest legal value) AND the caption, and the two
    # together are impossible to satisfy, this raises rather than silently
    # dropping something the caller explicitly asked for.
    tape = _tape(9)
    data = "T" * 70
    params = BarcodeLabelParams(
        symbology="qr", data=data, caption="below", size_mode="module", module_px=1
    )
    with pytest.raises(ValueError, match="even at module_px=1"):
        BarcodeLabelRenderer().render(params, tape)


def test_size_mode_module_clamps_module_px_never_drops_caption_never_overflows():
    # The reviewer's own regression case: module_px=8 requested for QR
    # "TEST" (29 total modules) on a 24mm tape with the default caption --
    # 29*8=232px doesn't fit the 98px band left after the caption. Before
    # the fix, this silently centered a 232px-tall code in a 98px band
    # (code_y negative, top/bottom sliced off canvas -- undecodable even
    # though only a warning fired). Now: module_px is CLAMPED down to
    # whatever fits (98 // 29 == 3), a module_clamped warning fires, the
    # caption is NOT dropped, and the code's own vertical placement is
    # non-negative (i.e. actually fits its band, nothing sliced).
    tape = _tape(24)
    total_modules = _qr_total_modules("TEST")
    assert total_modules == 29
    caption_block_px = _caption_block_px(tape.print_dots)
    available_height_px = tape.print_dots - caption_block_px
    expected_clamped_module_px = available_height_px // total_modules
    assert expected_clamped_module_px == 3
    assert expected_clamped_module_px < 8  # confirms the request really was too big

    params = BarcodeLabelParams(
        symbology="qr", data="TEST", caption="below", size_mode="module", module_px=8
    )
    label = BarcodeLabelRenderer().render(params, tape)
    assert "module_clamped" in [w.code for w in label.warnings]
    assert "caption_omitted" not in [w.code for w in label.warnings]
    assert "<text" in label.svg

    expected_code_height_px = total_modules * expected_clamped_module_px
    translate_match = re.search(r'<g transform="translate\((-?\d+),(-?\d+)\)">', label.svg)
    assert translate_match
    code_y = int(translate_match.group(2))
    # Non-negative AND fully within the available band -- neither edge sliced.
    assert code_y >= 0
    assert code_y + expected_code_height_px <= available_height_px


# --- 7. Fixed length_mm: center, 422 if the code doesn't fit ---------------


def test_fixed_length_mm_too_small_raises_value_error():
    params = BarcodeLabelParams(symbology="qr", data="TEST", caption="none", length_mm=5.0)
    with pytest.raises(ValueError, match="does not fit"):
        BarcodeLabelRenderer().render(params, _tape(24))


def test_fixed_length_mm_that_fits_centers_the_code():
    tape = _tape(24)
    params = BarcodeLabelParams(
        symbology="datamatrix", data="T-01", caption="none", length_mm=40.0
    )
    label = BarcodeLabelRenderer().render(params, tape)
    from labelmaker.driver.geometry import mm_to_dots

    assert label.width_px == mm_to_dots(40.0)
    # The code's <g translate(x,...)> x should center it: extract it and
    # confirm it's neither 0 nor flush against the right edge.
    translate_match = re.search(r'<g transform="translate\((\d+),(\d+)\)">', label.svg)
    assert translate_match
    code_x = int(translate_match.group(1))
    assert 0 < code_x < label.width_px


# --- 8. Warnings from objects.py bubble up ----------------------------------


def test_small_module_warning_bubbles_up_from_objects():
    params = BarcodeLabelParams(
        symbology="qr", data="TEST", caption="none", size_mode="module", module_px=1
    )
    label = BarcodeLabelRenderer().render(params, _tape(24))
    assert "barcode_small_module" in [w.code for w in label.warnings]


# --- 9. Schema fidelity: every field carries a description -----------------


def test_every_field_carries_a_description():
    props = BarcodeLabelParams.model_json_schema()["properties"]
    for field_name, schema in props.items():
        assert schema.get("description"), f"BarcodeLabelParams.{field_name} has no description"


def test_module_px_bounds_visible_in_schema():
    props = BarcodeLabelParams.model_json_schema()["properties"]
    assert props["module_px"]["minimum"] == 1
    assert props["module_px"]["maximum"] == 20


def test_symbology_enum_visible_in_schema():
    props = BarcodeLabelParams.model_json_schema()["properties"]
    assert set(props["symbology"]["enum"]) == {"qr", "code128", "code39", "datamatrix"}


# --- 10. Golden PNGs: byte-locked against committed files ------------------


def _render_preview_png(params: BarcodeLabelParams, tape) -> bytes:
    label = BarcodeLabelRenderer().render(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", BARCODE_TYPE_FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    png = _render_preview_png(fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden
