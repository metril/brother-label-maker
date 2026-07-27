"""Tests for the task 2.6 label types: cable_wrap, cable_flag -- Brother's
two cable-identification modes (docs/research/features.md), both bespoke
SVG layouts (NOT built on divided_blocks.py -- see each module's own
docstring for why).

Unlike test_type_configs.py/test_electrical_types.py, these two types don't
delegate to a shared layout engine there's already a test file for -- the
layout math (forced length from diameter, swapped-constraint font fitting,
repeat tiling, region boundaries, rotation) lives entirely in
cable_wrap.py/cable_flag.py themselves, so it's exercised directly here.
Expected pixel values are hand-derived from geometry.mm_to_dots' documented
formula (Decimal, round-half-up, 180dpi) and math.pi, independent of the
modules' own implementation, wherever that's cheap; a few warning/error
trigger scenarios are empirically pinned instead (found once via direct
exploration, then asserted going forward) where hand-deriving the exact
character count that tips a font-fit search would be more fragile than
informative.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from golden_fixtures import CABLE_TYPE_FIXTURES, GOLDEN_SCALE
from pydantic import ValidationError

from labelmaker.driver.geometry import mm_to_dots
from labelmaker.render.document import Tape
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.cable_flag import (
    CableFlagParams,
    CableFlagRenderer,
    _boundaries_px,
)
from labelmaker.render.types.cable_wrap import (
    CableWrapParams,
    CableWrapRenderer,
    _tile_centers,
    _wrap_length_mm,
)

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


def _ink(img, x: int, y: int) -> bool:
    """True if (x, y) is an "ink" (black) pixel in a mode "1" image -- same
    convention as test_divided_blocks.py's own `_ink`."""
    assert img.mode == "1"
    return img.getpixel((x, y)) == 0


# --- 0. Registration: both registered under "network" -----------------


def test_both_types_registered_under_network():
    by_type = {t.type: t for t in list_types()}
    assert by_type.keys() >= {"cable_wrap", "cable_flag"}
    for type_name in ("cable_wrap", "cable_flag"):
        assert by_type[type_name].category == "network"
        assert by_type[type_name].min_tape_mm is None


def test_get_renderer_returns_expected_renderer_instances():
    assert isinstance(get_renderer("cable_wrap"), CableWrapRenderer)
    assert isinstance(get_renderer("cable_flag"), CableFlagRenderer)


def test_api_lists_nine_types():
    # text, barcode, patch_panel, punch_down, faceplate, cable_wrap,
    # cable_flag, terminal_block, breaker_box.
    assert {t.type for t in list_types()} == {
        "text", "barcode", "patch_panel", "punch_down", "faceplate",
        "cable_wrap", "cable_flag", "terminal_block", "breaker_box",
    }
    assert len(list_types()) == 9


# --- 1. cable_wrap: Params validation ---------------------------------------


def test_cable_wrap_defaults():
    p = CableWrapParams(lines=["X"])
    assert p.cable_diameter_mm == 6.0
    assert p.overlap_mm == 5.0
    assert p.repeat is True
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.font_size_px is None
    assert p.padding_mm == 1.0


@pytest.mark.parametrize("diameter", [3.0, 90.0])
def test_cable_wrap_diameter_boundaries_accepted(diameter):
    CableWrapParams(lines=["X"], cable_diameter_mm=diameter)


@pytest.mark.parametrize("diameter", [2.9, 90.1])
def test_cable_wrap_diameter_out_of_range_rejected(diameter):
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["X"], cable_diameter_mm=diameter)


@pytest.mark.parametrize("overlap", [5.0, 20.0])
def test_cable_wrap_overlap_boundaries_accepted(overlap):
    CableWrapParams(lines=["X"], overlap_mm=overlap)


@pytest.mark.parametrize("overlap", [4.9, 20.1])
def test_cable_wrap_overlap_out_of_range_rejected(overlap):
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["X"], overlap_mm=overlap)


