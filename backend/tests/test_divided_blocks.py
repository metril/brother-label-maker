"""Tests for labelmaker.render.types.divided_blocks: the divided-blocks
layout engine (task 2.1) that 2.2/2.3's five thin-config label types will
sit on top of. This module is NOT a registered label type (see its module
docstring) -- these tests import layout_blocks/render_divided_blocks
directly, not via get_renderer()/render_definition().

Expected pixel values in the pure-math section below are hand-derived from
geometry.mm_to_dots' documented formula (Decimal, round-half-up, 180dpi),
independent of divided_blocks.py's implementation -- see the module
docstring's algorithm description for the cumulative-rounding scheme these
numbers assume.
"""

from pathlib import Path

import pytest
from golden_fixtures import DIVIDED_BLOCKS_FIXTURES, GOLDEN_SCALE
from pydantic import ValidationError

from labelmaker.driver.geometry import mm_to_dots
from labelmaker.render.document import Tape
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import list_types
from labelmaker.render.types.divided_blocks import (
    BlockLayout,
    BlockSpec,
    DividedBlocksParams,
    Orientation,
    Separator,
    layout_blocks,
    render_divided_blocks,
)

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


def _ink(img, x: int, y: int) -> bool:
    """True if (x, y) is an "ink" (black) pixel in a mode "1" image --
    mode "1" pixels are only ever 0 (black/ink) or 255 (white), per
    rasterize.py's threshold step; see test_text_label.py's
    _ink_pixel_count for the same convention."""
    assert img.mode == "1"
    return img.getpixel((x, y)) == 0


# --- 0. This engine registers no label type of its own -----------------


def test_divided_blocks_registers_no_label_type():
    assert "divided_blocks" not in {t.type for t in list_types()}


# --- 1. BlockSpec / DividedBlocksParams validation ----------------------


def test_block_spec_defaults():
    b = BlockSpec()
    assert b.lines == [""]
    assert b.width_multiplier == 1.0


@pytest.mark.parametrize("multiplier", [0.1, 9.5])
def test_block_spec_multiplier_extremes_accepted(multiplier):
    BlockSpec(width_multiplier=multiplier)


@pytest.mark.parametrize("multiplier", [0.09, 9.51])
def test_block_spec_multiplier_out_of_range_rejected(multiplier):
    with pytest.raises(ValidationError):
        BlockSpec(width_multiplier=multiplier)


def test_block_spec_five_lines_rejected():
    with pytest.raises(ValidationError):
        BlockSpec(lines=["A", "B", "C", "D", "E"])


def test_block_spec_four_lines_accepted():
    BlockSpec(lines=["A", "B", "C", "D"])


def test_block_spec_empty_lines_list_accepted():
    BlockSpec(lines=[])


def test_params_zero_blocks_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[], block_length_mm=10.0)


def test_params_fifty_blocks_accepted():
    DividedBlocksParams(blocks=[BlockSpec() for _ in range(50)], block_length_mm=1.0)


def test_params_fifty_one_blocks_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[BlockSpec() for _ in range(51)], block_length_mm=1.0)


def test_params_both_lengths_set_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=10.0, total_length_mm=20.0)


def test_params_neither_length_set_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[BlockSpec()])


def test_params_block_length_only_accepted():
    DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=10.0)


def test_params_total_length_only_accepted():
    DividedBlocksParams(blocks=[BlockSpec()], total_length_mm=10.0)


def test_params_unknown_font_family_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=10.0, font_family="Comic Sans")


def test_params_font_size_px_out_of_range_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=10.0, font_size_px=200)


def test_params_negative_padding_rejected():
    with pytest.raises(ValidationError):
        DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=10.0, padding_mm=-1.0)


def test_params_defaults():
    p = DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=10.0)
    assert p.separator == Separator.LINE
    assert p.orientation == Orientation.HORIZONTAL
    assert p.reverse is False
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.font_size_px is None
    assert p.padding_mm == 1.0


# --- 2. Pure math: layout_blocks ----------------------------------------
#
# Every expected px value below is independently hand-derived from
# mm_to_dots' Decimal/round-half-up formula (verified by a standalone
# probe script, not by reading divided_blocks.py's source) -- see the
# module docstring.


