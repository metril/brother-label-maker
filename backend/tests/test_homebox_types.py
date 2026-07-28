"""Tests for the task 3.3 label types: homebox_asset, homebox_location --
pure-layout renderers for HomeBox inventory items (see each module's own
docstring for the "why no I/O" contract: `qr_data`/`name`/`location`/`path`
all arrive already resolved by the caller; this module never talks to
HomeBox itself, synchronously or otherwise).

Both types are bespoke SVG layouts (NOT built on divided_blocks.py -- a QR
code plus a small stack of differently-sized text roles isn't a block grid),
though they reuse `objects.qr_object` for the code itself and
`fonts.fit_font_size` for auto-sizing, exactly the same shared helpers every
other label type in this package uses -- see each module's own docstring.

Golden fixtures live in golden_fixtures.py's HOMEBOX_TYPE_FIXTURES (shared
with scripts/regen_goldens.py, same convention as every other golden-backed
type in this suite); the two QR-bearing fixtures are additionally decode-
verified with zxing-cpp (a DEV-only dependency, see pyproject.toml) --
proving not just that the SVG geometry looks right, but that a real
scanner could read the result, the same guarantee test_objects.py's own
"Scannability regression guard" section establishes for the underlying
`qr_object` primitive.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from golden_fixtures import GOLDEN_SCALE, HOMEBOX_TYPE_FIXTURES
from pydantic import ValidationError

from labelmaker.render.document import Tape
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import get_renderer, list_types
from labelmaker.render.types.homebox_asset import HomeboxAssetParams, HomeboxAssetRenderer
from labelmaker.render.types.homebox_location import HomeboxLocationParams, HomeboxLocationRenderer

GOLDEN_DIR = Path(__file__).parent / "golden" / "render"


def _tape(width_mm, family="tze"):
    return Tape(width_mm=width_mm, family=family).resolve()


# --- 0. Registration: both under "homebox", min_tape_mm=12.0 ----------------


def test_both_types_registered_under_homebox_with_min_tape_mm_12():
    by_type = {t.type: t for t in list_types()}
    assert by_type.keys() >= {"homebox_asset", "homebox_location"}
    for type_name in ("homebox_asset", "homebox_location"):
        assert by_type[type_name].category == "homebox"
        assert by_type[type_name].min_tape_mm == 12.0
    assert by_type["homebox_asset"].title == "HomeBox Asset"
    assert by_type["homebox_location"].title == "HomeBox Location"


def test_get_renderer_returns_expected_renderer_instances():
    assert isinstance(get_renderer("homebox_asset"), HomeboxAssetRenderer)
    assert isinstance(get_renderer("homebox_location"), HomeboxLocationRenderer)


def test_api_lists_eleven_types_including_homebox():
    assert {t.type for t in list_types()} == {
        "text", "barcode", "patch_panel", "punch_down", "faceplate",
        "cable_wrap", "cable_flag", "terminal_block", "breaker_box",
        "homebox_asset", "homebox_location",
    }
    assert len(list_types()) == 11


# --- 1. HomeboxAssetParams: Field bounds (not field_validators) -------------
#
# docs/project-handoff.md §8: "Validator-body bounds are invisible to the
# client... Prefer Field(...) for anything the form should enforce." Every
# bound below is a plain Field(min_length=/max_length=), so both the
# ValidationError AND params_schema (section 3 below) see it.


def test_homebox_asset_required_fields():
    with pytest.raises(ValidationError):
        HomeboxAssetParams(name="UPS", qr_data="https://x/a/1")  # missing asset_id
    with pytest.raises(ValidationError):
        HomeboxAssetParams(asset_id="1", qr_data="https://x/a/1")  # missing name
    with pytest.raises(ValidationError):
        HomeboxAssetParams(asset_id="1", name="UPS")  # missing qr_data


def test_homebox_asset_defaults():
    p = HomeboxAssetParams(asset_id="000-042", name="UPS", qr_data="https://x/a/000-042")
    assert p.location == ""
    assert p.show_qr is True


@pytest.mark.parametrize("length", [1, 32])
def test_homebox_asset_id_length_boundaries_accepted(length):
    HomeboxAssetParams(asset_id="A" * length, name="UPS", qr_data="https://x/a/1")


@pytest.mark.parametrize("length", [0, 33])
def test_homebox_asset_id_length_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        HomeboxAssetParams(asset_id="A" * length, name="UPS", qr_data="https://x/a/1")


@pytest.mark.parametrize("length", [1, 120])
def test_homebox_asset_name_length_boundaries_accepted(length):
    HomeboxAssetParams(asset_id="1", name="A" * length, qr_data="https://x/a/1")


@pytest.mark.parametrize("length", [0, 121])
def test_homebox_asset_name_length_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        HomeboxAssetParams(asset_id="1", name="A" * length, qr_data="https://x/a/1")


def test_homebox_asset_location_boundaries_accepted():
    HomeboxAssetParams(asset_id="1", name="UPS", location="", qr_data="https://x/a/1")
    HomeboxAssetParams(asset_id="1", name="UPS", location="A" * 160, qr_data="https://x/a/1")


def test_homebox_asset_location_over_160_rejected():
    with pytest.raises(ValidationError):
        HomeboxAssetParams(asset_id="1", name="UPS", location="A" * 161, qr_data="https://x/a/1")


@pytest.mark.parametrize("length", [1, 512])
def test_homebox_asset_qr_data_length_boundaries_accepted(length):
    HomeboxAssetParams(asset_id="1", name="UPS", qr_data="A" * length)


@pytest.mark.parametrize("length", [0, 513])
def test_homebox_asset_qr_data_length_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        HomeboxAssetParams(asset_id="1", name="UPS", qr_data="A" * length)


# --- 2. HomeboxLocationParams: same Field-bound convention ------------------


def test_homebox_location_defaults():
    p = HomeboxLocationParams(name="Workshop", qr_data="https://x/location/abc")
    assert p.path == ""
    assert p.show_qr is True


@pytest.mark.parametrize("length", [1, 120])
def test_homebox_location_name_length_boundaries_accepted(length):
    HomeboxLocationParams(name="A" * length, qr_data="https://x/location/abc")


@pytest.mark.parametrize("length", [0, 121])
def test_homebox_location_name_length_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        HomeboxLocationParams(name="A" * length, qr_data="https://x/location/abc")


def test_homebox_location_path_boundaries_accepted():
    HomeboxLocationParams(name="Workshop", path="A" * 160, qr_data="https://x/location/abc")


def test_homebox_location_path_over_160_rejected():
    with pytest.raises(ValidationError):
        HomeboxLocationParams(name="Workshop", path="A" * 161, qr_data="https://x/location/abc")


@pytest.mark.parametrize("length", [1, 512])
def test_homebox_location_qr_data_length_boundaries_accepted(length):
    HomeboxLocationParams(name="Workshop", qr_data="A" * length)


@pytest.mark.parametrize("length", [0, 513])
def test_homebox_location_qr_data_length_out_of_range_rejected(length):
    with pytest.raises(ValidationError):
        HomeboxLocationParams(name="Workshop", qr_data="A" * length)


# --- 3. Schema fidelity: Field bounds reach params_schema -------------------


def test_homebox_asset_schema_carries_field_bounds():
    props = HomeboxAssetParams.model_json_schema()["properties"]
    assert props["asset_id"]["minLength"] == 1
    assert props["asset_id"]["maxLength"] == 32
    assert props["name"]["minLength"] == 1
    assert props["name"]["maxLength"] == 120
    assert props["location"]["maxLength"] == 160
    assert props["qr_data"]["minLength"] == 1
    assert props["qr_data"]["maxLength"] == 512


def test_homebox_location_schema_carries_field_bounds():
    props = HomeboxLocationParams.model_json_schema()["properties"]
    assert props["name"]["minLength"] == 1
    assert props["name"]["maxLength"] == 120
    assert props["path"]["maxLength"] == 160
    assert props["qr_data"]["minLength"] == 1
    assert props["qr_data"]["maxLength"] == 512


# --- 4. Layout behavior ------------------------------------------------------


def test_asset_show_qr_true_renders_a_qr_and_shifts_text_right():
    tape = _tape(24)
    with_qr = HomeboxAssetRenderer().render(
        HomeboxAssetParams(asset_id="1", name="UPS", qr_data="https://x/a/1", show_qr=True), tape
    )
    without_qr = HomeboxAssetRenderer().render(
        HomeboxAssetParams(asset_id="1", name="UPS", qr_data="https://x/a/1", show_qr=False), tape
    )
    # QR modules are black `<rect>`s (see objects.py); _svg_document's own
    # background rect is always present (white), so check specifically for
    # a BLACK one -- the QR's own footprint, not the document background.
    assert 'fill="black"' in with_qr.svg
    assert 'fill="black"' not in without_qr.svg
    # The QR + its gap makes the show_qr=True render meaningfully wider.
    assert with_qr.width_px > without_qr.width_px


def test_asset_location_blank_renders_two_text_elements_not_three():
    tape = _tape(24)
    no_location = HomeboxAssetRenderer().render(
        HomeboxAssetParams(asset_id="1", name="UPS", qr_data="https://x/a/1"), tape
    )
    with_location = HomeboxAssetRenderer().render(
        HomeboxAssetParams(
            asset_id="1", name="UPS", location="Garage", qr_data="https://x/a/1"
        ),
        tape,
    )
    assert no_location.svg.count("<text") == 2
    assert with_location.svg.count("<text") == 3


def test_location_path_blank_renders_one_text_element_not_two():
    tape = _tape(24)
    no_path = HomeboxLocationRenderer().render(
        HomeboxLocationParams(name="Workshop", qr_data="https://x/location/abc"), tape
    )
    with_path = HomeboxLocationRenderer().render(
        HomeboxLocationParams(name="Workshop", path="Garage", qr_data="https://x/location/abc"),
        tape,
    )
    assert no_path.svg.count("<text") == 1
    assert with_path.svg.count("<text") == 2


def test_asset_id_rendered_in_jetbrains_mono_bold():
    label = HomeboxAssetRenderer().render(
        HomeboxAssetParams(asset_id="000-042", name="UPS", qr_data="https://x/a/1"), _tape(24)
    )
    assert 'font-family="JetBrains Mono"' in label.svg
    # The asset_id <text> element specifically carries font-weight="bold".
    id_element = next(
        line for line in label.svg.split("<text") if "JetBrains Mono" in line
    )
    assert 'font-weight="bold"' in id_element


def test_location_name_rendered_bold_condensed():
    label = HomeboxLocationRenderer().render(
        HomeboxLocationParams(name="Workshop", qr_data="https://x/location/abc"), _tape(24)
    )
    assert 'font-family="Roboto Condensed"' in label.svg
    assert 'font-weight="bold"' in label.svg


def test_qr_too_tall_for_tiny_tape_raises_value_error():
    # 3.5mm tze -> print_dots=24; this qr_data's matrix (29x29 + 8 quiet =
    # 37 total modules, checked directly against the qrcode library) can't
    # fit even module_px=1 in a 24px band.
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data("https://homebox.example.com/a/000-042")
    qr.make(fit=True)
    total_modules = len(qr.get_matrix()) + 8
    tape = _tape(3.5)
    assert tape.print_dots < total_modules

    params = HomeboxAssetParams(
        asset_id="000-042", name="UPS", qr_data="https://homebox.example.com/a/000-042"
    )
    with pytest.raises(ValueError, match="print height"):
        HomeboxAssetRenderer().render(params, tape)


def test_qr_too_tall_does_not_apply_when_show_qr_false():
    # Same tiny tape/data as above, but text-only -- no QR sizing at all, so
    # this must NOT raise (may still warn text_cramped, which is fine).
    tape = _tape(3.5)
    params = HomeboxAssetParams(
        asset_id="000-042",
        name="UPS",
        location="Garage",
        qr_data="https://homebox.example.com/a/000-042",
        show_qr=False,
    )
    label = HomeboxAssetRenderer().render(params, tape)
    assert 'fill="black"' not in label.svg


def test_cramped_tape_warns_text_cramped_named_by_role():
    # Same tiny tape, three roles competing for a 24px-tall band -- name and
    # location's proportionally smaller shares fall below fit_font_size's
    # own min_px floor (empirically confirmed via direct exploration, see
    # this module's own docstring convention for such cases).
    tape = _tape(3.5)
    params = HomeboxAssetParams(
        asset_id="042", name="UPS", location="Garage", qr_data="https://x/a/1", show_qr=False
    )
    label = HomeboxAssetRenderer().render(params, tape)
    cramped_ids = {w.object_id for w in label.warnings if w.code == "text_cramped"}
    assert cramped_ids == {"name", "location"}
    assert all(w.severity == "info" for w in label.warnings if w.code == "text_cramped")


def test_asset_render_height_equals_print_dots():
    params = HomeboxAssetParams(asset_id="1", name="UPS", qr_data="https://x/a/1")
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = HomeboxAssetRenderer().render(params, _tape(tape_mm))
        assert label.height_px == expected_dots


def test_location_render_height_equals_print_dots():
    params = HomeboxLocationParams(name="Workshop", qr_data="https://x/location/abc")
    for tape_mm, expected_dots in [(24, 128), (12, 70)]:
        label = HomeboxLocationRenderer().render(params, _tape(tape_mm))
        assert label.height_px == expected_dots


# --- 5. Golden PNGs: byte-locked against committed files --------------------


def _render_preview_png(fixture) -> bytes:
    renderer = get_renderer(fixture.type)
    label = renderer.render(fixture.params, _tape(fixture.tape_mm, fixture.tape_family))
    img = rasterize(label)
    return preview_png(img, scale=GOLDEN_SCALE)


@pytest.mark.parametrize("fixture", HOMEBOX_TYPE_FIXTURES, ids=lambda f: f.name)
def test_golden_matches_committed_png(fixture):
    png = _render_preview_png(fixture)
    golden = (GOLDEN_DIR / f"{fixture.name}.png").read_bytes()
    assert png == golden


# --- 6. Scannability regression guard: decode the golden QR fixtures -------
#
# Proves not just that the SVG geometry looks right (section 5 above), but
# that a real scanner could read the result -- same zxing-cpp convention as
# test_objects.py's own "Scannability regression guard" section.


@pytest.mark.parametrize(
    "fixture", [f for f in HOMEBOX_TYPE_FIXTURES if f.params.show_qr], ids=lambda f: f.name
)
def test_golden_qr_decodes_back_to_qr_data(fixture):
    zxingcpp = pytest.importorskip("zxingcpp")
    from PIL import Image

    golden = GOLDEN_DIR / f"{fixture.name}.png"
    img = Image.open(golden)
    barcode_read = zxingcpp.read_barcode(img.convert("L"))
    assert barcode_read is not None, f"zxing-cpp could not decode {fixture.name}'s QR at all"
    assert barcode_read.text == fixture.params.qr_data
    assert barcode_read.format == zxingcpp.BarcodeFormat.QRCode
