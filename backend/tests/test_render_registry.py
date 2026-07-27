"""Tests for labelmaker.render.types.base: the label-type renderer registry.

Registers a local dummy type (rather than depending on the real "text" type)
so this file tests registry mechanics in isolation; text-specific
registration (list_types() containing "text", its schema) is asserted in
test_text_label.py alongside the rest of that type's behavior.
"""

import pytest
from pydantic import BaseModel, ValidationError

from labelmaker.render.document import LabelDefinition, RenderedLabel, Tape
from labelmaker.render.types.base import (
    LabelRenderer,
    LabelTypeInfo,
    get_renderer,
    list_types,
    register,
    render_definition,
)


class _DummyParams(BaseModel):
    text: str = "hi"


@register("dummy")
class _DummyRenderer(LabelRenderer):
    title = "Dummy"
    Params = _DummyParams

    def render(self, params: _DummyParams, tape) -> RenderedLabel:
        return RenderedLabel(svg=f"<svg>{params.text}</svg>", width_px=1, height_px=tape.print_dots)


def test_register_adds_entry_to_list_types():
    dummy = next(t for t in list_types() if t.type == "dummy")
    assert isinstance(dummy, LabelTypeInfo)
    assert dummy.title == "Dummy"
    assert "text" in dummy.params_schema.get("properties", {})


def test_get_renderer_returns_a_renderer_instance():
    renderer = get_renderer("dummy")
    assert isinstance(renderer, _DummyRenderer)
    assert isinstance(renderer, LabelRenderer)


def test_get_renderer_unknown_type_raises_keyerror_listing_valid_types():
    with pytest.raises(KeyError) as exc_info:
        get_renderer("does-not-exist")
    assert "dummy" in str(exc_info.value)


def test_render_definition_resolves_tape_validates_params_and_renders():
    defn = LabelDefinition(
        type="dummy", tape=Tape(width_mm=24, family="tze"), params={"text": "hello"}
    )
    result = render_definition(defn)
    assert isinstance(result, RenderedLabel)
    assert result.height_px == 128  # 24mm tze -> print_dots 128
    assert "hello" in result.svg


def test_render_definition_uses_params_default_when_omitted():
    defn = LabelDefinition(type="dummy", tape=Tape(width_mm=24, family="tze"), params={})
    result = render_definition(defn)
    assert "hi" in result.svg


def test_render_definition_invalid_params_raises_validation_error():
    defn = LabelDefinition(
        type="dummy", tape=Tape(width_mm=24, family="tze"), params={"text": {"not": "a string"}}
    )
    with pytest.raises(ValidationError):
        render_definition(defn)


def test_render_definition_invalid_tape_raises_value_error():
    defn = LabelDefinition(type="dummy", tape=Tape(width_mm=999, family="tze"), params={})
    with pytest.raises(ValueError, match="999"):
        render_definition(defn)


def test_render_definition_unknown_type_raises_keyerror():
    defn = LabelDefinition(type="does-not-exist", tape=Tape(width_mm=24, family="tze"), params={})
    with pytest.raises(KeyError):
        render_definition(defn)