def test_single_block_exact_width():
    params = DividedBlocksParams(blocks=[BlockSpec(lines=["X"])], block_length_mm=24.0)
    layouts = layout_blocks(params, _tape(24))
    assert layouts == [BlockLayout(x_px=0, width_px=mm_to_dots(24.0))]
    assert mm_to_dots(24.0) == 170


def test_equal_blocks_widths_sum_to_total_and_are_near_ideal():
    # 4 blocks x 15mm each -> total 60mm; hand-derived boundaries_px
    # [0, 106, 213, 319, 425] -> widths [106, 107, 106, 106].
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=[f"B{i}"]) for i in range(4)], block_length_mm=15.0
    )
    layouts = layout_blocks(params, _tape(24))
    assert [layout.width_px for layout in layouts] == [106, 107, 106, 106]
    assert [layout.x_px for layout in layouts] == [0, 106, 213, 319]
    assert sum(layout.width_px for layout in layouts) == mm_to_dots(60.0) == 425


def test_multiplier_extremes_produce_proportional_widths():
    # 2 blocks, multipliers 0.1 and 9.5, block_length_mm=10.0 (kept large
    # enough that the 0.1-multiplier block still clears the 4px minimum
    # block width -- see the zero-width-floor tests below) ->
    # boundaries_mm [0, 1.0, 96.0] -> boundaries_px [0, 7, 680].
    params = DividedBlocksParams(
        blocks=[
            BlockSpec(lines=["A"], width_multiplier=0.1),
            BlockSpec(lines=["B"], width_multiplier=9.5),
        ],
        block_length_mm=10.0,
    )
    layouts = layout_blocks(params, _tape(24))
    assert layouts == [BlockLayout(x_px=0, width_px=7), BlockLayout(x_px=7, width_px=673)]


def test_total_length_mm_division_with_mixed_multipliers():
    # 6 blocks, multipliers [1,1,2,1,1,1], total_length_mm=84.0 ->
    # boundaries_px [0, 85, 170, 340, 425, 510, 595] -> widths
    # [85, 85, 170, 85, 85, 85] (the x2 block is exactly double).
    params = DividedBlocksParams(
        blocks=[
            BlockSpec(lines=[str(i)], width_multiplier=m) for i, m in enumerate([1, 1, 2, 1, 1, 1])
        ],
        total_length_mm=84.0,
    )
    layouts = layout_blocks(params, _tape(12))
    assert [layout.width_px for layout in layouts] == [85, 85, 170, 85, 85, 85]
    assert sum(layout.width_px for layout in layouts) == mm_to_dots(84.0) == 595


def test_cumulative_rounding_drift_50_blocks():
    # 50 blocks x 3.7mm -> total exactly mm_to_dots(185.0); each block
    # within +-1px of the ideal 3.7mm (ideal ~= 26.22px).
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=[str(i)]) for i in range(50)], block_length_mm=3.7
    )
    layouts = layout_blocks(params, _tape(24))
    assert sum(layout.width_px for layout in layouts) == mm_to_dots(185.0) == 1311
    ideal_px = mm_to_dots(3.7)
    for layout in layouts:
        assert abs(layout.width_px - ideal_px) <= 1
    assert {layout.width_px for layout in layouts} == {26, 27}


def test_reverse_false_positions_left_to_right_in_input_order():
    # 3 blocks, multipliers [1,2,3], block_length_mm=10.0 ->
    # boundaries_px [0, 71, 213, 425] -> widths [71, 142, 212].
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=[str(i)], width_multiplier=m) for i, m in enumerate([1, 2, 3])],
        block_length_mm=10.0,
    )
    layouts = layout_blocks(params, _tape(24))
    assert layouts == [
        BlockLayout(x_px=0, width_px=71),
        BlockLayout(x_px=71, width_px=142),
        BlockLayout(x_px=213, width_px=212),
    ]


