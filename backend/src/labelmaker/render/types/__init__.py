"""Label type renderers: registry + built-in types.

Importing this package registers every built-in type ("text", task 2.2's
patch_panel/punch_down/faceplate, task 2.3's terminal_block/breaker_box, and
task 2.5's barcode) as a side effect of importing its module below.

Registration order below IS the display order of list_types() (base.py's
_REGISTRY is a plain dict, keyed by @register's type_name at class-
decoration time -- decoration happens at import time, in the order modules
are imported here, and dict iteration in Python is insertion-ordered). With
a single type this is invisible; once a second type lands, the import order
of its module relative to text_label's below is a real UI decision (e.g.
the order label-type tabs/options appear in), not an incidental one -- order
these imports deliberately, don't just append. text first (category
"general"), then barcode (task 2.5, also category "general" -- registered
immediately after text so both "general" types stay adjacent), then the
three "network" types in the same order the task 2.2 brief lists them
(patch_panel, punch_down, faceplate), then the two "electrical" types in the
order the task 2.3 brief lists them (terminal_block, breaker_box).
"""

from labelmaker.render.types import text_label  # noqa: F401,I001 -- registers "text"
from labelmaker.render.types import barcode_label  # noqa: F401 -- registers "barcode"
from labelmaker.render.types import patch_panel  # noqa: F401 -- registers "patch_panel"
from labelmaker.render.types import punch_down  # noqa: F401 -- registers "punch_down"
from labelmaker.render.types import faceplate  # noqa: F401 -- registers "faceplate"
from labelmaker.render.types import terminal_block  # noqa: F401 -- registers "terminal_block"
from labelmaker.render.types import breaker_box  # noqa: F401 -- registers "breaker_box"
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
