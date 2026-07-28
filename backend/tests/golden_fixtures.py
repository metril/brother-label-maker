"""Golden-PNG fixture definitions: the single source of truth both the
test suite's golden byte-lock tests (test_text_label.py, test_divided_blocks.py,
test_type_configs.py) and scripts/regen_goldens.py render from, so the two
can never drift out of sync with each other -- a fixture added/changed here
is immediately what both the test assertions and the regen script use, with
no second copy to remember to update.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from labelmaker.render.types.barcode_label import BarcodeLabelParams
from labelmaker.render.types.breaker_box import BreakerBoxParams, BreakerSpec
from labelmaker.render.types.cable_flag import CableFlagParams
from labelmaker.render.types.cable_wrap import CableWrapParams
from labelmaker.render.types.divided_blocks import (
    BlockSpec,
    DividedBlocksParams,
    Orientation,
    Separator,
)
from labelmaker.render.types.faceplate import BlockText as FaceplateBlockText
from labelmaker.render.types.faceplate import FaceplateParams
from labelmaker.render.types.homebox_asset import HomeboxAssetParams
from labelmaker.render.types.homebox_location import HomeboxLocationParams
from labelmaker.render.types.patch_panel import BlockText as PatchPanelBlockText
from labelmaker.render.types.patch_panel import PatchPanelParams
from labelmaker.render.types.punch_down import PunchDownParams
from labelmaker.render.types.terminal_block import TerminalBlockParams
from labelmaker.render.types.text_label import ImageIcon, SymbolIcon, TextLabelParams

# Upscale factor golden PNGs are encoded at (preview_png's `scale`) -- purely
# a golden-fixture convention (makes the committed PNGs bigger/easier to eyeball
# than the raw device-dot bitmap), unrelated to any real API default.
GOLDEN_SCALE = 4

# task 2.7: `tests/fixtures/uploads/{CAM3_GRADIENT_IMAGE_ID}.png` is a
# COMMITTED, deterministically-generated (not random) synthetic diagonal
# gradient PNG -- not something a real upload endpoint ever produced. Using
# this directory AS a `data_dir` for image_object()'s `data_dir/uploads/
# {image_id}.png` lookup (see render/images.py) means golden fixture (e)
# below needs zero special-casing in image_object/text_label.py: it's just
# an ordinary `icon.kind="image"` render pointed at a fixture "upload"
# instead of a tmp_path one, which is what keeps the golden reproducible
# (a real POST /api/images upload would mint a fresh random image_id every
# run -- incompatible with a byte-locked golden).
#
# The id itself must be IMAGE_ID_RE-shaped (32 lowercase hex chars --
# render/images.py's image_path() rejects anything else, a coordinator-
# review-caught security fix: image_id is untrusted input on the render
# path, see that module's docstring) -- generated once via a fixed,
# reproducible uuid5 (NOT uuid4/random: this id is committed both as a
# filename and in this source file, and must stay the same forever), not
# something a human picked by hand.
CAM3_GRADIENT_IMAGE_ID = uuid.uuid5(
    uuid.NAMESPACE_URL, "labelmaker/tests/fixtures/cam3_gradient"
).hex
FIXTURES_DATA_DIR = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class GoldenFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    params: TextLabelParams
    tape_mm: float
    tape_family: str = "tze"
    data_dir: Path | None = None  # only set when params.icon.kind == "image"


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
    # (d) task 2.7: text + a bundled Material Symbol icon (bolt), leading
    # art at the label's left edge, text shifted right.
    GoldenFixture(
        name="text_server_bolt_icon_24mm",
        params=TextLabelParams(lines=["SERVER"], icon=SymbolIcon(id="bolt")),
        tape_mm=24,
    ),
    # (e) task 2.7: text + a DITHERED image icon -- the real end-to-end path
    # for render/images.py's mode="dither" + rasterize.py's per-ObjectRegion
    # Floyd-Steinberg mechanism (task 1.2's mechanism, exercised here for
    # the first time through an actual label type, not a synthetic SVG).
    # `data_dir=FIXTURES_DATA_DIR` (see above) resolves CAM3_GRADIENT_IMAGE_ID
    # against the committed fixture file, not a real upload.
    GoldenFixture(
        name="text_cam3_dithered_icon_24mm",
        params=TextLabelParams(
            lines=["CAM-3"], icon=ImageIcon(image_id=CAM3_GRADIENT_IMAGE_ID, mode="dither")
        ),
        tape_mm=24,
        data_dir=FIXTURES_DATA_DIR,
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


@dataclass(frozen=True)
class ElectricalTypeFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    type: str  # registered label type name -- rendered via get_renderer(type)
    params: TerminalBlockParams | BreakerBoxParams
    tape_mm: float
    tape_family: str = "tze"


# Task 2.3's two thin-config types (terminal_block/breaker_box) -- the
# product's differentiators, no Brother equivalent -- each rendered via
# get_renderer(fixture.type).render(...), same convention as
# TYPE_CONFIG_FIXTURES above.
ELECTRICAL_TYPE_FIXTURES: tuple[ElectricalTypeFixture, ...] = (
    # (a) terminal_block, 12 terminals (default), numbered 1-12 (defaults:
    # numbering=True, start_value=1, step=1), VERTICAL (default), 9mm tape --
    # the realistic DIN-rail case.
    ElectricalTypeFixture(
        name="terminal_block_12terminal_vertical_9mm",
        type="terminal_block",
        params=TerminalBlockParams(),
        tape_mm=9,
    ),
    # (b) breaker_box, odd-numbering-scheme panel column, breakers
    # [2p "MAIN", 1p "KITCHEN", 1p "LIGHTS", 2p "DRYER"] -> slots 1, 5, 7, 9
    # (see test_electrical_types.py's numbering-math derivations), 24mm tape.
    ElectricalTypeFixture(
        name="breaker_box_odd_main_kitchen_lights_dryer_24mm",
        type="breaker_box",
        params=BreakerBoxParams(
            breakers=[
                BreakerSpec(poles=2, lines=["MAIN"]),
                BreakerSpec(poles=1, lines=["KITCHEN"]),
                BreakerSpec(poles=1, lines=["LIGHTS"]),
                BreakerSpec(poles=2, lines=["DRYER"]),
            ],
            numbering_scheme="odd",
        ),
        tape_mm=24,
    ),
)


@dataclass(frozen=True)
class BarcodeTypeFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    params: BarcodeLabelParams
    tape_mm: float
    tape_family: str = "tze"


# Task 2.5's barcode label type -- one fixture per symbology family, each
# rendered via get_renderer("barcode").render(...), same convention as
# TYPE_CONFIG_FIXTURES/ELECTRICAL_TYPE_FIXTURES above.
BARCODE_TYPE_FIXTURES: tuple[BarcodeTypeFixture, ...] = (
    # (a) QR, a URL, 24mm tape, default caption="below" requested -- but the
    # URL is still ~1.6x too wide for this compact QR's own width even
    # shrunk to the 8px floor (see test_barcode_type.py's
    # test_caption_wider_than_label_auto_length_shrinks_then_drops), so this
    # renders QR-ONLY: the caption is dropped (auto-length mode never
    # silently overflows one), the code re-sizes against the tape's full
    # print height, and a caption_omitted warning is attached. Filename kept
    # as -caption- (not renamed) since it documents the PARAM as requested,
    # not the rendered outcome -- see this fixture's own history for why.
    BarcodeTypeFixture(
        name="barcode_qr_url_caption_24mm",
        params=BarcodeLabelParams(symbology="qr", data="https://example.com/a/000-001"),
        tape_mm=24,
    ),
    # (b) Code128, an asset tag, 24mm tape, default caption="below".
    BarcodeTypeFixture(
        name="barcode_code128_asset_caption_24mm",
        params=BarcodeLabelParams(symbology="code128", data="ASSET-0042"),
        tape_mm=24,
    ),
    # (c) DataMatrix, a short code, 12mm tape, caption explicitly off.
    BarcodeTypeFixture(
        name="barcode_datamatrix_short_nocaption_12mm",
        params=BarcodeLabelParams(symbology="datamatrix", data="T-01", caption="none"),
        tape_mm=12,
    ),
)


@dataclass(frozen=True)
class CableTypeFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    type: str  # registered label type name -- rendered via get_renderer(type)
    params: CableWrapParams | CableFlagParams
    tape_mm: float
    tape_family: str = "tze"


# Task 2.6's two label types (cable_wrap/cable_flag) -- same
# get_renderer(fixture.type).render(...) convention as
# TYPE_CONFIG_FIXTURES/ELECTRICAL_TYPE_FIXTURES/BARCODE_TYPE_FIXTURES above.
CABLE_TYPE_FIXTURES: tuple[CableTypeFixture, ...] = (
    # (a) cable_wrap, 2-line switch-port ID, default diameter (6mm) and
    # overlap (5mm) -- length = pi*6+5 ~= 23.85mm -- default repeat=True on
    # a 12mm tape, several repeated instances tiled along the wrap.
    CableTypeFixture(
        name="cable_wrap_sw1p24_vlan40_d6_repeat_12mm",
        type="cable_wrap",
        params=CableWrapParams(lines=["SW1-P24", "VLAN 40"]),
        tape_mm=12,
    ),
    # (b) cable_flag, single-line fiber run ID, default diameter (4mm) and
    # flag_length_mm (20mm), default horizontal orientation, 12mm tape.
    CableTypeFixture(
        name="cable_flag_fiber07_d4_flag20_horizontal_12mm",
        type="cable_flag",
        params=CableFlagParams(lines=["FIBER-07"]),
        tape_mm=12,
    ),
)


@dataclass(frozen=True)
class HomeboxTypeFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    type: str  # registered label type name -- rendered via get_renderer(type)
    params: HomeboxAssetParams | HomeboxLocationParams
    tape_mm: float
    tape_family: str = "tze"


# Task 3.3's two label types (homebox_asset/homebox_location) -- same
# get_renderer(fixture.type).render(...) convention as
# TYPE_CONFIG_FIXTURES/ELECTRICAL_TYPE_FIXTURES/BARCODE_TYPE_FIXTURES/
# CABLE_TYPE_FIXTURES above. QR payloads follow HomeBox's own scheme
# (docs/research/homebox.md #39/#40): "https://{base}/a/{asset_id}" for
# assets, "https://{base}/location/{uuid}" for locations -- composed here as
# if by the (not-yet-built) browse page's caller, exactly like a real
# LabelDefinition would arrive with `qr_data` already resolved.
HOMEBOX_TYPE_FIXTURES: tuple[HomeboxTypeFixture, ...] = (
    # (a) homebox_asset, WITH a resolved location breadcrumb and the default
    # show_qr=True -- the common case: QR + all three text roles.
    HomeboxTypeFixture(
        name="homebox_asset_ups_garage_qr_24mm",
        type="homebox_asset",
        params=HomeboxAssetParams(
            asset_id="000-042",
            name="APC Smart-UPS 1500",
            location="Garage › Shelf B",
            qr_data="https://homebox.example.com/a/000-042",
        ),
        tape_mm=24,
    ),
    # (b) homebox_asset, show_qr=False (text-only tag) and no location --
    # exercises both the "no QR" content_left_px collapse and the two-role
    # (not three-role) height-weighting path in one fixture.
    HomeboxTypeFixture(
        name="homebox_asset_noqr_tool_24mm",
        type="homebox_asset",
        params=HomeboxAssetParams(
            asset_id="000-118",
            name="Impact Driver",
            qr_data="https://homebox.example.com/a/000-118",
            show_qr=False,
        ),
        tape_mm=24,
    ),
    # (c) homebox_location, WITH a resolved ancestor path and the default
    # show_qr=True.
    HomeboxTypeFixture(
        name="homebox_location_workshop_path_qr_24mm",
        type="homebox_location",
        params=HomeboxLocationParams(
            name="Workshop",
            path="Garage › Workshop",
            qr_data="https://homebox.example.com/location/3f9c2ea1-9b7b-4e9a-8c3d-2a6f9e1d4b70",
        ),
        tape_mm=24,
    ),
)
