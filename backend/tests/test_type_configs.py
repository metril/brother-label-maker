"""Tests for the task 2.2 label types: patch_panel, punch_down, faceplate.

Each is a THIN config over divided_blocks.py's layout engine (task 2.1) --
these tests deliberately do NOT re-derive layout math (block boundaries,
separator geometry, font fitting): that's already covered by
test_divided_blocks.py. What's tested here is each type's own contract: its
Params model's validation ranges, and that it builds the DividedBlocksParams
its config module's docstring promises (asserted via each module's own
`_to_engine_params` helper, plus layout_blocks/render_divided_blocks where a
concrete geometric assertion is cheap and worth pinning) -- not "whatever
the code happens to produce".
"""

from pathlib import Path

import pytest
from golden_fixtures import GOLDEN_SCALE, TYPE_CONFIG_FIXTURES
from pydantic import ValidationError

from labelmaker.driver.geometry import mm_to_dots
from labelmaker.render.document import Tape
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.divided_blocks import Orientation, Separator, layout_blocks
from labelmaker.render.types.faceplate import BlockText as FaceplateBlockText
from labelmaker.render.types.faceplate import FaceplateParams, FaceplateRenderer
from labelmaker.render.types.faceplate import _to_engine_params as faceplate_engine_params
from labelmaker.render.types.patch_panel import BlockText as PatchPanelBlockText
from labelmaker.render.types.patch_panel import PatchPanelParams, PatchPanelRenderer
from labelmaker.render.types.patch_panel import _to_engine_params as patch_panel_engine_params
from labelmaker.render.types.punch_down import PunchDownParams, PunchDownRenderer
from labelmaker.render.types.punch_down import _to_engine_params as punch_down_engine_params

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


# --- 0. Registration: all three registered under "network" -----------------


def test_all_three_types_registered_under_network_category():
    by_type = {t.type: t for t in list_types()}
    assert by_type.keys() >= {"patch_panel", "punch_down", "faceplate"}
    for type_name in ("patch_panel", "punch_down", "faceplate"):
        assert by_type[type_name].category == "network"
        assert by_type[type_name].min_tape_mm is None


def test_get_renderer_returns_expected_renderer_instances():
    assert isinstance(get_renderer("patch_panel"), PatchPanelRenderer)
    assert isinstance(get_renderer("punch_down"), PunchDownRenderer)
    assert isinstance(get_renderer("faceplate"), FaceplateRenderer)


# --- 1. patch_panel: Params validation --------------------------------------


def test_patch_panel_defaults():
    p = PatchPanelParams(blocks=[PatchPanelBlockText()])
    assert p.block_length_mm == 15.0
    assert p.separator == Separator.LINE
    assert p.orientation == Orientation.HORIZONTAL
    assert p.reverse is False
    assert p.multipliers is None
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.font_size_px is None
    assert p.padding_mm == 1.0


@pytest.mark.parametrize("length", [5.0, 300.0])
def test_patch_panel_block_length_mm_boundaries_accepted(length):
    PatchPanelParams(blocks=[PatchPanelBlockText()], block_length_mm=length)


@pytest.mark.parametrize("length", [4.9, 300.1])
def test_patch_panel_block_length_mm_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        PatchPanelParams(blocks=[PatchPanelBlockText()], block_length_mm=length)


def test_patch_panel_zero_blocks_rejected():
    with pytest.raises(ValidationError):
        PatchPanelParams(blocks=[])


def test_patch_panel_fifty_blocks_accepted():
    PatchPanelParams(blocks=[PatchPanelBlockText() for _ in range(50)])


def test_patch_panel_fifty_one_blocks_rejected():
    with pytest.raises(ValidationError):
        PatchPanelParams(blocks=[PatchPanelBlockText() for _ in range(51)])


def test_patch_panel_block_text_three_lines_rejected():
    with pytest.raises(ValidationError):
        PatchPanelBlockText(lines=["A", "B", "C"])


def test_patch_panel_block_text_two_lines_accepted():
    PatchPanelBlockText(lines=["A", "B"])


def test_patch_panel_block_text_zero_lines_accepted():
    PatchPanelBlockText(lines=[])


def test_patch_panel_multipliers_length_mismatch_rejected():
    with pytest.raises(ValidationError, match="multipliers length"):
        PatchPanelParams(blocks=[PatchPanelBlockText(), PatchPanelBlockText()], multipliers=[1.0])


