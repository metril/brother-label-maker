"""Label-type renderer registry: every label "type" (text, barcode, ...) is a
LabelRenderer subclass registered under a short type name via @register.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel

from labelmaker.driver.geometry import TapeSpec
from labelmaker.render.document import LabelDefinition, RenderedLabel

_REGISTRY: dict[str, type["LabelRenderer"]] = {}


class LabelTypeInfo(BaseModel):
    type: str
    title: str
    category: str
    min_tape_mm: float | None = None  # None = usable on any tape width
    params_schema: dict


class LabelRenderer(ABC):
    """Base class for a label type's renderer.

    Subclasses set `title` (a display name), `category` (grouping for a
    future type picker -- "general" for freeform text types, "network" for
    the patch_panel/punch_down/faceplate family, more later), and `Params`
    (their own pydantic model for `params`), and implement `render`.
    Registered via @register. `min_tape_mm` is optional (defaults to None,
    meaning "usable on any tape width") -- most types don't need a floor.
    """

    type: str
    title: str
    category: str
    min_tape_mm: float | None = None
    Params: type[BaseModel]

    @abstractmethod
    def render(
        self, params: BaseModel, tape: TapeSpec, *, data_dir: Path | None = None
    ) -> RenderedLabel:
        """Render `params` (already validated against this class's own
        `Params` model) against `tape`. `data_dir` (task 2.7) is the app's
        configured data directory -- only "text" actually reads it (to
        resolve an `icon.kind="image"` param's uploaded file via render/
        images.py; see text_label.py), and only when an image icon is
        requested. Every other type ignores it; it defaults to None so
        every existing direct `renderer.render(params, tape)` call (tests,
        scripts/regen_goldens.py, goldens with no icon) keeps working
        unchanged."""
        ...


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
        LabelTypeInfo(
            type=cls.type,
            title=cls.title,
            category=cls.category,
            min_tape_mm=cls.min_tape_mm,
            params_schema=cls.Params.model_json_schema(),
        )
        for cls in _REGISTRY.values()
    ]


def render_definition(defn: LabelDefinition, *, data_dir: Path | None = None) -> RenderedLabel:
    """Resolve defn's tape (exact nominal match), validate its params against
    the target type's own Params model, and render. `data_dir` (task 2.7) is
    threaded straight through to `renderer.render()` -- see that abstract
    method's docstring; optional, defaults to None, only consumed by the
    "text" type's `icon.kind="image"` path."""
    tape = defn.tape.resolve()
    renderer = get_renderer(defn.type)
    params = renderer.Params.model_validate(defn.params)
    return renderer.render(params, tape, data_dir=data_dir)