def test_reverse_true_block_0_rendered_rightmost_but_indexed_by_input_order():
    # Same params as above with reverse=True: display order is [2,1,0], so
    # hand-derived boundaries_px [0, 213, 354, 425] map back to input index
    # as {2: (0,213), 1: (213,141), 0: (354,71)}.
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=[str(i)], width_multiplier=m) for i, m in enumerate([1, 2, 3])],
        block_length_mm=10.0,
        reverse=True,
    )
    layouts = layout_blocks(params, _tape(24))
    assert layouts[0] == BlockLayout(x_px=354, width_px=71)
    assert layouts[1] == BlockLayout(x_px=213, width_px=141)
    assert layouts[2] == BlockLayout(x_px=0, width_px=213)
    # block 0 is rightmost: its x_px is the largest, and x_px + width_px
    # reaches the full label width.
    forward_params = params.model_copy(update={"reverse": False})
    total_px = sum(layout.width_px for layout in layout_blocks(forward_params, _tape(24)))
    assert layouts[0].x_px + layouts[0].width_px == total_px


def test_reverse_does_not_change_per_block_multiset_of_widths_much():
    # Reversing changes WHERE rounding error lands (rule 2 note in
    # layout_blocks' docstring) but the total must still be exact both ways.
    params_fwd = DividedBlocksParams(
        blocks=[BlockSpec(width_multiplier=m) for m in [1, 2, 3]], block_length_mm=10.0
    )
    params_rev = params_fwd.model_copy(update={"reverse": True})
    total_fwd = sum(layout.width_px for layout in layout_blocks(params_fwd, _tape(24)))
    total_rev = sum(layout.width_px for layout in layout_blocks(params_rev, _tape(24)))
    assert total_fwd == total_rev == mm_to_dots(60.0)


def test_total_below_min_label_mm_raises():
    params = DividedBlocksParams(blocks=[BlockSpec()], block_length_mm=1.0)
    # Message uses str(total_mm), not a fixed-precision format -- Python's
    # shortest round-tripping float repr, so it names the value exactly
    # rather than rounding it to look deceptively close to the boundary
    # (see the near-miss precision test further down).
    with pytest.raises(ValueError, match=r"1\.0mm"):
        layout_blocks(params, _tape(24))


def test_total_above_tape_max_length_mm_raises():
    params = DividedBlocksParams(blocks=[BlockSpec(), BlockSpec()], block_length_mm=600.0)
    with pytest.raises(ValueError, match=r"1200\.0mm"):
        layout_blocks(params, _tape(24))  # tze max_length_mm == 1000.0


def test_length_error_message_shows_near_miss_precision_not_rounded():
    # 50 blocks x 0.08788mm each: total_mm is a hair below MIN_LABEL_MM
    # (4.4) but NOT exactly 4.4 -- a fixed :.3f format would round this to
    # "4.394mm" (fine here) but the point being guarded is that the
    # message must reflect the ACTUAL float, not a lossy rounding of it,
    # so a near-miss can never accidentally print as if it were exactly on
    # the boundary. str(total_mm) (Python's shortest round-tripping float
    # repr) guarantees that regardless of how close to a "clean" decimal
    # the underlying float lands.
    per_block_mm = 4.399999999 / 50
    params = DividedBlocksParams(
        blocks=[BlockSpec() for _ in range(50)], block_length_mm=per_block_mm
    )
    total_mm = per_block_mm * 50
    assert total_mm != 4.4  # the float genuinely isn't the clean boundary value
    with pytest.raises(ValueError, match=rf"{total_mm}mm"):
        layout_blocks(params, _tape(24))


# --- 2b. Pure math: minimum block width floor ----------------------------


def test_zero_width_block_raises_naming_index_and_width():
    # 2 blocks, multipliers [0.1, 9.5], block_length_mm=1.0 -> block 0's
    # width is mm_to_dots(0.1mm) == 1px, below the 4px floor, even though
    # the total (9.6mm) comfortably clears MIN_LABEL_MM.
    params = DividedBlocksParams(
        blocks=[
            BlockSpec(width_multiplier=0.1),
            BlockSpec(width_multiplier=9.5),
        ],
        block_length_mm=1.0,
    )
    with pytest.raises(ValueError, match=r"block 0.*1px"):
        layout_blocks(params, _tape(24))


def test_block_width_exactly_at_floor_is_accepted():
    # Sanity check the floor is `< 4px`, not `<= 4px`: block_length_mm=0.55
    # for a single default-multiplier block -> mm_to_dots(0.55) == 4px
    # exactly, total_mm == 0.55 which is below MIN_LABEL_MM by itself, so
    # pair it with a second larger block to keep the total valid while
    # keeping the first block's own width pinned at exactly 4px.
    params = DividedBlocksParams(
        blocks=[BlockSpec(width_multiplier=0.55), BlockSpec(width_multiplier=9.0)],
        block_length_mm=1.0,
    )
    layouts = layout_blocks(params, _tape(24))
    assert layouts[0].width_px == 4


