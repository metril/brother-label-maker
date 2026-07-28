"""Label type renderers: registry + built-in types.

Importing this package registers every built-in type ("text", task 2.2's
patch_panel/punch_down/faceplate, task 2.3's terminal_block/breaker_box,
task 2.5's barcode, task 2.6's cable_wrap/cable_flag, and task 3.3's
homebox_asset/homebox_location) as a side effect of importing its module
below.

Registration order below IS the display order of list_types() (base.py's
_REGISTRY is a plain dict, keyed by @register's type_name at class-
decoration time -- decoration happens at import time, in the order modules
are imported here, and dict iteration in Python is insertion-ordered). With
a single type this is invisible; once a second type lands, the import order
of its module relative to text_label's below is a real UI decision (e.g.
the order label-type tabs/options appear in), not an incidental one -- order
these imports deliberately, don't just append. text first (category
"general"), then barcode (task 2.5, also category "general" -- registered
immediately after text so both "general" types stay adjacent), then all
five "network" types together -- the task 2.2 brief's own order
(patch_panel, punch_down, faceplate) followed by task 2.6's cable_wrap then
cable_flag (that task's own brief/title order) -- then the two "electrical"
types in the order the task 2.3 brief lists them (terminal_block,
breaker_box), then task 3.3's two "homebox" types (asset, location -- that
task's own brief order) kept last as their own new category group, the same
way "electrical" was appended after "network" rather than interleaved.
"""

from labelmaker.render.types import text_label  # noqa: F401,I001 -- registers "text"
from labelmaker.render.types import barcode_label  # noqa: F401 -- registers "barcode"
from labelmaker.render.types import patch_panel  # noqa: F401 -- registers "patch_panel"
from labelmaker.render.types import punch_down  # noqa: F401 -- registers "punch_down"
from labelmaker.render.types import faceplate  # noqa: F401 -- registers "faceplate"
from labelmaker.render.types import cable_wrap  # noqa: F401 -- registers "cable_wrap"
from labelmaker.render.types import cable_flag  # noqa: F401 -- registers "cable_flag"
from labelmaker.render.types import terminal_block  # noqa: F401 -- registers "terminal_block"
from labelmaker.render.types import breaker_box  # noqa: F401 -- registers "breaker_box"
from labelmaker.render.types import homebox_asset  # noqa: F401 -- registers "homebox_asset"
from labelmaker.render.types import homebox_location  # noqa: F401 -- registers "homebox_location"
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
