"""Label-type renderer registry: every label "type" (text, barcode, ...) is a
LabelRenderer subclass registered under a short type name via @register.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from labelmaker.driver.geometry import TapeSpec
from labelmaker.render.document import LabelDefinition, RenderedLabel

_REGISTRY: dict[str, type["LabelRenderer"]] = {}


class LabelTypeInfo(BaseModel):
    type: str
    title: str
    params_schema: dict


class LabelRenderer(ABC):
    """Base class for a label type's renderer.

    Subclasses set `title` (a display name) and `Params` (their own pydantic
    model for `params`), and implement `render`. Registered via @register.
    """

    type: str
    title: str
    Params: type[BaseModel]

    @abstractmethod
    def render(self, params: BaseModel, tape: TapeSpec) -> RenderedLabel: ...


def register(type_name: str):
    """Class decorator: register a LabelRenderer subclass under type_name."""

    def decorator(cls: type[LabelRenderer]) -> type[LabelRenderer]:
        cls.type = type_name
        _REGISTRY[type_name] = cls
        return cls

    return decorator


def get_renderer(type_name: str) -> LabelRenderer:
    cls = _REGISTRY.get(type_name)
    if cls is None:
        raise KeyError(f"unknown label type {type_name!r}; valid types: {sorted(_REGISTRY)}")
    return cls()


def list_types() -> list[LabelTypeInfo]:
    return [
        LabelTypeInfo(type=cls.type, title=cls.title, params_schema=cls.Params.model_json_schema())
        for cls in _REGISTRY.values()
    ]


def render_definition(defn: LabelDefinition) -> RenderedLabel:
    """Resolve defn's tape (exact nominal match), validate its params against
    the target type's own Params model, and render."""
    tape = defn.tape.resolve()
    renderer = get_renderer(defn.type)
    params = renderer.Params.model_validate(defn.params)
    return renderer.render(params, tape)