# --- 3. Separator geometry: bitmap-level pixel asserts, 2-block label ---
#
# 2 blocks x 12mm each, tape 24mm (print_dots=128) -> inner boundary at
# px 85 (hand-derived: mm_to_dots(12.0) == 85), total width 170px.


def _two_block_params(separator: Separator) -> DividedBlocksParams:
    return DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"]), BlockSpec(lines=["B"])],
        block_length_mm=12.0,
        separator=separator,
        font_size_px=10,  # keep text small/away from the boundary column
    )


def test_separator_line_full_height_1px_column():
    label = render_divided_blocks(_two_block_params(Separator.LINE), _tape(24))
    assert label.width_px == 170
    img = rasterize(label)
    for y in (0, 1, 63, 64, 126, 127):
        assert _ink(img, 85, y), f"LINE separator column should be ink at y={y}"
    # Only 1px wide: the neighboring columns are not part of the separator.
    assert not _ink(img, 83, 64)
    assert not _ink(img, 87, 64)


def test_separator_bold_is_3px_wide_full_height():
    label = render_divided_blocks(_two_block_params(Separator.BOLD), _tape(24))
    img = rasterize(label)
    for x in (84, 85, 86):
        for y in (0, 64, 127):
            assert _ink(img, x, y), f"BOLD separator should be ink at ({x},{y})"
    assert not _ink(img, 83, 64)
    assert not _ink(img, 87, 64)


def test_separator_tic_touches_only_top_and_bottom_15_percent():
    # print_dots=128 -> seg_h = round(128*0.15) == 19: rows [0,18] and
    # [109,127] are ink, rows in between are not.
    label = render_divided_blocks(_two_block_params(Separator.TIC), _tape(24))
    img = rasterize(label)
    assert _ink(img, 85, 0)
    assert _ink(img, 85, 18)
    assert not _ink(img, 85, 19)
    assert not _ink(img, 85, 64)  # middle
    assert not _ink(img, 85, 108)
    assert _ink(img, 85, 109)
    assert _ink(img, 85, 127)


def test_separator_tic_extent_rounds_half_up_at_exact_tie():
    # A 12mm tape has print_dots == 70 -> 70*0.15 == 10.5 EXACTLY, a genuine
    # rounding tie. The repo's own mm_to_dots convention is Decimal
    # ROUND_HALF_UP (round-half-away-from-zero), which resolves this tie to
    # 11 -- Python's builtin round() would instead tie to EVEN (banker's
    # rounding) and give 10, silently disagreeing with the rest of the
    # codebase's pixel math. 2 blocks x 6mm each on this tape -> boundary
    # at mm_to_dots(6.0) == 43px (hand-derived, independent of this
    # module).
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"]), BlockSpec(lines=["B"])],
        block_length_mm=6.0,
        separator=Separator.TIC,
        font_size_px=8,
    )
    label = render_divided_blocks(params, _tape(12))
    img = rasterize(label)
    assert _ink(img, 43, 10), "row 10 (0-indexed) should be the last ink row of an 11-row tic"
    assert not _ink(img, 43, 11), "row 11 should already be blank under ROUND_HALF_UP (seg_h=11)"
    assert not _ink(img, 43, 58)
    assert _ink(img, 43, 59), "bottom tic should start at row 59 (70-11)"


def test_separator_dash_has_4px_on_4px_off_gaps():
    label = render_divided_blocks(_two_block_params(Separator.DASH), _tape(24))
    img = rasterize(label)
    # on: [0,3], off: [4,7], on: [8,11], off: [12,15] ...
    for y in (0, 3, 8, 11):
        assert _ink(img, 85, y), f"DASH should be ink at y={y}"
    for y in (4, 7, 12, 15):
        assert not _ink(img, 85, y), f"DASH should be a gap at y={y}"


def test_separator_none_draws_no_boundary_ink():
    label = render_divided_blocks(_two_block_params(Separator.NONE), _tape(24))
    img = rasterize(label)
    for y in range(0, 128, 7):
        assert not _ink(img, 85, y)


