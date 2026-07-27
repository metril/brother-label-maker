"""Tests for labelmaker.render.types.text_label: the "text" label type."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from labelmaker.driver.geometry import MIN_LABEL_MM, mm_to_dots
from labelmaker.render.document import Tape
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.text_label import TextLabelParams, TextLabelRenderer

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"
GOLDEN_SCALE = 4

# --- 1. Registry integration ---


def test_text_type_is_registered():
    types_by_name = {t.type: t for t in list_types()}
    assert "text" in types_by_name
    assert "lines" in types_by_name["text"].params_schema.get("properties", {})


def test_get_renderer_text_returns_text_label_renderer():
    assert isinstance(get_renderer("text"), TextLabelRenderer)


# --- 2. Params validation ---


def test_params_defaults():
    p = TextLabelParams(lines=["HELLO"])
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.font_size_px is None
    assert p.h_align == "center"
    assert p.length_mm is None
    assert p.padding_mm == 2.0


def test_params_zero_lines_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=[])


def test_params_five_lines_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["A", "B", "C", "D", "E"])


def test_params_four_lines_accepted():
    TextLabelParams(lines=["A", "B", "C", "D"])


def test_params_line_over_200_chars_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["X" * 201])


def test_params_line_exactly_200_chars_accepted():
    TextLabelParams(lines=["X" * 200])


def test_params_all_blank_lines_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["", "   ", ""])


def test_params_one_non_empty_line_among_blanks_accepted():
    TextLabelParams(lines=["", "HELLO", ""])


def test_params_unknown_font_family_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["HELLO"], font_family="Comic Sans")


@pytest.mark.parametrize("family", ["Inter", "Roboto Condensed", "JetBrains Mono", "DejaVu Sans"])
def test_params_all_bundled_families_accepted(family):
    TextLabelParams(lines=["HELLO"], font_family=family)


def test_params_font_size_px_below_min_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["HELLO"], font_size_px=5)


def test_params_font_size_px_above_max_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["HELLO"], font_size_px=129)


def test_params_font_size_px_boundaries_accepted():
    TextLabelParams(lines=["HELLO"], font_size_px=6)
    TextLabelParams(lines=["HELLO"], font_size_px=128)


def test_params_invalid_h_align_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["HELLO"], h_align="justify")


def test_params_negative_padding_mm_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["HELLO"], padding_mm=-1.0)


def test_params_zero_padding_mm_accepted():
    TextLabelParams(lines=["HELLO"], padding_mm=0.0)


# --- 3. Geometry: height_px == print_dots; auto length grows; fixed length exact ---


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


def test_height_px_equals_print_dots_24mm():
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), _tape(24))
    assert label.height_px == 128


def test_height_px_equals_print_dots_12mm():
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), _tape(12))
    assert label.height_px == 70


def test_auto_length_grows_with_text_length():
    tape = _tape(24)
    short = TextLabelRenderer().render(
        TextLabelParams(lines=["A"], font_size_px=20), tape
    )
    long = TextLabelRenderer().render(
        TextLabelParams(lines=["A LONG STRING OF LABEL TEXT"], font_size_px=20), tape
    )
    assert long.width_px > short.width_px


def test_fixed_length_honored_exactly():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], length_mm=40.0), tape
    )
    assert label.width_px == mm_to_dots(40.0)


def test_fixed_length_clamped_to_min_label_mm():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], length_mm=0.1), tape
    )
    assert label.width_px == mm_to_dots(MIN_LABEL_MM)


def test_fixed_length_clamped_to_tape_max_length_mm():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], length_mm=99999.0), tape
    )
    assert label.width_px == mm_to_dots(tape.max_length_mm)


def test_auto_length_at_least_min_label_mm():
    tape = _tape(24)
    label = TextLabelRenderer().render(TextLabelParams(lines=["I"], font_size_px=6), tape)
    assert label.width_px >= mm_to_dots(MIN_LABEL_MM)


# --- 4. Explicit font_size_px is clamped to fit the physical print area ---


def test_explicit_font_size_clamped_to_print_area_height():
    tiny_tape = _tape(3.5)  # print_dots == 24
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["A"], font_size_px=128), tiny_tape
    )
    assert 'font-size="128"' not in label.svg
    assert label.height_px == 24


# --- 5. Warnings ---


def test_cramped_auto_size_triggers_warning():
    tiny_tape = _tape(3.5)  # print_dots == 24
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["A", "B", "C", "D"]), tiny_tape
    )
    assert any("cramped" in w or "minimum" in w for w in label.warnings)


def test_normal_case_has_no_warnings():
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), _tape(24))
    assert label.warnings == []


def test_fixed_length_truncation_triggers_warning_and_clips():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["PATCH-PANEL-PORT-01"], font_size_px=20, length_mm=5.0),
        tape,
    )
    assert any("truncat" in w for w in label.warnings)
    assert "clipPath" in label.svg


def test_fixed_length_no_truncation_no_clip():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], font_size_px=10, length_mm=40.0),
        tape,
    )
    assert label.warnings == []
    assert "clipPath" not in label.svg


# --- 6. h_align affects text-anchor ---


@pytest.mark.parametrize(
    "h_align,anchor", [("left", "start"), ("center", "middle"), ("right", "end")]
)
def test_h_align_maps_to_text_anchor(h_align, anchor):
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], h_align=h_align), _tape(24)
    )
    assert f'text-anchor="{anchor}"' in label.svg


# --- 7. Determinism (module-level; golden-PNG-level determinism lives with the goldens) ---


def test_render_is_deterministic_svg():
    tape = _tape(24)
    params = TextLabelParams(lines=["HELLO"])
    svg1 = TextLabelRenderer().render(params, tape).svg
    svg2 = TextLabelRenderer().render(params, tape).svg
    assert svg1 == svg2


# --- 8. Golden PNGs: byte-locked against committed files ---
#
# Generated by scripts/render dev runs, visually inspected (see
# task-1.2-report.md), then committed. These tests pin the exact bytes --
# any change to fonts/, rasterize.py, document.py's SVG output, or resvg-py's
# version will break them, which is the point.


def _render_preview_png(params: TextLabelParams, tape) -> bytes:
    label = TextLabelRenderer().render(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


def test_golden_hello_inter_auto_center_24mm():
    png = _render_preview_png(TextLabelParams(lines=["HELLO"]), _tape(24))
    golden = (GOLDEN_DIR / "text_hello_inter_24mm.png").read_bytes()
    assert png == golden


def test_golden_two_line_roboto_condensed_bold_12mm():
    png = _render_preview_png(
        TextLabelParams(
            lines=["PATCH PANEL", "PORT 1-24"], font_family="Roboto Condensed", bold=True
        ),
        _tape(12),
    )
    golden = (GOLDEN_DIR / "text_two_line_robotocondensed_bold_12mm.png").read_bytes()
    assert png == golden


def test_golden_port01_jetbrains_mono_fixed_40mm_left_24mm():
    png = _render_preview_png(
        TextLabelParams(
            lines=["PORT-01"], font_family="JetBrains Mono", length_mm=40.0, h_align="left"
        ),
        _tape(24),
    )
    golden = (GOLDEN_DIR / "text_port01_jetbrainsmono_fixed40mm_left_24mm.png").read_bytes()
    assert png == golden


def test_golden_hello_render_twice_is_byte_identical():
    png1 = _render_preview_png(TextLabelParams(lines=["HELLO"]), _tape(24))
    png2 = _render_preview_png(TextLabelParams(lines=["HELLO"]), _tape(24))
    assert png1 == png2
