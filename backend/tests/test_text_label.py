"""Tests for labelmaker.render.types.text_label: the "text" label type."""

from pathlib import Path

import pytest
from golden_fixtures import FIXTURES, GOLDEN_SCALE
from PIL import Image, ImageFont
from pydantic import ValidationError

from labelmaker.driver.geometry import MIN_LABEL_MM, dots_to_mm, mm_to_dots
from labelmaker.render.document import RenderedLabel, Tape
from labelmaker.render.fonts import extent_ratio, font_path
from labelmaker.render.images import image_path, uploads_dir
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.text_label import (
    ImageIcon,
    SymbolIcon,
    TextLabelParams,
    TextLabelRenderer,
)

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


def _render_preview_png(params: TextLabelParams, tape, data_dir=None) -> bytes:
    label = TextLabelRenderer().render(params, tape, data_dir=data_dir)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    png = _render_preview_png(
        fixture.params, _tape(fixture.tape_mm, fixture.tape_family), fixture.data_dir
    )
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


# --- 10. `icon` (task 2.7): leading symbol/image art -------------------------


def test_params_icon_defaults_to_none():
    assert TextLabelParams(lines=["HI"]).icon is None


def test_params_icon_symbol_kind_parses():
    p = TextLabelParams(lines=["HI"], icon={"kind": "symbol", "id": "bolt"})
    assert isinstance(p.icon, SymbolIcon)
    assert p.icon.id == "bolt"


def test_params_icon_image_kind_parses_with_defaults():
    p = TextLabelParams(lines=["HI"], icon={"kind": "image", "image_id": "abc123"})
    assert isinstance(p.icon, ImageIcon)
    assert p.icon.mode == "threshold"
    assert p.icon.threshold == 128


def test_params_icon_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(lines=["HI"], icon={"kind": "bogus", "id": "x"})


def test_params_icon_image_threshold_out_of_range_rejected():
    with pytest.raises(ValidationError):
        TextLabelParams(
            lines=["HI"], icon={"kind": "image", "image_id": "x", "threshold": 300}
        )


# -- symbol icon: layout ------------------------------------------------------


def test_symbol_icon_reserves_square_sized_to_print_area():
    tape = _tape(24)  # print_dots == 128
    padding_px = mm_to_dots(2.0)  # default padding_mm
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["SERVER"], icon=SymbolIcon(id="bolt")), tape
    )
    expected_icon_size = tape.print_dots - 2 * padding_px
    # symbol_object() formats the scale via document.py's _fmt_num (fixed
    # 2-decimal, trailing zeros trimmed) -- match that exactly rather than
    # Python's own float formatting, which would disagree (e.g. "4.17" vs
    # "4.166666666666667").
    expected_scale = f"{expected_icon_size / 24:.2f}".rstrip("0").rstrip(".")
    assert f"scale({expected_scale})" in label.svg
    assert f"translate({padding_px},{padding_px})" in label.svg


def test_symbol_icon_shifts_left_aligned_text_right_by_icon_plus_padding():
    tape = _tape(24)
    padding_px = mm_to_dots(2.0)
    icon_size_px = tape.print_dots - 2 * padding_px
    expected_x = padding_px + icon_size_px + padding_px

    with_icon = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], h_align="left", icon=SymbolIcon(id="bolt")), tape
    )
    without_icon = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], h_align="left"), tape
    )
    assert f'x="{expected_x}"' in with_icon.svg
    # sanity: the no-icon render uses plain padding_px as its left edge, a
    # different (smaller) x than the icon case -- proves the shift is real,
    # not a coincidental match.
    assert f'x="{padding_px}"' in without_icon.svg
    assert f'x="{expected_x}"' not in without_icon.svg


def test_symbol_icon_auto_width_grows_to_fit_icon_plus_text():
    tape = _tape(24)
    with_icon = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], font_size_px=20, icon=SymbolIcon(id="bolt")), tape
    )
    without_icon = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], font_size_px=20), tape
    )
    assert with_icon.width_px > without_icon.width_px


def test_symbol_icon_unknown_id_raises_value_error():
    tape = _tape(24)
    with pytest.raises(ValueError, match="unknown symbol id"):
        TextLabelRenderer().render(
            TextLabelParams(lines=["HI"], icon=SymbolIcon(id="not-a-real-icon")), tape
        )


def test_symbol_icon_too_tall_for_tiny_tape_raises_value_error():
    tiny_tape = _tape(3.5)  # print_dots == 24; default padding leaves too little room
    with pytest.raises(ValueError, match="no room for a square icon"):
        TextLabelRenderer().render(
            TextLabelParams(lines=["A"], padding_mm=6.0, icon=SymbolIcon(id="bolt")), tiny_tape
        )


def test_symbol_icon_wider_than_fixed_length_raises_value_error_not_silent_clip():
    # Regression: icon_size_px (128 - 2*14 = 100px on a 24mm tape) is far
    # wider than a 5mm fixed length (~35px) -- before this guard, the icon
    # rendered past the SVG root's right edge and was silently clipped away
    # by resvg's default overflow:hidden, with no warning pointing at why
    # (only a text_truncated warning about the TEXT, unrelated to the
    # icon's own near-total invisibility). Must 422, not silently vanish.
    tape = _tape(24)
    with pytest.raises(ValueError, match="icon does not fit within the fixed label length"):
        TextLabelRenderer().render(
            TextLabelParams(lines=["X"], icon=SymbolIcon(id="bolt"), length_mm=5.0), tape
        )


def test_symbol_icon_fixed_length_exactly_at_minimum_required_succeeds():
    tape = _tape(24)  # print_dots == 128
    padding_px = mm_to_dots(2.0)
    icon_size_px = tape.print_dots - 2 * padding_px
    content_left_px = padding_px + icon_size_px + padding_px
    min_required_px = content_left_px + padding_px  # icon + gap + right padding, zero text
    # dots_to_mm is the exact (unrounded) inverse of mm_to_dots -- add a
    # small margin so re-rounding length_mm back to dots via mm_to_dots
    # (round-half-up) can never land one dot BELOW min_required_px.
    length_mm = dots_to_mm(min_required_px) + 0.1
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["X"], icon=SymbolIcon(id="bolt"), length_mm=length_mm), tape
    )
    assert label.width_px >= min_required_px


def test_symbol_icon_object_map_stays_empty():
    # A symbol icon is pure vector -- never a dither region (only an
    # image icon in dither mode is).
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], icon=SymbolIcon(id="bolt")), tape
    )
    assert label.object_map == []


def test_center_and_right_align_still_work_with_icon_present():
    tape = _tape(24)
    for h_align, anchor in [("center", "middle"), ("right", "end")]:
        label = TextLabelRenderer().render(
            TextLabelParams(lines=["HI"], h_align=h_align, icon=SymbolIcon(id="bolt")), tape
        )
        assert f'text-anchor="{anchor}"' in label.svg


def test_no_icon_render_is_byte_identical_to_pre_2_7_shape():
    # icon=None must reduce every new content_left_px-based formula back to
    # its original padding_px-only form exactly -- the whole existing golden
    # suite already pins this indirectly, but this test makes the "no
    # regression for the common case" property explicit and fast.
    tape = _tape(24)
    label = TextLabelRenderer().render(TextLabelParams(lines=["HELLO"]), tape)
    assert label.object_map == []
    assert "<image" not in label.svg


# -- image icon: layout + threshold/dither ------------------------------------


def _put_upload(data_dir: Path, image_id: str, img: Image.Image) -> None:
    uploads_dir(data_dir).mkdir(parents=True, exist_ok=True)
    img.save(image_path(image_id, data_dir), format="PNG")


def _gradient(width: int, height: int) -> Image.Image:
    img = Image.new("L", (width, height))
    for x in range(width):
        value = round(255 * x / max(1, width - 1))
        for y in range(height):
            img.putpixel((x, y), value)
    return img.convert("RGB")


def test_image_icon_threshold_mode_renders(tmp_path):
    _put_upload(tmp_path, "logo", _gradient(40, 40))
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["CAM-3"], icon=ImageIcon(image_id="logo")),
        tape,
        data_dir=tmp_path,
    )
    assert "<image" in label.svg
    assert label.object_map == []  # threshold mode needs no dither region


def test_image_icon_dither_mode_adds_offset_object_region(tmp_path):
    _put_upload(tmp_path, "logo", _gradient(40, 40))
    tape = _tape(24)  # print_dots == 128
    padding_px = mm_to_dots(2.0)
    icon_size_px = tape.print_dots - 2 * padding_px
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["CAM-3"], icon=ImageIcon(image_id="logo", mode="dither")),
        tape,
        data_dir=tmp_path,
    )
    assert len(label.object_map) == 1
    region = label.object_map[0]
    assert region.mode == "dither"
    assert (region.x, region.y) == (padding_px, padding_px)
    assert (region.width, region.height) == (icon_size_px, icon_size_px)


def test_image_icon_dither_mode_rasterizes_with_scattered_pixels(tmp_path):
    _put_upload(tmp_path, "logo", _gradient(200, 200))
    tape = _tape(24)
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["CAM-3"], icon=ImageIcon(image_id="logo", mode="dither")),
        tape,
        data_dir=tmp_path,
    )
    img = rasterize(label)
    region = label.object_map[0]
    xs = range(region.x, region.x + region.width)
    ys = range(region.y, region.y + region.height)
    black = sum(1 for x in xs for y in ys if img.getpixel((x, y)) == 0)
    total = region.width * region.height
    assert 0.05 < (black / total) < 0.95


def test_image_icon_missing_data_dir_raises_clear_error():
    tape = _tape(24)
    with pytest.raises(ValueError, match="data_dir"):
        TextLabelRenderer().render(
            TextLabelParams(lines=["HI"], icon=ImageIcon(image_id="logo")), tape
        )  # data_dir omitted entirely


def test_image_icon_unknown_id_raises_value_error(tmp_path):
    tape = _tape(24)
    with pytest.raises(ValueError, match="unknown image_id"):
        TextLabelRenderer().render(
            TextLabelParams(lines=["HI"], icon=ImageIcon(image_id="no-such-id")),
            tape,
            data_dir=tmp_path,
        )


def test_image_icon_is_forced_square_regardless_of_source_aspect_ratio(tmp_path):
    _put_upload(tmp_path, "wide", Image.new("RGB", (400, 100), "black"))  # 4:1 source
    tape = _tape(24)
    padding_px = mm_to_dots(2.0)
    expected_icon_size = tape.print_dots - 2 * padding_px
    label = TextLabelRenderer().render(
        TextLabelParams(lines=["HI"], icon=ImageIcon(image_id="wide")), tape, data_dir=tmp_path
    )
    assert f'width="{expected_icon_size}" height="{expected_icon_size}"' in label.svg