def test_separator_frame_adds_perimeter_border_and_inner_line():
    label = render_divided_blocks(_two_block_params(Separator.FRAME), _tape(24))
    img = rasterize(label)
    # inner boundary: same as LINE
    assert _ink(img, 85, 64)
    # perimeter: top row, bottom row, left col, right col all ink
    for x in (0, 84, 169):
        assert _ink(img, x, 0), f"FRAME top border should be ink at x={x}"
        assert _ink(img, x, 127), f"FRAME bottom border should be ink at x={x}"
    for y in (0, 64, 127):
        assert _ink(img, 0, y), f"FRAME left border should be ink at y={y}"
        assert _ink(img, 169, y), f"FRAME right border should be ink at y={y}"
    # interior (not on any border/boundary) is not ink
    assert not _ink(img, 40, 30)


# --- 4. Orientation ------------------------------------------------------


def test_vertical_rotates_90_clockwise():
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["X"])], block_length_mm=20.0, orientation=Orientation.VERTICAL
    )
    label = render_divided_blocks(params, _tape(24))
    assert "rotate(90," in label.svg
    assert "rotate(-90," not in label.svg


def test_backbone_rotates_90_counter_clockwise():
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["X"])], block_length_mm=20.0, orientation=Orientation.BACKBONE
    )
    label = render_divided_blocks(params, _tape(24))
    assert "rotate(-90," in label.svg


def test_horizontal_has_no_rotation():
    params = DividedBlocksParams(blocks=[BlockSpec(lines=["X"])], block_length_mm=20.0)
    label = render_divided_blocks(params, _tape(24))
    assert "rotate(" not in label.svg


def test_vertical_fits_long_word_that_horizontal_cannot():
    # A narrow-but-tall single block: 8mm long on a 24mm tape
    # (print_dots=128). A 10-char word is cramped horizontally (little
    # width to work with) but has much more room to work with once
    # rotated (the fit-width budget becomes ~print_height instead of
    # ~block_width) -- this is the width/height swap in rule 6.
    horizontal = DividedBlocksParams(
        blocks=[BlockSpec(lines=["PATCHPANEL"])],
        block_length_mm=8.0,
        orientation=Orientation.HORIZONTAL,
    )
    vertical = horizontal.model_copy(update={"orientation": Orientation.VERTICAL})
    tape = _tape(24)

    h_label = render_divided_blocks(horizontal, tape)
    v_label = render_divided_blocks(vertical, tape)

    assert any(w.code == "text_cramped" for w in h_label.warnings)
    assert not any(w.code == "text_cramped" for w in v_label.warnings)


# --- 5. Text content: empty blocks render without error ------------------


@pytest.mark.parametrize("lines", [[], [""], ["", ""]])
def test_empty_block_lines_render_without_error(lines):
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=lines), BlockSpec(lines=["OK"])], block_length_mm=20.0
    )
    label = render_divided_blocks(params, _tape(24))
    assert label.svg  # renders successfully, no exception


# --- 6. Warnings: object_id carries block index --------------------------


def test_cramped_block_warns_with_its_own_object_id_others_unaffected():
    tiny_tape = _tape(3.5)  # print_dots == 24, very little vertical room
    params = DividedBlocksParams(
        blocks=[
            BlockSpec(lines=["A", "B", "C", "D"]),  # 4 lines: forced to the floor
            BlockSpec(lines=["X"]),  # 1 line: comfortably fits at the shared size
        ],
        block_length_mm=20.0,
    )
    label = render_divided_blocks(params, tiny_tape)
    cramped = [w for w in label.warnings if w.code == "text_cramped"]
    assert {w.object_id for w in cramped} == {"block-0"}
    assert all(w.severity == "warning" for w in cramped)


def test_normal_case_has_no_warnings():
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"]), BlockSpec(lines=["B"])], block_length_mm=20.0
    )
    label = render_divided_blocks(params, _tape(24))
    assert label.warnings == []


def test_explicit_font_size_clamped_triggers_global_font_clamped_warning():
    tiny_tape = _tape(3.5)  # print_dots == 24
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"])], block_length_mm=20.0, font_size_px=128
    )
    label = render_divided_blocks(params, tiny_tape)
    clamped = [w for w in label.warnings if w.code == "font_clamped"]
    assert len(clamped) == 1
    assert clamped[0].object_id is None


