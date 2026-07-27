"""Curated Material Symbols icon library (task 2.7) -- a small "objects"
module, parallel to render/objects.py's barcode groups: `symbol_object()`
places one bundled icon's vector path at a given size/position on a label's
canvas, ready to drop straight into an SVG document body.

Assets live outside the installed package at backend/assets/symbols/,
sibling to backend/assets/fonts/ (see fonts.py's FONTS_DIR docstring for
the same layout assumption -- Path(__file__).resolve().parents[3] walks
render/ -> labelmaker/ -> src/ -> backend/). Two files there matter to this
module: `index.json` (the catalog: `[{id, name, tags, path}, ...]`) and one
`<id>.svg` per catalog entry -- see backend/assets/symbols/LICENSES.md for
where they came from (Material Symbols, Apache-2.0) and exactly how they
were normalized.

-- The single-path-24x24 assumption --

Every bundled file is assumed to be exactly one `<svg viewBox="0 0 24 24">`
wrapping exactly one `<path d="..." .../>` (LICENSES.md documents the
normalization step that makes this true for every file this project
curated). `symbol_object()` doesn't parse SVG generically -- it takes
everything between the outer `<svg ...>` and `</svg>` tags verbatim (a
plain string slice, via regex) and re-wraps it in a translate+scale `<g>`.
This is deliberately NOT a general SVG-inlining mechanism: it trusts the
curated file's inner content is already just path data with no `<script>`,
no external references, no font-family/style declarations of its own (the
"validate at load" half of the brief's ask) -- `_validate_symbol_svg` below
checks the shape (single `<path>`, correct viewBox, no `style`/`font-family`
attributes) every time a symbol is loaded, raising loudly rather than
silently inlining something this mechanism wasn't designed for. This same
per-load check is what test_symbols.py's asset-integrity test exercises
against all 60 bundled files up front, so a curation mistake is caught by
the test suite, not discovered later at render time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from labelmaker.render.document import _fmt_num

SYMBOLS_DIR = Path(__file__).resolve().parents[3] / "assets" / "symbols"

_SVG_WRAPPER_RE = re.compile(r"<svg\b[^>]*>(.*)</svg>\s*\Z", re.S)
_PATH_TAG_RE = re.compile(r"<path\b", re.S)
_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"0 0 24 24"')
_FORBIDDEN_ATTR_RE = re.compile(r"\b(style|font-family)\s*=", re.I)


class SymbolInfo(BaseModel):
    id: str
    name: str
    tags: list[str]
    path: str


def ensure_symbols_dir() -> None:
    """Raise loudly if SYMBOLS_DIR doesn't exist -- same rationale as
    fonts.ensure_fonts_dir(): without this, a missing/misplaced assets
    directory degrades into a confusing FileNotFoundError deep inside
    json.loads()/Path.read_text() instead of one clear message naming what's
    actually wrong, at the first point this module touches the filesystem.
    """
    if not SYMBOLS_DIR.is_dir():
        raise RuntimeError(
            f"symbols directory not found: {SYMBOLS_DIR} -- expected backend/assets/symbols "
            "alongside backend/assets/fonts (see labelmaker.render.symbols.SYMBOLS_DIR)"
        )


def list_symbols() -> list[SymbolInfo]:
    """The full 60-icon catalog, freshly re-read from index.json every call
    (no caching) -- same convention as fonts.py's list_fonts()/font_path():
    a test that points SYMBOLS_DIR elsewhere sees the change immediately,
    rather than a stale value cached from whatever SYMBOLS_DIR was at first
    call. index.json is small (60 entries); re-parsing it is cheap.
    """
    ensure_symbols_dir()
    index_path = SYMBOLS_DIR / "index.json"
    if not index_path.is_file():
        raise RuntimeError(f"symbols index not found: {index_path}")
    raw = json.loads(index_path.read_text())
    return [SymbolInfo.model_validate(entry) for entry in raw]


def get_symbol_info(symbol_id: str) -> SymbolInfo:
    for info in list_symbols():
        if info.id == symbol_id:
            return info
    valid = sorted(info.id for info in list_symbols())
    raise ValueError(
        f"unknown symbol id {symbol_id!r}; {len(valid)} valid id(s), see GET /api/symbols "
        f"(first 10: {valid[:10]})"
    )


def _validate_symbol_svg(info: SymbolInfo, raw: str) -> str:
    """Returns the inner content of `raw` (everything between the outer
    `<svg ...>` and `</svg>` tags) after checking the single-path-24x24
    assumption this whole module depends on (see module docstring) --
    raises ValueError naming exactly what's wrong rather than silently
    inlining a malformed/unexpected file.
    """
    match = _SVG_WRAPPER_RE.match(raw.strip())
    if match is None:
        raise ValueError(
            f"symbol {info.id!r} file {info.path} is not a single <svg>...</svg> document"
        )
    if not _VIEWBOX_RE.search(raw):
        raise ValueError(f"symbol {info.id!r} file {info.path} must declare viewBox=\"0 0 24 24\"")
    path_count = len(_PATH_TAG_RE.findall(raw))
    if path_count != 1:
        raise ValueError(
            f"symbol {info.id!r} file {info.path} must contain exactly one <path>, "
            f"found {path_count}"
        )
    if _FORBIDDEN_ATTR_RE.search(raw):
        raise ValueError(
            f"symbol {info.id!r} file {info.path} must not carry style/font-family "
            "attributes (see rasterize.py's font-family guard for why this matters)"
        )
    return match.group(1)


def _load_symbol_inner_svg(info: SymbolInfo) -> str:
    ensure_symbols_dir()
    path = SYMBOLS_DIR / info.path
    if not path.is_file():
        raise RuntimeError(
            f"symbol file missing: {path} (listed in index.json as id={info.id!r})"
        )
    return _validate_symbol_svg(info, path.read_text())


def symbol_object(symbol_id: str, *, size_px: int, x: int = 0, y: int = 0) -> str:
    """One bundled icon, scaled from its native 24x24 viewBox to `size_px`
    (a square) and positioned at (x, y) -- an SVG `<g>` fragment ready to
    drop into a label body, same calling convention as render/objects.py's
    barcode `*_object()` functions (which also take x/y directly, unlike
    render/images.py's `image_object()` -- see that module's docstring for
    why it doesn't).

    Raises ValueError for an unknown `symbol_id` (422-mappable by any
    caller that funnels ValueError through the usual error_message() path --
    see api/router_labels.py's text-with-icon wiring) or a curated file that
    fails `_validate_symbol_svg`'s shape check.
    """
    if size_px <= 0:
        raise ValueError(f"size_px must be positive, got {size_px}")
    info = get_symbol_info(symbol_id)
    inner = _load_symbol_inner_svg(info)
    scale = size_px / 24
    return f'<g transform="translate({x},{y}) scale({_fmt_num(scale)})">{inner}</g>'
