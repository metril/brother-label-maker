"""Render core: SVG document model, hermetic fonts, rasterizer, label types.

The guarantee this package exists to provide: preview and print are the same
bitmap. Every label is rendered once, from a single RenderedLabel (an SVG
document + device-pixel canvas size), through rasterize() to a PIL mode "1"
image -- the preview PNG is encoded from that same image, never a second
render path.

render/ never imports labelmaker.driver EXCEPT labelmaker.driver.geometry
(TapeSpec/geometry is shared vocabulary with the driver, nothing else is).
"""

from labelmaker.render.document import LabelDefinition, ObjectRegion, RenderedLabel, Tape
from labelmaker.render.fonts import (
    FONTS_DIR,
    FontInfo,
    ensure_fonts_dir,
    fit_font_size,
    font_path,
    list_fonts,
    measure_text,
)
from labelmaker.render.rasterize import preview_png, rasterize
from labelmaker.render.types import (
    LabelRenderer,
    LabelTypeInfo,
    get_renderer,
    list_types,
    register,
    render_definition,
)

__all__ = [
    "FONTS_DIR",
    "FontInfo",
    "LabelDefinition",
    "LabelRenderer",
    "LabelTypeInfo",
    "ObjectRegion",
    "RenderedLabel",
    "Tape",
    "ensure_fonts_dir",
    "fit_font_size",
    "font_path",
    "get_renderer",
    "list_fonts",
    "list_types",
    "measure_text",
    "preview_png",
    "rasterize",
    "register",
    "render_definition",
]
