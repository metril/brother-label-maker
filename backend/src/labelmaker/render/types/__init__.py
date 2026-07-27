"""Label type renderers: registry + built-in types.

Importing this package registers every built-in type (currently just
"text") as a side effect of importing its module below.
"""

from labelmaker.render.types import text_label  # noqa: F401 -- registers "text" as a side effect
from labelmaker.render.types.base import (
    LabelRenderer,
    LabelTypeInfo,
    get_renderer,
    list_types,
    register,
    render_definition,
)

__all__ = [
    "LabelRenderer",
    "LabelTypeInfo",
    "get_renderer",
    "list_types",
    "register",
    "render_definition",
]