def test_explicit_oversized_font_warns_text_truncated_per_block_and_clips():
    # Reproduces the reported bug: an explicit font_size_px far too big for
    # each block's own width (3 blocks x 10mm on a 24mm tape ->
    # boundaries_px [0, 71, 142, 213], avail width per block ==
    # 71 - 2*mm_to_dots(1.0) == 71 - 14 == 57px; an 8-char line at 48px is
    # far wider than that) used to render an illegible smear crossing
    # every block boundary with warnings == []. Now: a text_truncated
    # warning per block, AND the rendered ink never crosses into a
    # neighboring block.
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["ABCDEFGH"]) for _ in range(3)],
        block_length_mm=10.0,
        font_size_px=48,
        separator=Separator.NONE,
    )
    tape = _tape(24)
    label = render_divided_blocks(params, tape)

    truncated = [w for w in label.warnings if w.code == "text_truncated"]
    assert {w.object_id for w in truncated} == {"block-0", "block-1", "block-2"}
    assert all(w.severity == "warning" for w in truncated)
    assert "clipPath" in label.svg

    layouts = layout_blocks(params, tape)
    img = rasterize(label)
    # No ink within a padding-width margin (7px, mm_to_dots(1.0)) of any
    # inner boundary -- proves clipping actually confines each block's
    # (badly overflowing) text to its own box instead of bleeding across
    # the boundary into a neighbor.
    for boundary_x in (layouts[1].x_px, layouts[2].x_px):
        for x in range(boundary_x - 6, boundary_x + 6):
            for y in range(0, tape.print_dots, 8):
                assert not _ink(img, x, y), f"ink bled across boundary at x={x}, y={y}"


def test_auto_mode_floor_fallback_still_clips_no_cross_block_bleed():
    # Reproduces the report's second finding: fit_font_size's min_px
    # FALLBACK (when nothing in [min_px, max_px] actually satisfies the
    # fit) used to paint text at the floor size with no clip, which can
    # still overflow a very narrow block and bleed into its neighbors --
    # auto mode's existing text_cramped warning flags that something's
    # wrong, but didn't used to stop the bleed. 3 narrow blocks (4mm each
    # -> ~28px wide, avail width ~14px after padding) with a wide word
    # forces every block to the 6px floor.
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["WWWWWWWWWW"]) for _ in range(3)],
        block_length_mm=4.0,
        separator=Separator.NONE,
    )
    tape = _tape(24)
    label = render_divided_blocks(params, tape)

    assert any(w.code == "text_cramped" for w in label.warnings)

    layouts = layout_blocks(params, tape)
    img = rasterize(label)
    for boundary_x in (layouts[1].x_px, layouts[2].x_px):
        for x in range(boundary_x - 6, boundary_x + 6):
            for y in range(0, tape.print_dots, 8):
                assert not _ink(img, x, y), f"ink bled across boundary at x={x}, y={y}"


def test_explicit_font_size_that_fits_has_no_warning():
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"])], block_length_mm=20.0, font_size_px=10
    )
    label = render_divided_blocks(params, _tape(24))
    assert label.warnings == []


# --- 7. Determinism --------------------------------------------------------


def test_render_is_deterministic_svg():
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"]), BlockSpec(lines=["B"])], block_length_mm=20.0
    )
    tape = _tape(24)
    svg1 = render_divided_blocks(params, tape).svg
    svg2 = render_divided_blocks(params, tape).svg
    assert svg1 == svg2


def test_render_twice_is_byte_identical_png():
    params = DividedBlocksParams(
        blocks=[BlockSpec(lines=["A"]), BlockSpec(lines=["B"])], block_length_mm=20.0
    )
    tape = _tape(24)

    def _png():
        label = render_divided_blocks(params, tape)
        return preview_png(rasterize(label), scale=GOLDEN_SCALE)

    assert _png() == _png()


# --- 8. Golden PNGs: byte-locked against committed files -----------------
#
# Fixture definitions live in golden_fixtures.py (shared with
# scripts/regen_goldens.py) -- visually inspect any new/changed golden
# before committing it (see task-2.1-report.md for descriptions).


def _render_preview_png(params: DividedBlocksParams, tape) -> bytes:
    label = render_divided_blocks(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", DIVIDED_BLOCKS_FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    png = _render_preview_png(fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden
