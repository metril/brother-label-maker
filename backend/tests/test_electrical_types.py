"""Tests for the task 2.3 label types: terminal_block, breaker_box -- the
product's differentiators (Brother's own software has no equivalent wizard
for either shape, so these modules' own docstrings/Field descriptions ARE
the spec; see their module docstrings).

Like test_type_configs.py (task 2.2), these tests do NOT re-derive
divided_blocks.py's layout math (boundary rounding, separator geometry,
font fitting) -- that's covered by test_divided_blocks.py. What's tested
here is each type's own contract: Params validation ranges, that it builds
the DividedBlocksParams its module docstring promises, and -- the point of
this task -- breaker_box's panel-position numbering arithmetic, hand-derived
independently below (see each test's own comment) rather than just asserting
"whatever the code happens to produce".
"""

from pathlib import Path

import pytest
from golden_fixtures import ELECTRICAL_TYPE_FIXTURES, GOLDEN_SCALE
from pydantic import ValidationError

from labelmaker.driver.geometry import mm_to_dots
from labelmaker.render.document import Tape
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.breaker_box import (
    BreakerBoxParams,
    BreakerBoxRenderer,
    BreakerSpec,
)
from labelmaker.render.types.breaker_box import _to_engine_params as breaker_box_engine_params
from labelmaker.render.types.divided_blocks import Orientation, Separator, layout_blocks
from labelmaker.render.types.terminal_block import TerminalBlockParams, TerminalBlockRenderer
from labelmaker.render.types.terminal_block import _to_engine_params as terminal_block_engine_params

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


# --- 0. Registration: both registered under "electrical" --------------------


def test_both_types_registered_under_electrical_category():
    by_type = {t.type: t for t in list_types()}
    assert by_type.keys() >= {"terminal_block", "breaker_box"}
    for type_name in ("terminal_block", "breaker_box"):
        assert by_type[type_name].category == "electrical"
        assert by_type[type_name].min_tape_mm is None


def test_get_renderer_returns_expected_renderer_instances():
    assert isinstance(get_renderer("terminal_block"), TerminalBlockRenderer)
    assert isinstance(get_renderer("breaker_box"), BreakerBoxRenderer)


# --- 1. terminal_block: Params validation -----------------------------------


def test_terminal_block_defaults():
    p = TerminalBlockParams()
    assert p.pitch_mm == 6.0
    assert p.n_terminals == 12
    assert p.numbering is True
    assert p.start_value == 1
    assert p.step == 1
    assert p.labels == []
    assert p.orientation == "vertical"
    assert p.separator == Separator.LINE
    assert p.font_family == "Inter"
    assert p.bold is False
    assert p.font_size_px is None
    assert p.padding_mm == 1.0


@pytest.mark.parametrize("pitch", [3.0, 50.0])
def test_terminal_block_pitch_mm_boundaries_accepted(pitch):
    TerminalBlockParams(pitch_mm=pitch)


@pytest.mark.parametrize("pitch", [2.9, 50.1])
def test_terminal_block_pitch_mm_out_of_range_rejected(pitch):
    with pytest.raises(ValidationError):
        TerminalBlockParams(pitch_mm=pitch)


def test_terminal_block_n_terminals_boundaries_accepted():
    TerminalBlockParams(n_terminals=1)
    TerminalBlockParams(n_terminals=50)


def test_terminal_block_n_terminals_out_of_range_rejected():
    with pytest.raises(ValidationError):
        TerminalBlockParams(n_terminals=0)
    with pytest.raises(ValidationError):
        TerminalBlockParams(n_terminals=51)


@pytest.mark.parametrize("value", [0, 99999])
def test_terminal_block_start_value_boundaries_accepted(value):
    TerminalBlockParams(start_value=value)


@pytest.mark.parametrize("value", [-1, 100000])
def test_terminal_block_start_value_out_of_range_rejected(value):
    with pytest.raises(ValidationError):
        TerminalBlockParams(start_value=value)


