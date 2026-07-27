"""Tests for labelmaker.render.types.text_label: the "text" label type."""

from pathlib import Path

import pytest
from golden_fixtures import FIXTURES, GOLDEN_SCALE
from PIL import ImageFont
from pydantic import ValidationError

from labelmaker.driver.geometry import MIN_LABEL_MM, mm_to_dots
from labelmaker.render.document import RenderedLabel, Tape
from labelmaker.render.fonts import extent_ratio, font_path
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.text_label import TextLabelParams, TextLabelRenderer

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"

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


# --- 5. Warnings (B3: structured RenderWarning objects, not bare strings) ---


def test_cramped_auto_size_triggers_warning():
    tiny_tape = _tape(3.5)  # print_dots == 24
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["A", "B", "C", "D"]), tiny_tape
    )
    assert any(w.code == "text_cramped" for w in label.warnings)
    assert all(w.severity == "warning" for w in label.warnings)


def test_normal_case_has_no_warnings():
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), _tape(24))
    assert label.warnings == []


def test_fixed_length_truncation_triggers_warning_and_clips():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["PATCH-PANEL-PORT-01"], font_size_px=20, length_mm=5.0),
        tape,
    )
    assert any(w.code == "text_truncated" for w in label.warnings)
    assert "clipPath" in label.svg


def test_fixed_length_no_truncation_no_clip():
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], font_size_px=10, length_mm=40.0),
        tape,
    )
    assert label.warnings == []
    assert "clipPath" not in label.svg


def test_explicit_font_size_reduced_by_height_fit_triggers_font_clamped_warning():
    tiny_tape = _tape(3.5)  # print_dots == 24: 128px explicitly asked for cannot fit
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["A"], font_size_px=128), tiny_tape
    )
    assert any(w.code == "font_clamped" for w in label.warnings)


def test_explicit_font_size_that_already_fits_has_no_font_clamped_warning():
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], font_size_px=20), _tape(24)
    )
    assert label.warnings == []


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
# Fixture definitions live in golden_fixtures.py (shared with
# scripts/regen_goldens.py, which is how these PNGs are (re)generated --
# visually inspect any new/changed golden before committing it). These
# tests pin the exact bytes -- any change to fonts/, rasterize.py,
# document.py's SVG output, or resvg-py's version will break them, which is
# the point.


def _render_preview_png(params: TextLabelParams, tape) -> bytes:
    label = TextLabelRenderer().render(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    png = _render_preview_png(fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden


def test_golden_hello_render_twice_is_byte_identical():
    png1 = _render_preview_png(TextLabelParams(lines=["HELLO"]), _tape(24))
    png2 = _render_preview_png(TextLabelParams(lines=["HELLO"]), _tape(24))
    assert png1 == png2


# --- 9. Fit model: real vertical extent, not em-size (B1) ------------------
#
# The old fit model treated font_size_px itself as the line's vertical
# extent (`size * line_spacing <= max_height_px`), but a font's real
# ascent+descent at a given pixel size is not the same number as that pixel
# size -- it can exceed it. fit_font_size auto-picks the LARGEST size that
# satisfies its height budget, so any gap between the assumed extent (size)
# and the real one (ascent+descent) gets fully spent, and glyphs can render
# past the true canvas edge, silently cut off by resvg's default
# overflow:hidden on the root <svg> (the pixels are gone before rasterize.py
# ever runs -- nothing downstream can detect it from the bitmap alone).


def _ink_pixel_count(img) -> int:
    """Count of black ("ink") pixels in a mode "1" image. rasterize.py's
    threshold makes ink pixels exactly the value-0 ones on an all-white
    background (mode "1" pixels are only ever 0 or 255) -- histogram()[0]
    is that count directly, no need to scan pixel-by-pixel."""
    assert img.mode == "1"
    return img.histogram()[0]


def _grow_canvas_symmetrically(label: RenderedLabel, extra_px: int) -> RenderedLabel:
    """The identical rendered label, on a canvas `extra_px` taller, split
    evenly above and below the original [0, height_px] canvas -- done by
    shifting the viewBox's min-y to -extra_px/2 and growing both the
    viewBox height and the raster width/height attributes by extra_px,
    WITHOUT touching a single drawn x/y coordinate in the body. If the
    original render clipped nothing, this is a no-op on what's visible: a
    render at the new (taller) canvas size must show the exact same ink
    pixels the original did, just with extra blank margin top and bottom.
    If the original DID clip something at its true edge, this reveals it,
    changing the ink-pixel count."""
    half = extra_px // 2
    new_height = label.height_px + extra_px
    old_head = (
        f'width="{label.width_px}" height="{label.height_px}" '
        f'viewBox="0 0 {label.width_px} {label.height_px}">'
    )
    new_head = (
        f'width="{label.width_px}" height="{new_height}" '
        f'viewBox="0 {-half} {label.width_px} {new_height}">'
    )
    assert old_head in label.svg, "SVG header shape changed -- update this test helper"
    return RenderedLabel(
        svg=label.svg.replace(old_head, new_head, 1),
        width_px=label.width_px,
        height_px=new_height,
    )


def test_rasterized_height_equals_print_dots_24mm():
    tape = _tape(24)
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), tape)
    assert rasterize(label).size[1] == tape.print_dots


def test_rasterized_height_equals_print_dots_12mm():
    tape = _tape(12)
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), tape)
    assert rasterize(label).size[1] == tape.print_dots


@pytest.mark.parametrize("text", ["gjpqy", "ÅÄÖ"])  # descenders / accents
def test_auto_fit_nothing_clipped_at_true_canvas_edge(text):
    tape = _tape(24)
    label = TextLabelRenderer().render(TextLabelParams(lines=[text]), tape)

    original_ink = _ink_pixel_count(rasterize(label))
    grown = _grow_canvas_symmetrically(label, extra_px=16)
    grown_ink = _ink_pixel_count(rasterize(grown))

    assert original_ink == grown_ink, (
        "growing the canvas revealed ink the original render clipped at its "
        "true edge -- the fit model left too little vertical margin"
    )


def test_extent_ratio_is_linear_in_probe_size():
    """extent_ratio(family, probe_px) predicts the real ascent+descent at a
    target size, to within 1px, regardless of which probe size it was
    itself measured at -- verified against two different probe sizes (128
    and 1000), each checked against metrics measured directly at an
    unrelated target size (96). Both probes are kept >= the target: probing
    at a SMALLER size than the target would amplify FreeType's per-size
    integer rounding by the size ratio when scaled back up (e.g. a probe of
    100 predicting a target of 500 -- 5x the probe -- is off by several px,
    well outside this tolerance), which is a real limitation of the ratio
    method, not a bug in it; fit_font_size's own default probe (1000) is
    comfortably above _MAX_FONT_PX (128), so it never hits that case."""
    target_size = 96
    font = ImageFont.truetype(str(font_path("Inter")), target_size)
    actual_ascent, actual_descent = font.getmetrics()
    actual_extent = actual_ascent + actual_descent

    for probe_px in (128, 1000):
        predicted_extent = extent_ratio("Inter", probe_px=probe_px) * target_size
        assert abs(predicted_extent - actual_extent) <= 1