def test_cable_wrap_one_or_two_lines_accepted():
    CableWrapParams(lines=["A"])
    CableWrapParams(lines=["A", "B"])


def test_cable_wrap_three_lines_rejected():
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["A", "B", "C"])


def test_cable_wrap_zero_lines_rejected():
    with pytest.raises(ValidationError):
        CableWrapParams(lines=[])


def test_cable_wrap_line_over_30_chars_rejected():
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["A" * 31])


def test_cable_wrap_line_exactly_30_chars_accepted():
    CableWrapParams(lines=["A" * 30])


def test_cable_wrap_all_blank_lines_rejected():
    with pytest.raises(ValidationError, match="at least one line must be non-empty"):
        CableWrapParams(lines=["", "  "])


def test_cable_wrap_unknown_font_family_rejected():
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["X"], font_family="Comic Sans")


def test_cable_wrap_font_size_px_out_of_range_rejected():
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["X"], font_size_px=5)
    with pytest.raises(ValidationError):
        CableWrapParams(lines=["X"], font_size_px=129)


# --- 2. cable_wrap: geometry (hand-derived, independent of the module) -----


def test_wrap_length_forced_by_diameter_and_overlap():
    # pi*6 + 5 ~= 23.8496mm -- hand-derived via math.pi, matching the task
    # brief's own worked example.
    params = CableWrapParams(lines=["X"])
    assert _wrap_length_mm(params) == math.pi * 6.0 + 5.0

    label = CableWrapRenderer().render(params, _tape(24))
    assert label.width_px == mm_to_dots(math.pi * 6.0 + 5.0) == 169


def test_wrap_length_varies_with_diameter_and_overlap():
    params = CableWrapParams(lines=["X"], cable_diameter_mm=20.0, overlap_mm=8.0)
    label = CableWrapRenderer().render(params, _tape(24))
    assert label.width_px == mm_to_dots(math.pi * 20.0 + 8.0)


def test_wrap_height_is_the_full_print_strip():
    for tape_mm, expected_dots in [(24, 128), (12, 70), (9, 50)]:
        label = CableWrapRenderer().render(CableWrapParams(lines=["X"]), _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 3. cable_wrap: rotation -------------------------------------------


def test_wrap_text_rotated_90_counterclockwise():
    # Brother's own Cable Wrap mode rotates text 90 CCW (docs/research/
    # features.md) -- SVG rotate(-90, ...) in a y-down coordinate system,
    # same direction divided_blocks.py's BACKBONE orientation uses. Assert
    # the substring literally, not just "any rotate(" -- rotate(90 (the
    # OTHER direction) must never appear for this type.
    label = CableWrapRenderer().render(CableWrapParams(lines=["X"]), _tape(24))
    assert "rotate(-90," in label.svg
    assert "rotate(90," not in label.svg


# --- 4. cable_wrap: repeat tiling ----------------------------------------


def test_repeat_false_yields_exactly_one_instance():
    label = CableWrapRenderer().render(
        CableWrapParams(lines=["X"], repeat=False, cable_diameter_mm=90.0, overlap_mm=20.0),
        _tape(24),
    )
    assert label.svg.count("rotate(-90,") == 1


def test_repeat_true_on_a_long_label_yields_multiple_instances():
    label = CableWrapRenderer().render(
        CableWrapParams(lines=["X"], repeat=True, cable_diameter_mm=90.0, overlap_mm=20.0),
        _tape(24),
    )
    assert label.svg.count("rotate(-90,") > 1


def test_repeat_true_instance_count_matches_hand_derived_tiling_formula():
    # font_size_px pinned (no auto-fit search to reason about) so the
    # instance length -- and therefore how many fit -- is exactly
    # predictable: len(lines)*font_px*line_spacing.
    params = CableWrapParams(
        lines=["A"], font_size_px=10, cable_diameter_mm=90.0, overlap_mm=20.0
    )
    label = CableWrapRenderer().render(params, _tape(24))
    assert label.warnings == []  # font_size_px=10 must not have been clamped

    width_px = mm_to_dots(math.pi * 90.0 + 20.0)
    padding_px = mm_to_dots(1.0)  # default padding_mm
    length_budget_px = width_px - 2 * padding_px
    instance_len_px = 1 * 10 * 1.15  # n_lines * font_px * line_spacing
    gap_px = mm_to_dots(2.0)
    expected_n = max(1, math.floor((length_budget_px + gap_px) / (instance_len_px + gap_px)))

    assert label.svg.count("rotate(-90,") == expected_n == 84


def test_gap_between_repeated_instances_is_at_least_2mm():
    params = CableWrapParams(
        lines=["A"], font_size_px=10, cable_diameter_mm=90.0, overlap_mm=20.0
    )
    label = CableWrapRenderer().render(params, _tape(24))
    cxs = [float(m.group(1)) for m in re.finditer(r"rotate\(-90, ([\d.]+),", label.svg)]
    assert len(cxs) > 1
    instance_len_px = 1 * 10 * 1.15
    edge_gaps = [
        (cxs[i + 1] - instance_len_px / 2) - (cxs[i] + instance_len_px / 2)
        for i in range(len(cxs) - 1)
    ]
    for gap in edge_gaps:
        assert gap >= mm_to_dots(2.0) - 0.1  # -0.1: _fmt_num's 2-decimal rounding noise


def test_tile_centers_math_n1_centers_on_the_whole_budget():
    # n=1: the single instance is centered on padding_px + budget_px/2,
    # regardless of instance_len_px -- the same formula as n>1, not a
    # special case (see cable_wrap.py's module docstring).
    centers = _tile_centers(1, instance_len_px=10.0, budget_px=50.0, padding_px=5.0)
    assert centers == [5.0 + 50.0 / 2]


def test_tile_centers_math_n3_evenly_spaced_with_computed_gap():
    # budget=50, 3 instances of length 10 -> leftover 20, split into 2 gaps
    # of 10 each -> centers at 10, 30, 50 (hand-derived).
    centers = _tile_centers(3, instance_len_px=10.0, budget_px=50.0, padding_px=5.0)
    assert centers == [10.0, 30.0, 50.0]


# --- 5. cable_wrap: warnings / errors --------------------------------------


def test_wrap_auto_font_hits_floor_and_still_fits_warns_cramped():
    label = CableWrapRenderer().render(CableWrapParams(lines=["A" * 7]), _tape(9))
    assert [w.code for w in label.warnings] == ["text_cramped"]


def test_wrap_unfittable_text_raises_value_error_naming_tape_width():
    with pytest.raises(ValueError, match=r"text too long for 3\.5mm tape"):
        CableWrapRenderer().render(CableWrapParams(lines=["A" * 30]), _tape(3.5))


def test_wrap_explicit_font_size_clamped_to_length_budget_warns_font_clamped():
    label = CableWrapRenderer().render(
        CableWrapParams(
            lines=["X"], font_size_px=128, cable_diameter_mm=3.0, overlap_mm=5.0
        ),
        _tape(24),
    )
    codes = [w.code for w in label.warnings]
    assert "font_clamped" in codes


def test_wrap_explicit_font_size_that_fits_has_no_warning():
    label = CableWrapRenderer().render(
        CableWrapParams(lines=["X"], font_size_px=10), _tape(24)
    )
    assert label.warnings == []


# --- 6. cable_flag: Params validation ---------------------------------------


def test_cable_flag_defaults():
    p = CableFlagParams(lines=["X"])
    assert p.cable_diameter_mm == 4.0
    assert p.flag_length_mm == 20.0
    assert p.text_orientation == "horizontal"
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.font_size_px is None
    assert p.padding_mm == 1.0


@pytest.mark.parametrize("diameter", [3.0, 90.0])
def test_cable_flag_diameter_boundaries_accepted(diameter):
    CableFlagParams(lines=["X"], cable_diameter_mm=diameter)


@pytest.mark.parametrize("diameter", [2.9, 90.1])
def test_cable_flag_diameter_out_of_range_rejected(diameter):
    with pytest.raises(ValidationError):
        CableFlagParams(lines=["X"], cable_diameter_mm=diameter)


@pytest.mark.parametrize("flag_length", [5.0, 100.0])
def test_cable_flag_flag_length_boundaries_accepted(flag_length):
    CableFlagParams(lines=["X"], flag_length_mm=flag_length)


@pytest.mark.parametrize("flag_length", [4.9, 100.1])
def test_cable_flag_flag_length_out_of_range_rejected(flag_length):
    with pytest.raises(ValidationError):
        CableFlagParams(lines=["X"], flag_length_mm=flag_length)


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_cable_flag_orientation_valid_values_accepted(orientation):
    CableFlagParams(lines=["X"], text_orientation=orientation)


def test_cable_flag_invalid_orientation_rejected():
    with pytest.raises(ValidationError):
        CableFlagParams(lines=["X"], text_orientation="diagonal")


def test_cable_flag_line_over_30_chars_rejected():
    with pytest.raises(ValidationError):
        CableFlagParams(lines=["A" * 31])


def test_cable_flag_all_blank_lines_rejected():
    with pytest.raises(ValidationError, match="at least one line must be non-empty"):
        CableFlagParams(lines=[""])


# --- 7. cable_flag: geometry (hand-derived) ---------------------------------


def test_flag_total_length_from_diameter_and_flag_length():
    # 20 + (pi*4 + 1) + 20 -- the task brief's own worked example.
    params = CableFlagParams(lines=["X"], cable_diameter_mm=4.0, flag_length_mm=20.0)
    label = CableFlagRenderer().render(params, _tape(24))
    expected_mm = 2 * 20.0 + (math.pi * 4.0 + 1.0)
    assert label.width_px == mm_to_dots(expected_mm) == 380


def test_flag_boundaries_sum_to_total_width():
    params = CableFlagParams(lines=["X"], cable_diameter_mm=4.0, flag_length_mm=20.0)
    b1, b2, b3 = _boundaries_px(params)
    assert (b1, b2, b3) == (142, 238, 380)
    label = CableFlagRenderer().render(params, _tape(24))
    assert label.width_px == b3


def test_flag_height_is_the_full_print_strip():
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = CableFlagRenderer().render(CableFlagParams(lines=["X"]), _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 8. cable_flag: rotation -------------------------------------------


def test_flag_horizontal_end_a_unrotated_end_b_rotated_180():
    label = CableFlagRenderer().render(
        CableFlagParams(lines=["X"], text_orientation="horizontal"), _tape(24)
    )
    assert "rotate(180," in label.svg
    assert "rotate(90," not in label.svg
    assert "rotate(270," not in label.svg


def test_flag_vertical_end_a_rotated_90_end_b_rotated_270():
    label = CableFlagRenderer().render(
        CableFlagParams(lines=["X"], text_orientation="vertical"), _tape(24)
    )
    assert "rotate(90," in label.svg
    assert "rotate(270," in label.svg
    assert "rotate(180," not in label.svg


# --- 9. cable_flag: fold guides + gap blankness (bitmap) -------------------


def _flag_bitmap(lines=("X",), font_size_px=10, flag_length_mm=20.0, cable_diameter_mm=4.0):
    params = CableFlagParams(
        lines=list(lines),
        font_size_px=font_size_px,
        flag_length_mm=flag_length_mm,
        cable_diameter_mm=cable_diameter_mm,
    )
    label = CableFlagRenderer().render(params, _tape(24))
    return rasterize(label), _boundaries_px(params)


def test_fold_guide_dash_pattern_at_each_boundary():
    # 4px-on/4px-off starting at y=0, same convention as divided_blocks.py's
    # own DASH separator.
    img, (b1, b2, b3) = _flag_bitmap()
    for x in (b1, b2):
        for y in (0, 3, 8, 11):
            assert _ink(img, x, y), f"fold guide at x={x} should be ink at y={y}"
        for y in (4, 7, 12, 15):
            assert not _ink(img, x, y), f"fold guide at x={x} should be a gap at y={y}"


def test_gap_region_is_blank_except_fold_guides():
    img, (b1, b2, b3) = _flag_bitmap()
    height_px = img.size[1]
    mid_x = (b1 + b2) // 2
    assert not any(_ink(img, mid_x, y) for y in range(height_px))
    # a column just inside the gap, next to (but not on) each boundary --
    # also blank, confirming the flag text stays within its own flag,
    # never bleeding into the gap.
    assert not any(_ink(img, b1 + 2, y) for y in range(height_px))
    assert not any(_ink(img, b2 - 2, y) for y in range(height_px))


# --- 10. cable_flag: warnings / errors --------------------------------------


def test_flag_auto_font_hits_floor_and_still_fits_warns_cramped():
    label = CableFlagRenderer().render(
        CableFlagParams(lines=["A" * 9], flag_length_mm=8.0), _tape(6)
    )
    assert [w.code for w in label.warnings] == ["text_cramped"]


def test_flag_unfittable_text_horizontal_raises_value_error():
    with pytest.raises(ValueError, match="text too long for a 5.0mm flag"):
        CableFlagRenderer().render(
            CableFlagParams(lines=["A" * 30], flag_length_mm=5.0), _tape(6)
        )


def test_flag_unfittable_text_vertical_raises_value_error_naming_tape():
    with pytest.raises(ValueError, match=r"on a 3\.5mm tape"):
        CableFlagRenderer().render(
            CableFlagParams(lines=["A" * 30], text_orientation="vertical"), _tape(3.5)
        )


def test_flag_explicit_font_size_clamped_warns_font_clamped():
    label = CableFlagRenderer().render(
        CableFlagParams(lines=["X"], font_size_px=128, flag_length_mm=15.0), _tape(24)
    )
    assert "font_clamped" in [w.code for w in label.warnings]


def test_flag_explicit_font_size_that_fits_has_no_warning():
    label = CableFlagRenderer().render(
        CableFlagParams(lines=["X"], font_size_px=10), _tape(24)
    )
    assert label.warnings == []


# --- 11. Schema fidelity: every field carries a description -----------------


@pytest.mark.parametrize(
    "params_cls", [CableWrapParams, CableFlagParams], ids=lambda c: c.__name__
)
def test_every_field_carries_a_description(params_cls):
    props = params_cls.model_json_schema()["properties"]
    for field_name, schema in props.items():
        assert schema.get("description"), f"{params_cls.__name__}.{field_name} has no description"


def test_cable_wrap_diameter_and_overlap_bounds_visible_in_schema():
    props = CableWrapParams.model_json_schema()["properties"]
    assert props["cable_diameter_mm"]["minimum"] == 3
    assert props["cable_diameter_mm"]["maximum"] == 90
    assert props["overlap_mm"]["minimum"] == 5
    assert props["overlap_mm"]["maximum"] == 20


def test_cable_flag_diameter_and_flag_length_bounds_visible_in_schema():
    props = CableFlagParams.model_json_schema()["properties"]
    assert props["cable_diameter_mm"]["minimum"] == 3
    assert props["cable_diameter_mm"]["maximum"] == 90
    assert props["flag_length_mm"]["minimum"] == 5
    assert props["flag_length_mm"]["maximum"] == 100


# --- 12. Golden PNGs: byte-locked against committed files -------------------
#
# Fixture definitions live in golden_fixtures.py (shared with
# scripts/regen_goldens.py) -- visually inspect any new/changed golden
# before committing it (see task-2.6-report.md for descriptions).


def _render_preview_png(renderer, params, tape) -> bytes:
    label = renderer.render(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", CABLE_TYPE_FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    renderer = get_renderer(fixture.type)
    png = _render_preview_png(renderer, fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden
