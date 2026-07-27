"""Label type renderers: registry + built-in types.

Importing this package registers every built-in type (currently just
"text") as a side effect of importing its module below.

Registration order below IS the display order of list_types() (base.py's
_REGISTRY is a plain dict, keyed by @register's type_name at class-
decoration time -- decoration happens at import time, in the order modules
are imported here, and dict iteration in Python is insertion-ordered). With
a single type this is invisible; once a second type lands, the import order
of its module relative to text_label's below is a real UI decision (e.g.
the order label-type tabs/options appear in), not an incidental one -- order
these imports deliberately, don't just append.
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