@pytest.mark.parametrize("multiplier", [0.1, 9.5])
def test_patch_panel_multiplier_extremes_accepted(multiplier):
    PatchPanelParams(blocks=[PatchPanelBlockText()], multipliers=[multiplier])


@pytest.mark.parametrize("multiplier", [0.09, 9.51])
def test_patch_panel_multiplier_out_of_range_rejected(multiplier):
    with pytest.raises(ValidationError):
        PatchPanelParams(blocks=[PatchPanelBlockText()], multipliers=[multiplier])


def test_patch_panel_multipliers_matching_length_accepted():
    PatchPanelParams(blocks=[PatchPanelBlockText(), PatchPanelBlockText()], multipliers=[1.0, 2.0])


# --- 2. patch_panel: delegates to the engine, doesn't reimplement it -------


def test_patch_panel_builds_expected_divided_blocks_params():
    params = PatchPanelParams(
        blocks=[PatchPanelBlockText(lines=[f"P-0{i}"]) for i in range(1, 5)],
        block_length_mm=15.0,
    )
    engine_params = patch_panel_engine_params(params)
    assert engine_params.block_length_mm == 15.0
    assert engine_params.total_length_mm is None
    assert [b.lines for b in engine_params.blocks] == [["P-01"], ["P-02"], ["P-03"], ["P-04"]]
    assert all(b.width_multiplier == 1.0 for b in engine_params.blocks)
    assert engine_params.separator == Separator.LINE
    assert engine_params.orientation == Orientation.HORIZONTAL


def test_patch_panel_4_blocks_15mm_layout_matches_hand_derived_boundaries():
    # Same numbers as test_divided_blocks.py's
    # test_equal_blocks_widths_sum_to_total_and_are_near_ideal: 4 blocks x
    # 15mm -> total 60mm -> widths [106, 107, 106, 106], x_px [0, 106, 213, 319].
    params = PatchPanelParams(
        blocks=[PatchPanelBlockText(lines=[f"P-0{i}"]) for i in range(1, 5)],
        block_length_mm=15.0,
    )
    layouts = layout_blocks(patch_panel_engine_params(params), _tape(24))
    assert [layout.width_px for layout in layouts] == [106, 107, 106, 106]
    assert [layout.x_px for layout in layouts] == [0, 106, 213, 319]


def test_patch_panel_multipliers_forwarded_as_width_multiplier():
    params = PatchPanelParams(
        blocks=[PatchPanelBlockText(), PatchPanelBlockText()],
        multipliers=[0.5, 2.0],
    )
    engine_params = patch_panel_engine_params(params)
    assert [b.width_multiplier for b in engine_params.blocks] == [0.5, 2.0]


def test_patch_panel_reverse_orientation_separator_forwarded():
    params = PatchPanelParams(
        blocks=[PatchPanelBlockText()],
        separator=Separator.TIC,
        orientation=Orientation.VERTICAL,
        reverse=True,
    )
    engine_params = patch_panel_engine_params(params)
    assert engine_params.separator == Separator.TIC
    assert engine_params.orientation == Orientation.VERTICAL
    assert engine_params.reverse is True


def test_patch_panel_font_padding_forwarded_unmodified():
    params = PatchPanelParams(
        blocks=[PatchPanelBlockText()],
        font_family="JetBrains Mono",
        bold=True,
        font_size_px=20,
        padding_mm=3.0,
    )
    engine_params = patch_panel_engine_params(params)
    assert engine_params.font_family == "JetBrains Mono"
    assert engine_params.bold is True
    assert engine_params.font_size_px == 20
    assert engine_params.padding_mm == 3.0


def test_patch_panel_render_height_equals_print_dots():
    params = PatchPanelParams(blocks=[PatchPanelBlockText(lines=["A"])])
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = PatchPanelRenderer().render(params, _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 3. punch_down: Params validation ---------------------------------------


def test_punch_down_defaults():
    p = PunchDownParams()
    assert p.module_width_mm == 203.0
    assert p.n_blocks == 6
    assert p.block_type == "4-pair"
    assert p.sequence == "horizontal"
    assert p.start_value == 1
    assert p.extra_lines == []
    assert p.font_family == "Inter"
    assert p.padding_mm == 1.0


@pytest.mark.parametrize("width", [50.0, 300.0])
def test_punch_down_module_width_mm_boundaries_accepted(width):
    PunchDownParams(module_width_mm=width)


@pytest.mark.parametrize("width", [49.9, 300.1])
def test_punch_down_module_width_mm_out_of_range_rejected(width):
    with pytest.raises(ValidationError):
        PunchDownParams(module_width_mm=width)


def test_punch_down_n_blocks_boundaries_accepted():
    PunchDownParams(n_blocks=1)
    PunchDownParams(n_blocks=50)


def test_punch_down_n_blocks_out_of_range_rejected():
    with pytest.raises(ValidationError):
        PunchDownParams(n_blocks=0)
    with pytest.raises(ValidationError):
        PunchDownParams(n_blocks=51)


@pytest.mark.parametrize("block_type", ["4-pair", "3-pair", "2-pair", "5-pair", "blank"])
def test_punch_down_block_type_all_valid_values_accepted(block_type):
    PunchDownParams(block_type=block_type)


def test_punch_down_invalid_block_type_rejected():
    with pytest.raises(ValidationError):
        PunchDownParams(block_type="6-pair")


@pytest.mark.parametrize("sequence", ["none", "horizontal", "backbone"])
def test_punch_down_sequence_all_valid_values_accepted(sequence):
    PunchDownParams(sequence=sequence)


def test_punch_down_invalid_sequence_rejected():
    with pytest.raises(ValidationError):
        PunchDownParams(sequence="vertical")


@pytest.mark.parametrize("value", [1, 99999])
def test_punch_down_start_value_boundaries_accepted(value):
    PunchDownParams(start_value=value)


@pytest.mark.parametrize("value", [0, 100000])
def test_punch_down_start_value_out_of_range_rejected(value):
    with pytest.raises(ValidationError):
        PunchDownParams(start_value=value)


def test_punch_down_extra_lines_two_entries_rejected():
    with pytest.raises(ValidationError):
        PunchDownParams(extra_lines=["A", "B"])


def test_punch_down_extra_lines_one_entry_accepted():
    PunchDownParams(extra_lines=["CAT6"])


# --- 4. punch_down: numbering semantics -------------------------------------


def test_punch_down_4pair_start_1_six_blocks_numbering():
    params = PunchDownParams(block_type="4-pair", sequence="horizontal", start_value=1, n_blocks=6)
    engine_params = punch_down_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [
        ["1"],
        ["5"],
        ["9"],
        ["13"],
        ["17"],
        ["21"],
    ]


@pytest.mark.parametrize("block_type,pair_count", [("2-pair", 2), ("3-pair", 3), ("5-pair", 5)])
def test_punch_down_numbering_uses_pair_count_from_block_type(block_type, pair_count):
    params = PunchDownParams(block_type=block_type, start_value=10, n_blocks=3)
    engine_params = punch_down_engine_params(params)
    assert [b.lines[0] for b in engine_params.blocks] == [
        str(10 + i * pair_count) for i in range(3)
    ]


def test_punch_down_blank_block_type_produces_no_numbers():
    params = PunchDownParams(block_type="blank", n_blocks=4)
    engine_params = punch_down_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [[], [], [], []]


def test_punch_down_blank_with_extra_lines_shows_only_extra_lines():
    params = PunchDownParams(block_type="blank", n_blocks=2, extra_lines=["SPARE"])
    engine_params = punch_down_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [["SPARE"], ["SPARE"]]


def test_punch_down_sequence_none_produces_no_numbers():
    params = PunchDownParams(sequence="none", n_blocks=3)
    engine_params = punch_down_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [[], [], []]


def test_punch_down_sequence_none_with_extra_lines_shows_only_extra_lines():
    params = PunchDownParams(sequence="none", n_blocks=2, extra_lines=["SPARE"])
    engine_params = punch_down_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [["SPARE"], ["SPARE"]]


def test_punch_down_extra_line_appended_after_number():
    params = PunchDownParams(n_blocks=2, extra_lines=["CAT6"])
    engine_params = punch_down_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [["1", "CAT6"], ["5", "CAT6"]]


# --- 5. punch_down: sequence doubles as engine orientation ------------------


def test_punch_down_sequence_horizontal_maps_to_orientation_horizontal():
    engine_params = punch_down_engine_params(PunchDownParams(sequence="horizontal"))
    assert engine_params.orientation == Orientation.HORIZONTAL


def test_punch_down_sequence_backbone_maps_to_orientation_backbone():
    engine_params = punch_down_engine_params(PunchDownParams(sequence="backbone"))
    assert engine_params.orientation == Orientation.BACKBONE


def test_punch_down_sequence_none_maps_to_orientation_horizontal():
    engine_params = punch_down_engine_params(PunchDownParams(sequence="none"))
    assert engine_params.orientation == Orientation.HORIZONTAL


def test_punch_down_has_no_separator_param_fixed_to_line():
    assert "separator" not in PunchDownParams.model_fields
    engine_params = punch_down_engine_params(PunchDownParams())
    assert engine_params.separator == Separator.LINE


def test_punch_down_module_width_mm_forwarded_as_total_length_mm():
    engine_params = punch_down_engine_params(PunchDownParams(module_width_mm=150.0))
    assert engine_params.total_length_mm == 150.0
    assert engine_params.block_length_mm is None


def test_punch_down_render_height_equals_print_dots():
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = PunchDownRenderer().render(PunchDownParams(), _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 6. faceplate: Params validation -----------------------------------------


def test_faceplate_defaults():
    p = FaceplateParams()
    assert p.total_length_mm == 70.0
    assert p.n_blocks == 2
    assert len(p.blocks) == 2
    assert p.separator == Separator.NONE
    assert p.orientation == Orientation.HORIZONTAL


@pytest.mark.parametrize("length", [5.0, 1000.0])
def test_faceplate_total_length_mm_boundaries_accepted(length):
    FaceplateParams(total_length_mm=length)


@pytest.mark.parametrize("length", [4.9, 1000.1])
def test_faceplate_total_length_mm_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        FaceplateParams(total_length_mm=length)


def test_faceplate_n_blocks_boundaries_accepted():
    FaceplateParams(n_blocks=1)
    FaceplateParams(n_blocks=50)


def test_faceplate_n_blocks_out_of_range_rejected():
    with pytest.raises(ValidationError):
        FaceplateParams(n_blocks=0)
    with pytest.raises(ValidationError):
        FaceplateParams(n_blocks=51)


def test_faceplate_fewer_blocks_than_n_blocks_padded_with_blank():
    params = FaceplateParams(n_blocks=3, blocks=[FaceplateBlockText(lines=["OFFICE 1"])])
    assert [b.lines for b in params.blocks] == [["OFFICE 1"], [""], [""]]


def test_faceplate_blocks_matching_n_blocks_unchanged():
    params = FaceplateParams(
        n_blocks=2,
        blocks=[FaceplateBlockText(lines=["OFFICE 1"]), FaceplateBlockText(lines=["OFFICE 2"])],
    )
    assert [b.lines for b in params.blocks] == [["OFFICE 1"], ["OFFICE 2"]]


def test_faceplate_more_blocks_than_n_blocks_rejected():
    with pytest.raises(ValidationError, match="exceeds n_blocks"):
        FaceplateParams(
            n_blocks=1,
            blocks=[FaceplateBlockText(lines=["A"]), FaceplateBlockText(lines=["B"])],
        )


def test_faceplate_no_blocks_given_all_padded_blank():
    params = FaceplateParams(n_blocks=2)
    assert [b.lines for b in params.blocks] == [[""], [""]]


# --- 7. faceplate: delegates to the engine (even division, total-length mode) --


def test_faceplate_builds_expected_divided_blocks_params():
    params = FaceplateParams(
        total_length_mm=70.0,
        n_blocks=2,
        blocks=[
            FaceplateBlockText(lines=["OFFICE 1"]),
            FaceplateBlockText(lines=["OFFICE 2"]),
        ],
    )
    engine_params = faceplate_engine_params(params)
    assert engine_params.total_length_mm == 70.0
    assert engine_params.block_length_mm is None
    assert [b.lines for b in engine_params.blocks] == [["OFFICE 1"], ["OFFICE 2"]]
    assert engine_params.separator == Separator.NONE
    assert engine_params.orientation == Orientation.HORIZONTAL


def test_faceplate_even_division_layout():
    # total_length_mm=70, 2 equal blocks -> boundary at mm_to_dots(35.0).
    params = FaceplateParams(
        total_length_mm=70.0,
        n_blocks=2,
        blocks=[FaceplateBlockText(lines=["A"]), FaceplateBlockText(lines=["B"])],
    )
    layouts = layout_blocks(faceplate_engine_params(params), _tape(24))
    assert layouts[0].x_px == 0
    assert layouts[0].width_px == mm_to_dots(35.0)
    assert layouts[1].x_px == mm_to_dots(35.0)


def test_faceplate_render_height_equals_print_dots():
    params = FaceplateParams(n_blocks=2)
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = FaceplateRenderer().render(params, _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 8. Schema fidelity: bounds live in Field(...), not validator bodies ---
#
# A future params_schema-driven form generator (2.10) can only see what
# JSON Schema exposes -- a `ge`/`le` on the Field() itself, not a
# raise-inside-a-validator-function. Every numeric bound cheap enough to
# express declaratively must be a Field constraint (see each module's
# docstring), and this is pinned here so a future edit that quietly moves a
# bound back into a validator body regresses loudly.


@pytest.mark.parametrize(
    "params_cls", [PatchPanelParams, PunchDownParams, FaceplateParams], ids=lambda c: c.__name__
)
def test_padding_mm_schema_carries_minimum_zero(params_cls):
    props = params_cls.model_json_schema()["properties"]
    assert props["padding_mm"]["minimum"] == 0


def test_patch_panel_multipliers_schema_items_carry_minimum_and_maximum():
    props = PatchPanelParams.model_json_schema()["properties"]
    # multipliers: list[...] | None -> anyOf [array-of-bounded-number, null].
    array_variant = next(v for v in props["multipliers"]["anyOf"] if v.get("type") == "array")
    assert array_variant["items"]["minimum"] == 0.1
    assert array_variant["items"]["maximum"] == 9.5


def test_faceplate_blocks_schema_has_max_length_50_matching_patch_panel():
    faceplate_props = FaceplateParams.model_json_schema()["properties"]
    patch_panel_props = PatchPanelParams.model_json_schema()["properties"]
    assert faceplate_props["blocks"]["maxItems"] == 50
    assert patch_panel_props["blocks"]["maxItems"] == 50


def test_patch_panel_multiplier_out_of_range_error_loc_points_at_the_item():
    # Field-level bounds (not a validator-body loop) give each out-of-range
    # item its own error `loc` -- (multipliers, <index>) -- instead of one
    # opaque message naming the whole list.
    with pytest.raises(ValidationError) as exc_info:
        PatchPanelParams(
            blocks=[PatchPanelBlockText(), PatchPanelBlockText()],
            multipliers=[1.0, 20.0],
        )
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("multipliers", 1) for err in errors)


# --- 8b. build_divided_blocks_params: 422 names the CALLER's type ----------
#
# divided_blocks.py's build_divided_blocks_params re-raises any
# pydantic.ValidationError from the internal DividedBlocksParams
# construction with the caller's own Params class name substituted in --
# so a 422 for e.g. an unvalidated-at-this-layer font_family names
# "PatchPanelParams", not the internal engine type "DividedBlocksParams"
# a caller of the public API was never told about.


@pytest.mark.parametrize(
    "make_bad_params,renderer_cls,expected_name",
    [
        (
            lambda: PatchPanelParams(
                blocks=[PatchPanelBlockText(lines=["A"])], font_family="Comic Sans"
            ),
            PatchPanelRenderer,
            "PatchPanelParams",
        ),
        (
            lambda: PunchDownParams(font_family="Comic Sans"),
            PunchDownRenderer,
            "PunchDownParams",
        ),
        (
            lambda: FaceplateParams(font_family="Comic Sans"),
            FaceplateRenderer,
            "FaceplateParams",
        ),
    ],
)
def test_engine_value_error_names_the_callers_own_type_not_divided_blocks_params(
    make_bad_params, renderer_cls, expected_name
):
    bad_params = make_bad_params()
    with pytest.raises(ValueError) as exc_info:
        renderer_cls().render(bad_params, _tape(24))
    message = str(exc_info.value)
    assert expected_name in message
    assert "DividedBlocksParams" not in message


# --- 9. Golden PNGs: byte-locked against committed files --------------------
#
# Fixture definitions live in golden_fixtures.py (shared with
# scripts/regen_goldens.py) -- visually inspect any new/changed golden
# before committing it (see task-2.2-report.md for descriptions).


def _render_preview_png(renderer, params, tape) -> bytes:
    label = renderer.render(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", TYPE_CONFIG_FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    renderer = get_renderer(fixture.type)
    png = _render_preview_png(renderer, fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden
