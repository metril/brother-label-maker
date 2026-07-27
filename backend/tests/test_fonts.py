"""Tests for labelmaker.render.fonts: hermetic bundled fonts + measurement."""

import pytest
from PIL import ImageFont

from labelmaker.render import fonts as fonts_module
from labelmaker.render.fonts import (
    FONTS_DIR,
    FontInfo,
    ensure_fonts_dir,
    extent_ratio,
    fit_font_size,
    font_path,
    list_fonts,
    measure_text,
)

# --- 1. list_fonts() ---


def test_list_fonts_returns_four_families():
    fonts = list_fonts()
    assert len(fonts) == 4
    assert all(isinstance(f, FontInfo) for f in fonts)
    families = {f.family for f in fonts}
    assert families == {"Inter", "Roboto Condensed", "JetBrains Mono", "DejaVu Sans"}


def test_list_fonts_all_have_bold():
    assert all(f.has_bold for f in list_fonts())


def test_list_fonts_monospace_flag_only_on_jetbrains_mono():
    monospace = {f.family for f in list_fonts() if f.monospace}
    assert monospace == {"JetBrains Mono"}


# --- 2. font_path() ---


@pytest.mark.parametrize(
    "family,bold,filename",
    [
        ("Inter", False, "Inter-Regular.ttf"),
        ("Inter", True, "Inter-Bold.ttf"),
        ("Roboto Condensed", False, "RobotoCondensed-Regular.ttf"),
        ("Roboto Condensed", True, "RobotoCondensed-Bold.ttf"),
        ("JetBrains Mono", False, "JetBrainsMono-Regular.ttf"),
        ("JetBrains Mono", True, "JetBrainsMono-Bold.ttf"),
        ("DejaVu Sans", False, "DejaVuSans.ttf"),
        ("DejaVu Sans", True, "DejaVuSans-Bold.ttf"),
    ],
)
def test_font_path_maps_family_and_bold_to_expected_file(family, bold, filename):
    assert font_path(family, bold) == FONTS_DIR / filename


def test_font_path_default_is_not_bold():
    assert font_path("Inter") == font_path("Inter", bold=False)


def test_font_path_unknown_family_raises_with_valid_list():
    with pytest.raises(ValueError, match="Inter"):
        font_path("Comic Sans")


# --- 2b. ensure_fonts_dir(): missing FONTS_DIR fails loudly, not silently ---
#
# Without this guard, a missing/misplaced fonts directory doesn't raise
# anywhere in this module -- font_path() would happily return a Path to a
# file that doesn't exist, and resvg (in rasterize.py) would silently render
# a blank label rather than erroring. See fonts.ensure_fonts_dir()'s
# docstring and rasterize.py's module docstring for the full failure mode.


def test_ensure_fonts_dir_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(fonts_module, "FONTS_DIR", tmp_path / "does-not-exist")
    with pytest.raises(RuntimeError, match="fonts directory not found"):
        ensure_fonts_dir()


def test_ensure_fonts_dir_passes_when_present():
    ensure_fonts_dir()  # FONTS_DIR is the real bundled directory -- no raise


def test_font_path_raises_runtime_error_when_fonts_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(fonts_module, "FONTS_DIR", tmp_path / "does-not-exist")
    with pytest.raises(RuntimeError, match="fonts directory not found"):
        font_path("Inter")


def test_ensure_fonts_dir_raises_when_fonts_dir_is_a_file(monkeypatch, tmp_path):
    not_a_dir = tmp_path / "fonts-but-actually-a-file"
    not_a_dir.write_text("oops")
    monkeypatch.setattr(fonts_module, "FONTS_DIR", not_a_dir)
    with pytest.raises(RuntimeError, match="fonts directory not found"):
        ensure_fonts_dir()


# --- 2c. ensure_fonts_dir(): a directory that EXISTS but is missing one or
# more of the 8 expected TTFs also fails loudly (task 1.2 review, deferred
# to 2.7) -- not just a missing directory. Without this, a partial fonts
# dir sails through ensure_fonts_dir() and only fails much later, deep
# inside font_path()/resvg, as a generic "file not found" instead of a
# clear "here's what's missing" error at this same first-use checkpoint.


def test_ensure_fonts_dir_raises_when_one_ttf_is_missing(monkeypatch, tmp_path):
    partial = tmp_path / "partial-fonts"
    partial.mkdir()
    for name in {f for f in fonts_module._FILES.values()}:
        (partial / name).write_bytes(b"not a real font, just needs to exist")
    (partial / "JetBrainsMono-Bold.ttf").unlink()
    monkeypatch.setattr(fonts_module, "FONTS_DIR", partial)
    with pytest.raises(RuntimeError, match="JetBrainsMono-Bold.ttf"):
        ensure_fonts_dir()


def test_ensure_fonts_dir_names_multiple_missing_files(monkeypatch, tmp_path):
    partial = tmp_path / "partial-fonts-2"
    partial.mkdir()
    for name in set(fonts_module._FILES.values()):
        (partial / name).write_bytes(b"placeholder")
    (partial / "Inter-Bold.ttf").unlink()
    (partial / "DejaVuSans.ttf").unlink()
    monkeypatch.setattr(fonts_module, "FONTS_DIR", partial)
    with pytest.raises(RuntimeError) as exc_info:
        ensure_fonts_dir()
    message = str(exc_info.value)
    assert "Inter-Bold.ttf" in message
    assert "DejaVuSans.ttf" in message


def test_ensure_fonts_dir_passes_with_all_8_files_present(monkeypatch, tmp_path):
    complete = tmp_path / "complete-fonts"
    complete.mkdir()
    for name in set(fonts_module._FILES.values()):
        (complete / name).write_bytes(b"placeholder")
    monkeypatch.setattr(fonts_module, "FONTS_DIR", complete)
    ensure_fonts_dir()  # no raise -- directory exists AND all 8 files present


# --- 3. All 8 files exist, are nonempty, and load with their declared family ---


def test_all_bundled_font_files_exist_and_are_nonempty():
    for family in {f.family for f in list_fonts()}:
        for bold in (False, True):
            path = font_path(family, bold)
            assert path.is_file(), f"{path} missing"
            assert path.stat().st_size > 0, f"{path} is empty"


def test_all_bundled_font_files_load_and_declare_their_family():
    for family in {f.family for f in list_fonts()}:
        for bold in (False, True):
            loaded = ImageFont.truetype(str(font_path(family, bold)), 24)
            declared_family, _style = loaded.getname()
            assert declared_family == family


# --- 4. measure_text() ---


def test_measure_text_monotonic_in_string_length():
    short_w, _ = measure_text("A", "Inter", 40)
    long_w, _ = measure_text("A LONGER STRING OF TEXT", "Inter", 40)
    assert long_w >= short_w


def test_measure_text_monotonic_in_font_size():
    small_w, small_h = measure_text("HELLO", "Inter", 10)
    big_w, big_h = measure_text("HELLO", "Inter", 40)
    assert big_w > small_w
    assert big_h > small_h


def test_measure_text_bold_variant_loads_independently():
    w_regular, _ = measure_text("HELLO", "Inter", 40, bold=False)
    w_bold, _ = measure_text("HELLO", "Inter", 40, bold=True)
    assert w_regular > 0
    assert w_bold > 0


# --- 5. fit_font_size() ---


def test_fit_font_size_fits_within_height_only():
    size = fit_font_size(["HELLO"], "Inter", None, 100.0)
    # N=1 line: size * extent_ratio(family) * line_spacing <= 100 (B1: fit is
    # on the font's real vertical extent, not on size itself -- see
    # fit_font_size's docstring).
    assert size * extent_ratio("Inter") * 1.15 <= 100.0 + 1e-9
    assert size >= 6
    # One size larger must NOT fit -- pins this as the true boundary, not a
    # vacuously-true inequality (e.g. a size far below the real limit would
    # also satisfy the assertion above without this).
    assert (size + 1) * extent_ratio("Inter") * 1.15 > 100.0 + 1e-9


def test_fit_font_size_respects_width_constraint():
    size = fit_font_size(["HI"], "Inter", 100.0, 1000.0)
    width, _ = measure_text("HI", "Inter", size)
    # width must fit inside the 0.95 safety-margined budget, and the fit
    # must not be the degenerate min_px fallback (100px is generous for "HI")
    assert size > 6
    assert width <= 100.0 * 0.95 + 1e-6


def test_fit_font_size_falls_back_to_min_px_when_width_budget_is_impossible():
    # Even at min_px, this string cannot fit inside a 1px width budget --
    # fit_font_size must fall back to min_px rather than loop forever or
    # return something smaller than min_px.
    size = fit_font_size(["A REASONABLY LONG LINE OF TEXT"], "Inter", 1.0, 1000.0)
    assert size == 6


def test_fit_font_size_multiple_lines_shrinks_to_fit_height():
    one_line = fit_font_size(["X"], "Inter", None, 100.0)
    four_lines = fit_font_size(["X", "X", "X", "X"], "Inter", None, 100.0)
    assert four_lines <= one_line


def test_fit_font_size_hits_min_px_when_impossible():
    size = fit_font_size(["X"], "Inter", None, 0.5, min_px=6, max_px=128)
    assert size == 6


def test_fit_font_size_caps_at_max_px():
    size = fit_font_size(["X"], "Inter", None, 100000.0, max_px=20)
    assert size == 20
