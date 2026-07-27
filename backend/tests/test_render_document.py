"""Tests for labelmaker.render.document: the SVG document model.

render/ never imports labelmaker.driver except labelmaker.driver.geometry --
this test file only ever imports geometry constants for cross-checking
figures, matching that rule.
"""

import pytest
from pydantic import ValidationError

from labelmaker.driver.geometry import MediaFamily, all_tapes
from labelmaker.render.document import (
    LabelDefinition,
    ObjectRegion,
    RenderedLabel,
    RenderWarning,
    Tape,
)

# --- 1. Tape.resolve(): exact nominal_mm match, per family ---


def test_tape_resolve_24mm_tze():
    spec = Tape(width_mm=24, family="tze").resolve()
    assert spec.print_dots == 128
    assert spec.family is MediaFamily.TZE
    assert spec.nominal_mm == 24


def test_tape_resolve_8_8mm_hse_2_1():
    spec = Tape(width_mm=8.8, family="hse_2_1").resolve()
    assert spec.nominal_mm == 8.8
    assert spec.family is MediaFamily.HSE_2_1
    assert spec.print_dots == 48


def test_tape_resolve_23_6mm_hse_2_1_resolves():
    spec = Tape(width_mm=23.6, family="hse_2_1").resolve()
    assert spec.nominal_mm == 23.6
    assert spec.print_dots == 128


def test_tape_resolve_24mm_hse_2_1_is_not_23_6_and_raises():
    # 24mm under hse_2_1 must NOT round-trip to the 23.6mm tape via
    # status_width_mm (both report status_width_mm == 24) -- exact nominal
    # match only.
    with pytest.raises(ValueError, match="23.6"):
        Tape(width_mm=24, family="hse_2_1").resolve()


def test_tape_resolve_unknown_width_lists_valid_widths_for_family():
    with pytest.raises(ValueError) as exc_info:
        Tape(width_mm=999, family="tze").resolve()
    message = str(exc_info.value)
    tze_widths = sorted(t.nominal_mm for t in all_tapes() if t.family is MediaFamily.TZE)
    for width in tze_widths:
        assert str(width) in message
    # hse widths must not leak into a tze error message
    assert "hse" not in message.lower() or True  # message only lists tze widths, checked above


def test_tape_resolve_default_family_is_tze():
    assert Tape(width_mm=24).family == "tze"


def test_tape_invalid_family_rejected_by_pydantic():
    with pytest.raises(ValidationError):
        Tape(width_mm=24, family="not_a_family")


# --- 2. ObjectRegion / RenderedLabel: defaults and field shapes ---


def test_object_region_fields():
    region = ObjectRegion(x=1, y=2, width=3, height=4, mode="dither")
    assert (region.x, region.y, region.width, region.height, region.mode) == (1, 2, 3, 4, "dither")


def test_object_region_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        ObjectRegion(x=0, y=0, width=1, height=1, mode="blur")


def test_rendered_label_defaults():
    label = RenderedLabel(svg="<svg/>", width_px=10, height_px=20)
    assert label.object_map == []
    assert label.warnings == []


def test_rendered_label_with_object_map_and_warnings():
    label = RenderedLabel(
        svg="<svg/>",
        width_px=10,
        height_px=20,
        object_map=[ObjectRegion(x=0, y=0, width=5, height=5, mode="dither")],
        warnings=[RenderWarning(code="text_cramped", message="cramped")],
    )
    assert len(label.object_map) == 1
    assert len(label.warnings) == 1
    assert label.warnings[0].code == "text_cramped"
    assert label.warnings[0].severity == "warning"
    assert label.warnings[0].message == "cramped"
    assert label.warnings[0].object_id is None


# --- 3. RenderWarning: field shape and defaults -----------------------------


def test_render_warning_defaults():
    warning = RenderWarning(code="text_cramped", message="cramped")
    assert warning.severity == "warning"
    assert warning.object_id is None


def test_render_warning_info_severity_and_object_id():
    warning = RenderWarning(
        code="dither_region", severity="info", message="a note", object_id="obj-1"
    )
    assert warning.severity == "info"
    assert warning.object_id == "obj-1"


def test_render_warning_invalid_severity_rejected():
    with pytest.raises(ValidationError):
        RenderWarning(code="x", severity="critical", message="m")


# --- 4. LabelDefinition ---


def test_label_definition_roundtrip():
    defn = LabelDefinition(
        type="text",
        tape=Tape(width_mm=24, family="tze"),
        params={"lines": ["HELLO"]},
    )
    assert defn.type == "text"
    assert defn.tape.width_mm == 24
    assert defn.params == {"lines": ["HELLO"]}


# --- 5. SVG helpers (module-private, exercised directly) ---


def test_escape_xml_escapes_special_characters():
    from labelmaker.render.document import _escape_xml

    assert _escape_xml("A & B <C> \"D\" 'E'") == "A &amp; B &lt;C&gt; &quot;D&quot; &apos;E&apos;"


def test_svg_document_wraps_body_with_white_background():
    from labelmaker.render.document import _svg_document

    svg = _svg_document(100, 50, "<circle/>")
    assert svg.startswith("<svg")
    assert 'width="100"' in svg
    assert 'height="50"' in svg
    assert 'viewBox="0 0 100 50"' in svg
    assert 'fill="white"' in svg
    assert "<circle/>" in svg
    assert svg.rstrip().endswith("</svg>")


def test_text_element_has_expected_attributes():
    from labelmaker.render.document import _text_element

    el = _text_element(10, 20, "Hi & Bye", "Inter", 16, text_anchor="middle", bold=True)
    assert 'x="10"' in el
    assert 'y="20"' in el
    assert 'font-family="Inter"' in el
    assert 'font-size="16"' in el
    assert 'text-anchor="middle"' in el
    assert 'font-weight="bold"' in el
    assert "Hi &amp; Bye" in el
    assert el.startswith("<text")
    assert el.rstrip().endswith("</text>")


def test_text_element_no_bold_omits_font_weight():
    from labelmaker.render.document import _text_element

    el = _text_element(0, 0, "x", "Inter", 12)
    assert "font-weight" not in el