@pytest.mark.parametrize("step", [1, 100])
def test_terminal_block_step_boundaries_accepted(step):
    TerminalBlockParams(step=step)


@pytest.mark.parametrize("step", [0, 101])
def test_terminal_block_step_out_of_range_rejected(step):
    with pytest.raises(ValidationError):
        TerminalBlockParams(step=step)


def test_terminal_block_label_over_20_chars_rejected():
    with pytest.raises(ValidationError):
        TerminalBlockParams(n_terminals=1, labels=["A" * 21])


def test_terminal_block_label_exactly_20_chars_accepted():
    TerminalBlockParams(n_terminals=1, labels=["A" * 20])


def test_terminal_block_labels_exceeding_n_terminals_rejected():
    with pytest.raises(ValidationError, match="labels length"):
        TerminalBlockParams(n_terminals=2, labels=["A", "B", "C"])


def test_terminal_block_labels_matching_n_terminals_accepted():
    TerminalBlockParams(n_terminals=2, labels=["A", "B"])


def test_terminal_block_orientation_rejects_backbone():
    with pytest.raises(ValidationError):
        TerminalBlockParams(orientation="backbone")


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_terminal_block_orientation_valid_values_accepted(orientation):
    TerminalBlockParams(orientation=orientation)


# --- 2. terminal_block: numbering semantics ----------------------------------


def test_terminal_block_numbering_with_step():
    # start_value=10, step=2, 5 terminals -> 10, 12, 14, 16, 18.
    params = TerminalBlockParams(n_terminals=5, start_value=10, step=2)
    engine_params = terminal_block_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [
        ["10"], ["12"], ["14"], ["16"], ["18"],
    ]


def test_terminal_block_labels_override_partial_list():
    # labels=["L1", "L2"] on a 4-terminal strip (start_value=1, step=1
    # defaults): terminals 0-1 take the label text; terminals 2-3 fall
    # through to their OWN number (1 + i*1), not renumbered/shifted by the
    # earlier labels -- i.e. "3", "4", not "1", "2".
    params = TerminalBlockParams(n_terminals=4, labels=["L1", "L2"])
    engine_params = terminal_block_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [
        ["L1"], ["L2"], ["3"], ["4"],
    ]


def test_terminal_block_numbering_false_with_labels():
    # numbering=False: labeled terminal 0 keeps its label; unlabeled
    # terminals 1-2 render blank (no fallback number).
    params = TerminalBlockParams(n_terminals=3, numbering=False, labels=["A"])
    engine_params = terminal_block_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [["A"], [], []]


def test_terminal_block_numbering_false_no_labels_all_blank():
    params = TerminalBlockParams(n_terminals=3, numbering=False)
    engine_params = terminal_block_engine_params(params)
    assert [b.lines for b in engine_params.blocks] == [[], [], []]


# --- 3. terminal_block: delegates to the engine ------------------------------


def test_terminal_block_builds_expected_divided_blocks_params():
    params = TerminalBlockParams(pitch_mm=6.0, n_terminals=4)
    engine_params = terminal_block_engine_params(params)
    assert engine_params.block_length_mm == 6.0
    assert engine_params.total_length_mm is None
    assert len(engine_params.blocks) == 4
    assert engine_params.separator == Separator.LINE


def test_terminal_block_vertical_default_reaches_engine():
    engine_params = terminal_block_engine_params(TerminalBlockParams())
    assert engine_params.orientation == Orientation.VERTICAL


def test_terminal_block_horizontal_orientation_reaches_engine():
    engine_params = terminal_block_engine_params(TerminalBlockParams(orientation="horizontal"))
    assert engine_params.orientation == Orientation.HORIZONTAL


def test_terminal_block_one_block_per_terminal():
    for n in (1, 12, 50):
        engine_params = terminal_block_engine_params(TerminalBlockParams(n_terminals=n))
        assert len(engine_params.blocks) == n


