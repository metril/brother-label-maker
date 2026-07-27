"""Golden-PNG fixture definitions: the single source of truth both the
test suite's golden byte-lock tests (test_text_label.py, test_divided_blocks.py,
test_type_configs.py) and scripts/regen_goldens.py render from, so the two
can never drift out of sync with each other -- a fixture added/changed here
is immediately what both the test assertions and the regen script use, with
no second copy to remember to update.
"""

from dataclasses import dataclass

from labelmaker.render.types.divided_blocks import (
    BlockSpec,
    DividedBlocksParams,
    Orientation,
    Separator,
)
from labelmaker.render.types.faceplate import BlockText as FaceplateBlockText
from labelmaker.render.types.faceplate import FaceplateParams
from labelmaker.render.types.patch_panel import BlockText as PatchPanelBlockText
from labelmaker.render.types.patch_panel import PatchPanelParams
from labelmaker.render.types.punch_down import PunchDownParams
from labelmaker.render.types.text_label import TextLabelParams

# Upscale factor golden PNGs are encoded at (preview_png's `scale`) -- purely
# a golden-fixture convention (makes the committed PNGs bigger/easier to eyeball
# than the raw device-dot bitmap), unrelated to any real API default.
GOLDEN_SCALE = 4


@dataclass(frozen=True)
class GoldenFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    params: TextLabelParams
    tape_mm: float
    tape_family: str = "tze"


FIXTURES: tuple[GoldenFixture, ...] = (
    GoldenFixture(
        name="text_hello_inter_24mm",
        params=TextLabelParams(lines=["HELLO"]),
        tape_mm=24,
    ),
    GoldenFixture(
        name="text_two_line_robotocondensed_bold_12mm",
        params=TextLabelParams(
            lines=["PATCH PANEL", "PORT 1-24"], font_family="Roboto Condensed", bold=True
        ),
        tape_mm=12,
    ),
    GoldenFixture(
        name="text_port01_jetbrainsmono_fixed40mm_left_24mm",
        params=TextLabelParams(
            lines=["PORT-01"], font_family="JetBrains Mono", length_mm=40.0, h_align="left"
        ),
        tape_mm=24,
    ),
)


@dataclass(frozen=True)
class DividedBlocksFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    params: DividedBlocksParams
    tape_mm: float
    tape_family: str = "tze"


DIVIDED_BLOCKS_FIXTURES: tuple[DividedBlocksFixture, ...] = (
    # (a) 4-block patch-panel-ish LINE separator, 24mm tape, horizontal.
    DividedBlocksFixture(
        name="divided_blocks_4block_line_24mm",
        params=DividedBlocksParams(
            blocks=[BlockSpec(lines=[f"A{i}"]) for i in range(1, 5)],
            block_length_mm=15.0,
            separator=Separator.LINE,
            orientation=Orientation.HORIZONTAL,
        ),
        tape_mm=24,
    ),
    # (b) 6-block TIC separator, 12mm tape, multipliers [1,1,2,1,1,1].
    DividedBlocksFixture(
        name="divided_blocks_6block_tic_multipliers_12mm",
        params=DividedBlocksParams(
            blocks=[
                BlockSpec(lines=[str(i)], width_multiplier=m)
                for i, m in zip(range(1, 7), [1, 1, 2, 1, 1, 1], strict=True)
            ],
            block_length_mm=12.0,
            separator=Separator.TIC,
        ),
        tape_mm=12,
    ),
    # (c) 3-block VERTICAL FRAME, 24mm tape.
    DividedBlocksFixture(
        name="divided_blocks_3block_vertical_frame_24mm",
        params=DividedBlocksParams(
            blocks=[BlockSpec(lines=[f"CH{i}"]) for i in range(1, 4)],
            block_length_mm=20.0,
            separator=Separator.FRAME,
            orientation=Orientation.VERTICAL,
        ),
        tape_mm=24,
    ),
)


@dataclass(frozen=True)
class TypeConfigFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    type: str  # registered label type name -- rendered via get_renderer(type)
    params: PatchPanelParams | PunchDownParams | FaceplateParams
    tape_mm: float
    tape_family: str = "tze"


# Task 2.2's three thin-config types (patch_panel/punch_down/faceplate), each
# rendered via get_renderer(fixture.type).render(...) -- i.e. through the
# real registered type, not by calling render_divided_blocks directly (unlike
# DIVIDED_BLOCKS_FIXTURES above, which exercises the un-registered engine
# module on its own).
TYPE_CONFIG_FIXTURES: tuple[TypeConfigFixture, ...] = (
    # (a) patch_panel, 6 blocks "P-01".."P-06", 24mm tape, LINE separator
    # (default), block_length_mm 15.0 (default).
    TypeConfigFixture(
        name="patch_panel_6block_p0x_24mm",
        type="patch_panel",
        params=PatchPanelParams(
            blocks=[PatchPanelBlockText(lines=[f"P-0{i}"]) for i in range(1, 7)]
        ),
        tape_mm=24,
    ),
    # (b) punch_down, 4-pair, start_value 1, 6 blocks, 12mm tape (all defaults).
    TypeConfigFixture(
        name="punch_down_4pair_start1_6block_12mm",
        type="punch_down",
        params=PunchDownParams(),
        tape_mm=12,
    ),
    # (c) faceplate, 2 blocks ["OFFICE 1", "OFFICE 2"], 24mm tape, NONE
    # separator (default), total_length_mm 70.0 (default).
    TypeConfigFixture(
        name="faceplate_2block_office_24mm",
        type="faceplate",
        params=FaceplateParams(
            blocks=[
                FaceplateBlockText(lines=["OFFICE 1"]),
                FaceplateBlockText(lines=["OFFICE 2"]),
            ]
        ),
        tape_mm=24,
    ),
)