def test_terminal_block_font_padding_separator_forwarded_unmodified():
    params = TerminalBlockParams(
        font_family="JetBrains Mono",
        bold=True,
        font_size_px=20,
        padding_mm=3.0,
        separator=Separator.TIC,
    )
    engine_params = terminal_block_engine_params(params)
    assert engine_params.font_family == "JetBrains Mono"
    assert engine_params.bold is True
    assert engine_params.font_size_px == 20
    assert engine_params.padding_mm == 3.0
    assert engine_params.separator == Separator.TIC


def test_terminal_block_render_height_equals_print_dots():
    params = TerminalBlockParams(n_terminals=3)
    for tape_mm, expected_dots in [(24, 128), (9, 50)]:
        label = TerminalBlockRenderer().render(params, _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 4. breaker_box: Params validation ---------------------------------------


def test_breaker_box_defaults():
    p = BreakerBoxParams(breakers=[BreakerSpec()])
    assert p.pitch_mm == 25.4
    assert p.numbering_scheme == "sequential"
    assert p.start_value == 1
    assert p.show_numbers is True
    assert p.separator == Separator.LINE
    assert p.font_family == "Inter"
    assert p.padding_mm == 1.0
    assert "orientation" not in BreakerBoxParams.model_fields


@pytest.mark.parametrize("pitch", [10.0, 60.0])
def test_breaker_box_pitch_mm_boundaries_accepted(pitch):
    BreakerBoxParams(breakers=[BreakerSpec()], pitch_mm=pitch)


@pytest.mark.parametrize("pitch", [9.9, 60.1])
def test_breaker_box_pitch_mm_out_of_range_rejected(pitch):
    with pytest.raises(ValidationError):
        BreakerBoxParams(breakers=[BreakerSpec()], pitch_mm=pitch)


def test_breaker_box_zero_breakers_rejected():
    with pytest.raises(ValidationError):
        BreakerBoxParams(breakers=[])


def test_breaker_box_fifty_breakers_accepted():
    BreakerBoxParams(breakers=[BreakerSpec() for _ in range(50)])


def test_breaker_box_fifty_one_breakers_rejected():
    with pytest.raises(ValidationError):
        BreakerBoxParams(breakers=[BreakerSpec() for _ in range(51)])


@pytest.mark.parametrize("poles", [1, 4])
def test_breaker_spec_poles_boundaries_accepted(poles):
    BreakerSpec(poles=poles)


@pytest.mark.parametrize("poles", [0, 5])
def test_breaker_spec_poles_out_of_range_rejected(poles):
    with pytest.raises(ValidationError):
        BreakerSpec(poles=poles)


def test_breaker_spec_three_lines_rejected():
    with pytest.raises(ValidationError):
        BreakerSpec(lines=["A", "B", "C"])


def test_breaker_spec_two_lines_accepted_when_show_numbers_false():
    BreakerBoxParams(breakers=[BreakerSpec(lines=["A", "B"])], show_numbers=False)


@pytest.mark.parametrize("value", [1, 999])
def test_breaker_box_start_value_boundaries_accepted(value):
    BreakerBoxParams(breakers=[BreakerSpec()], start_value=value)


@pytest.mark.parametrize("value", [0, 1000])
def test_breaker_box_start_value_out_of_range_rejected(value):
    with pytest.raises(ValidationError):
        BreakerBoxParams(breakers=[BreakerSpec()], start_value=value)


@pytest.mark.parametrize("scheme", ["sequential", "odd", "even"])
def test_breaker_box_numbering_scheme_valid_values_accepted(scheme):
    BreakerBoxParams(breakers=[BreakerSpec()], numbering_scheme=scheme)


def test_breaker_box_invalid_numbering_scheme_rejected():
    with pytest.raises(ValidationError):
        BreakerBoxParams(breakers=[BreakerSpec()], numbering_scheme="prime")


# --- 5. breaker_box: panel-position numbering math (the point of this task) -
#
# slot_i = start_value + increment * positions_consumed_before_i
# increment = 1 (sequential) or 2 (odd/even); positions_consumed_before_i is
# the sum of `poles` over every EARLIER breaker. Every expected sequence
# below is hand-derived from that formula, independently of breaker_box.py's
# own implementation -- see each test's comment for the arithmetic.


def test_breaker_box_odd_scheme_brief_worked_example():
    # From the task brief itself: odd scheme, start=1, breakers [2p, 1p, 1p].
    # positions_consumed_before: 0, 2, 3 (2, then 2+1)
    # slots = 1 + 2*[0, 2, 3] = [1, 5, 7]
    params = BreakerBoxParams(
        breakers=[BreakerSpec(poles=2), BreakerSpec(poles=1), BreakerSpec(poles=1)],
        numbering_scheme="odd",
        start_value=1,
    )
    engine_params = breaker_box_engine_params(params)
    assert [b.lines[0] for b in engine_params.blocks] == ["1", "5", "7"]


def test_breaker_box_sequential_scheme_mixed_poles():
    # sequential, start=1, breakers poles=[1, 2, 3, 1, 2] (a 1/2/3-pole mix).
    # positions_consumed_before: 0, 1, 3, 6, 7
    #   (after breaker0: 0+1=1; after breaker1: 1+2=3; after breaker2: 3+3=6;
    #    after breaker3: 6+1=7)
    # increment=1 -> slots = 1 + 1*[0, 1, 3, 6, 7] = [1, 2, 4, 7, 8]
    params = BreakerBoxParams(
        breakers=[
            BreakerSpec(poles=1), BreakerSpec(poles=2), BreakerSpec(poles=3),
            BreakerSpec(poles=1), BreakerSpec(poles=2),
        ],
        numbering_scheme="sequential",
        start_value=1,
    )
    engine_params = breaker_box_engine_params(params)
    assert [b.lines[0] for b in engine_params.blocks] == ["1", "2", "4", "7", "8"]


def test_breaker_box_odd_scheme_mixed_poles():
    # Same breaker layout as above (poles=[1,2,3,1,2]), odd scheme, start=1.
    # positions_consumed_before is unchanged (poles/consumption don't depend
    # on scheme): 0, 1, 3, 6, 7. increment=2 for odd/even ->
    # slots = 1 + 2*[0, 1, 3, 6, 7] = [1, 3, 7, 13, 15]
    params = BreakerBoxParams(
        breakers=[
            BreakerSpec(poles=1), BreakerSpec(poles=2), BreakerSpec(poles=3),
            BreakerSpec(poles=1), BreakerSpec(poles=2),
        ],
        numbering_scheme="odd",
        start_value=1,
    )
    engine_params = breaker_box_engine_params(params)
    assert [b.lines[0] for b in engine_params.blocks] == ["1", "3", "7", "13", "15"]


def test_breaker_box_even_scheme_mixed_poles_with_start_value_2():
    # Same breaker layout, even scheme -- a right-column strip in real
    # panel-schedule convention starts at 2, not 1 (odd and even share the
    # same increment=2 formula; the caller supplies the different start).
    # positions_consumed_before: 0, 1, 3, 6, 7. increment=2, start=2 ->
    # slots = 2 + 2*[0, 1, 3, 6, 7] = [2, 4, 8, 14, 16]
    params = BreakerBoxParams(
        breakers=[
            BreakerSpec(poles=1), BreakerSpec(poles=2), BreakerSpec(poles=3),
            BreakerSpec(poles=1), BreakerSpec(poles=2),
        ],
        numbering_scheme="even",
        start_value=2,
    )
    engine_params = breaker_box_engine_params(params)
    assert [b.lines[0] for b in engine_params.blocks] == ["2", "4", "8", "14", "16"]


def test_breaker_box_single_pole_sequential_is_plain_1_2_3():
    # Sanity check: all 1-pole breakers, sequential -> positions_consumed_before
    # is just the index itself (0,1,2,3), so slots = start + index -- the
    # familiar "every position numbered" case.
    params = BreakerBoxParams(
        breakers=[BreakerSpec(poles=1) for _ in range(4)],
        numbering_scheme="sequential",
        start_value=1,
    )
    engine_params = breaker_box_engine_params(params)
    assert [b.lines[0] for b in engine_params.blocks] == ["1", "2", "3", "4"]


# --- 6. breaker_box: show_numbers / block text composition ------------------


def test_breaker_box_block_text_is_number_then_lines():
    params = BreakerBoxParams(
        breakers=[BreakerSpec(poles=2, lines=["MAIN"])], show_numbers=True
    )
    engine_params = breaker_box_engine_params(params)
    assert engine_params.blocks[0].lines == ["1", "MAIN"]


def test_breaker_box_show_numbers_false_omits_number():
    params = BreakerBoxParams(
        breakers=[BreakerSpec(poles=1, lines=["KITCHEN"])], show_numbers=False
    )
    engine_params = breaker_box_engine_params(params)
    assert engine_params.blocks[0].lines == ["KITCHEN"]


def test_breaker_box_show_numbers_true_no_lines_shows_number_alone():
    params = BreakerBoxParams(breakers=[BreakerSpec(poles=1)], show_numbers=True)
    engine_params = breaker_box_engine_params(params)
    assert engine_params.blocks[0].lines == ["1"]


def test_breaker_box_show_numbers_and_two_lines_rejected():
    with pytest.raises(ValidationError, match="at most 1 description line fits"):
        BreakerBoxParams(
            breakers=[BreakerSpec(poles=1, lines=["A", "B"])], show_numbers=True
        )


def test_breaker_box_show_numbers_and_one_line_accepted():
    BreakerBoxParams(breakers=[BreakerSpec(poles=1, lines=["A"])], show_numbers=True)


def test_breaker_box_show_numbers_false_and_two_lines_accepted():
    BreakerBoxParams(
        breakers=[BreakerSpec(poles=1, lines=["A", "B"])], show_numbers=False
    )


# --- 7. breaker_box: multiplier flow -- poles drives physical WIDTH ---------


def test_breaker_box_poles_forwarded_as_width_multiplier():
    params = BreakerBoxParams(
        breakers=[BreakerSpec(poles=1), BreakerSpec(poles=2), BreakerSpec(poles=3)]
    )
    engine_params = breaker_box_engine_params(params)
    assert [b.width_multiplier for b in engine_params.blocks] == [1.0, 2.0, 3.0]


def test_breaker_box_2pole_block_is_2x_width_via_layout_blocks():
    # pitch_mm=25.4 (default) is exactly 1in -> mm_to_dots(25.4) = 180 dots
    # at 180dpi, so this comes out to clean numbers:
    #   block0 (1-pole): cum_weight=1 -> boundary mm_to_dots(25.4*1)=180
    #   block1 (2-pole): cum_weight=3 -> boundary mm_to_dots(25.4*3)=540
    #   block2 (1-pole): cum_weight=4 -> boundary mm_to_dots(25.4*4)=720
    # widths: [180-0, 540-180, 720-540] = [180, 360, 180] -- block1 (2-pole)
    # is exactly 2x block0/block2 (1-pole)'s width, as poles=2 demands.
    params = BreakerBoxParams(
        breakers=[BreakerSpec(poles=1), BreakerSpec(poles=2), BreakerSpec(poles=1)]
    )
    layouts = layout_blocks(breaker_box_engine_params(params), _tape(24))
    assert [layout.width_px for layout in layouts] == [180, 360, 180]
    assert [layout.x_px for layout in layouts] == [0, 180, 540]
    assert mm_to_dots(25.4) == 180


def test_breaker_box_pitch_mm_forwarded_as_block_length_mm():
    engine_params = breaker_box_engine_params(
        BreakerBoxParams(breakers=[BreakerSpec()], pitch_mm=12.7)
    )
    assert engine_params.block_length_mm == 12.7
    assert engine_params.total_length_mm is None


# --- 8. breaker_box: orientation fixed to HORIZONTAL, no user param --------


def test_breaker_box_orientation_always_horizontal():
    for scheme in ("sequential", "odd", "even"):
        engine_params = breaker_box_engine_params(
            BreakerBoxParams(breakers=[BreakerSpec()], numbering_scheme=scheme)
        )
        assert engine_params.orientation == Orientation.HORIZONTAL


def test_breaker_box_separator_and_font_forwarded_unmodified():
    params = BreakerBoxParams(
        breakers=[BreakerSpec()],
        separator=Separator.TIC,
        font_family="Roboto Condensed",
        bold=True,
        font_size_px=18,
        padding_mm=2.5,
    )
    engine_params = breaker_box_engine_params(params)
    assert engine_params.separator == Separator.TIC
    assert engine_params.font_family == "Roboto Condensed"
    assert engine_params.bold is True
    assert engine_params.font_size_px == 18
    assert engine_params.padding_mm == 2.5


def test_breaker_box_render_height_equals_print_dots():
    params = BreakerBoxParams(breakers=[BreakerSpec(lines=["A"])])
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = BreakerBoxRenderer().render(params, _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 9. Schema fidelity: every field carries a description, bounds visible -


@pytest.mark.parametrize(
    "params_cls", [TerminalBlockParams, BreakerBoxParams], ids=lambda c: c.__name__
)
def test_every_field_carries_a_description(params_cls):
    props = params_cls.model_json_schema()["properties"]
    for field_name, schema in props.items():
        # anyOf (e.g. font_size_px: int | None) carries the description at
        # the top level, not inside each variant -- still asserted directly.
        assert schema.get("description"), f"{params_cls.__name__}.{field_name} has no description"


def test_breaker_spec_fields_carry_descriptions():
    props = BreakerSpec.model_json_schema()["properties"]
    assert props["poles"]["description"]
    assert props["lines"]["description"]


def test_terminal_block_padding_and_pitch_bounds_visible_in_schema():
    props = TerminalBlockParams.model_json_schema()["properties"]
    assert props["padding_mm"]["minimum"] == 0
    assert props["pitch_mm"]["minimum"] == 3
    assert props["pitch_mm"]["maximum"] == 50


def test_breaker_box_padding_and_pitch_bounds_visible_in_schema():
    props = BreakerBoxParams.model_json_schema()["properties"]
    assert props["padding_mm"]["minimum"] == 0
    assert props["pitch_mm"]["minimum"] == 10
    assert props["pitch_mm"]["maximum"] == 60


def test_terminal_block_orientation_schema_excludes_backbone():
    props = TerminalBlockParams.model_json_schema()["properties"]
    assert set(props["orientation"]["enum"]) == {"horizontal", "vertical"}


def test_breaker_box_has_no_orientation_param():
    assert "orientation" not in BreakerBoxParams.model_fields


# --- 9b. build_divided_blocks_params: 422 names the CALLER's type ----------


@pytest.mark.parametrize(
    "make_bad_params,renderer_cls,expected_name",
    [
        (
            lambda: TerminalBlockParams(font_family="Comic Sans"),
            TerminalBlockRenderer,
            "TerminalBlockParams",
        ),
        (
            lambda: BreakerBoxParams(breakers=[BreakerSpec()], font_family="Comic Sans"),
            BreakerBoxRenderer,
            "BreakerBoxParams",
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


# --- 10. Golden PNGs: byte-locked against committed files -------------------
#
# Fixture definitions live in golden_fixtures.py (shared with
# scripts/regen_goldens.py) -- visually inspect any new/changed golden
# before committing it (see task-2.3-report.md for descriptions).


def _render_preview_png(renderer, params, tape) -> bytes:
    label = renderer.render(params, tape)
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", ELECTRICAL_TYPE_FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    renderer = get_renderer(fixture.type)
    png = _render_preview_png(renderer, fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden
