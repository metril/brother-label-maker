"""Curated icon library (task 2.7, expanded to ~1000+ icons in commit 7's
symbols pipeline) -- a small "objects" module, parallel to render/objects.py's
barcode groups: `symbol_object()` places one bundled icon's vector path at a
given size/position on a label's canvas, ready to drop straight into an SVG
document body.

Assets live outside the installed package at backend/assets/symbols/,
sibling to backend/assets/fonts/ (see fonts.py's FONTS_DIR docstring for
the same layout assumption -- Path(__file__).resolve().parents[3] walks
render/ -> labelmaker/ -> src/ -> backend/). Two things there matter to this
module: `index.json` (the manifest v2 catalog: `[{id, name, tags, path,
category, source, license}, ...]`) and one `<id>.svg` per catalog entry --
see backend/assets/symbols/LICENSES.md for where they came from (Material
Symbols/Apache-2.0, Phosphor/MIT -- each entry's `source`/`license` fields
name which) and exactly how they were normalized. The original 60 ids are
bare (e.g. "bolt"); everything the backend/scripts/symbols_pipeline/
pipeline added is namespaced by source (`material_*`, `phosphor_*`) so old
saved label definitions/presets referencing a bare id keep resolving. (The
`safety` manifest category exists for a possible future source and is
currently unused -- see the pipeline's own README.md.)

-- The single-path-24x24 assumption --

Every bundled file is assumed to be exactly one `<svg viewBox="0 0 24 24">`
wrapping exactly one `<path d="..." .../>` (LICENSES.md documents the
normalization step that makes this true for every file this project
curated, including the pipeline-generated ones -- Material/Phosphor each
start from a different native coordinate system and get rewritten to this
same shape). `symbol_object()` doesn't parse SVG generically -- it
takes everything between the outer `<svg ...>` and `</svg>` tags verbatim (a
plain string slice, via regex) and re-wraps it in a translate+scale `<g>`.
This is deliberately NOT a general SVG-inlining mechanism: it trusts the
curated file's inner content is already just path data with no `<script>`,
no external references, no font-family/style declarations of its own (the
"validate at load" half of the brief's ask) -- `_validate_symbol_svg` below
checks the shape (single `<path>`, correct viewBox, no `style`/`font-family`,
no `<script>`, no event-handler (`on*`) attributes, no `href`/`xlink:href` --
L9, 2026-08 review) every time a symbol is loaded, raising loudly rather than
silently inlining something this mechanism wasn't designed for. This same
per-load check is what test_symbols.py's asset-integrity test exercises
against every bundled file up front, so a curation mistake is caught by the
test suite, not discovered later at render time. The pipeline itself
(backend/scripts/symbols_pipeline/common.py) reruns this exact check (plus a
rasterize gate) at generation time, before a file is ever committed.

-- Caching --

index.json now holds 8000+ entries, so list_symbols()/get_symbol_info() no
longer re-read+re-validate it on every call: both cache on
`(str(index_path), index_path.stat().st_mtime_ns)` -- a cache hit is free, a
miss (first call, or index.json's mtime changed -- including a test that
monkeypatches SYMBOLS_DIR to a tmp_path, which naturally has its own
distinct path in the cache key) transparently re-parses. Nothing needs to
call an explicit "invalidate" function; touching/rewriting index.json is
enough.

At this catalog size, "a cache hit is free" turned out not to be true for
list_symbols() ITSELF: its per-call `model_copy(deep=True)` over 8362
entries (see its docstring -- that copy is load-bearing for callers that
mutate a returned entry) plus FastAPI's own response-model re-encoding was
measured costing 690-866ms of event-loop time per GET /api/symbols request
(review doc H4). `list_symbols_json()` below is the fix for that ONE
caller: it caches the fully-encoded response *bytes* on the same cache key,
paid once per index.json change rather than once per request, and
`symbols_etag()` gives GET /api/symbols a matching weak ETag (also
mtime_ns-derived) so a client's conditional GET can skip both the transfer
and the encode via a 304. `list_symbols()`'s own per-call deep-copy
contract is unchanged -- `get_symbol_info()` and any other caller that
needs safely-mutable instances should keep using it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from labelmaker.render.document import _fmt_num

SYMBOLS_DIR = Path(__file__).resolve().parents[3] / "assets" / "symbols"

_SVG_WRAPPER_RE = re.compile(r"<svg\b[^>]*>(.*)</svg>\s*\Z", re.S)
_PATH_TAG_RE = re.compile(r"<path\b", re.S)
_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"0 0 24 24"')
# L9 (2026-08 review): style/font-family were the original checks (see
# rasterize.py's font-family guard); `on\w+` (event-handler attributes,
# e.g. onload/onclick) is new -- symbols are served directly as
# image/svg+xml (api/router_labels.py's GET /api/symbols/{id}), which is
# script-executing content when navigated to directly, so this needs to
# reject the same active-content surface a browser would actually execute.
_FORBIDDEN_ATTR_RE = re.compile(r"\b(style|font-family|on\w+)\s*=", re.I)
# <script> siblings and href/xlink:href (an <image>/<use>/<a> pulling in
# external -- or javascript: -- content) are checked separately from
# _FORBIDDEN_ATTR_RE above since they're not a bare `name=` attribute
# shape: a tag name and an attribute name that legitimately appears on
# many non-hostile SVG constructs this module doesn't otherwise use.
_SCRIPT_TAG_RE = re.compile(r"<\s*script\b", re.I)
_HREF_ATTR_RE = re.compile(r"\b(?:xlink:)?href\s*=", re.I)


class SymbolInfo(BaseModel):
    id: str
    name: str
    tags: list[str]
    path: str
    # Manifest v2 (commit 7): category is one of general/electrical/network/
    # av/arrow/safety/misc (see backend/scripts/symbols_pipeline/common.py's
    # VALID_CATEGORIES -- "safety" is reserved for a possible future source
    # and currently unused); source/license are free-form provenance strings
    # ("material-symbols@0.45.10"/"Apache-2.0", "phosphor@2.1.1"/"MIT") --
    # see LICENSES.md for the full per-source detail these two fields
    # summarize.
    category: str
    source: str
    license: str


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


def _current_index_path() -> Path:
    ensure_symbols_dir()
    index_path = SYMBOLS_DIR / "index.json"
    if not index_path.is_file():
        raise RuntimeError(f"symbols index not found: {index_path}")
    return index_path


def _cache_key(index_path: Path) -> tuple[str, int]:
    """`(path, mtime_ns)` -- a test that monkeypatches SYMBOLS_DIR gets a
    distinct key automatically (different path), and rewriting index.json
    in place (the pipeline's emit_source(), or a test fixture) bumps mtime_ns
    and so is picked up on the very next call with no explicit invalidation.
    """
    return (str(index_path), index_path.stat().st_mtime_ns)


def _parse_index(index_path: Path) -> list[SymbolInfo]:
    raw = json.loads(index_path.read_text())
    return [SymbolInfo.model_validate(entry) for entry in raw]


_list_cache: tuple[tuple[str, int], list[SymbolInfo]] | None = None


def list_symbols() -> list[SymbolInfo]:
    """The full catalog (8000+ entries as of commit 7's symbols pipeline),
    cached by `_cache_key()` -- see the module docstring's "Caching" section.
    Returns a fresh list of deep-copied `SymbolInfo` instances each call, so
    a caller mutating either the returned list OR a field on one of its
    entries (e.g. appending to `.tags`, a mutable list) can't corrupt the
    cached instances -- a plain `list(...)` shallow copy would still share
    the same `SymbolInfo` objects (and their mutable `tags` lists) with the
    cache, which is not enough.

    This deep copy is real per-call work at 8362 entries -- callers that
    only need to serialize the catalog verbatim (GET /api/symbols) should
    use `list_symbols_json()` instead, which skips it entirely (see that
    function's docstring and H4 in docs/code-review-2026-08.md).
    """
    global _list_cache
    index_path = _current_index_path()
    key = _cache_key(index_path)
    if _list_cache is None or _list_cache[0] != key:
        _list_cache = (key, _parse_index(index_path))
    return [info.model_copy(deep=True) for info in _list_cache[1]]


_SYMBOL_LIST_ADAPTER: TypeAdapter = TypeAdapter(list[SymbolInfo])
_list_json_cache: tuple[tuple[str, int], bytes] | None = None


def list_symbols_json() -> bytes:
    """The full catalog pre-encoded to JSON bytes, cached on the same
    `_cache_key()` as `list_symbols()` (and sharing its `_list_cache` parse,
    so a cache miss here never re-reads/re-validates index.json a second
    time). GET /api/symbols (router_labels.py) hands this straight to
    `Response(content=..., media_type="application/json")`, which is what
    makes it a real fix for H4 (docs/code-review-2026-08.md) rather than a
    relocation of the cost: neither `list_symbols()`'s per-call deep copy
    (irrelevant here -- `bytes` is immutable, there's nothing to protect the
    cache from) nor FastAPI's `jsonable_encoder`/response-model re-encoding
    (measured at 1317ms/8362 entries) run per request any more -- both are
    paid once, on the same index.json-mtime miss that already invalidates
    `_list_cache`.

    `TypeAdapter(list[SymbolInfo]).dump_json(...)` was checked byte-for-byte
    identical to what FastAPI's `list[SymbolInfo]` response model produced
    for this same catalog before this function existed (same compact
    separators, same field order, same non-ASCII handling) -- so this is a
    caching change, not a response-shape change.
    """
    global _list_cache, _list_json_cache
    index_path = _current_index_path()
    key = _cache_key(index_path)
    if _list_cache is None or _list_cache[0] != key:
        _list_cache = (key, _parse_index(index_path))
    if _list_json_cache is None or _list_json_cache[0] != key:
        _list_json_cache = (key, _SYMBOL_LIST_ADAPTER.dump_json(_list_cache[1]))
    return _list_json_cache[1]


def symbols_etag() -> str:
    """A weak ETag for the whole catalog (GET /api/symbols), derived from
    index.json's mtime_ns -- the same identity `_cache_key()` uses, so this
    changes exactly when `list_symbols_json()`'s cached bytes change and
    stays stable otherwise. Weak (`W/`) because the guarantee is
    freshness-equivalence (same index.json generation), not byte-for-byte
    identity (RFC 7232 2.1) -- appropriate here since nothing promises the
    encoded bytes are stable across code changes, only that a given
    index.json mtime always encodes the same way.
    """
    _, mtime_ns = _cache_key(_current_index_path())
    return f'W/"{mtime_ns}"'


_info_cache: tuple[tuple[str, int], dict[str, SymbolInfo]] | None = None


def get_symbol_info(symbol_id: str) -> SymbolInfo:
    """O(1) id lookup via a cached `{id: SymbolInfo}` dict, same cache key
    convention as list_symbols() (see module docstring). Returns a
    deep-copied `SymbolInfo`, never the cached instance itself, for the same
    reason list_symbols() returns deep copies: a caller mutating the
    returned object's fields (e.g. `.tags.append(...)`) must not be able to
    reach the cached instance shared by every future call.
    """
    global _info_cache
    index_path = _current_index_path()
    key = _cache_key(index_path)
    if _info_cache is None or _info_cache[0] != key:
        _info_cache = (key, {info.id: info for info in list_symbols()})
    by_id = _info_cache[1]
    if symbol_id in by_id:
        return by_id[symbol_id].model_copy(deep=True)
    valid = sorted(by_id)
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
        raise ValueError(f'symbol {info.id!r} file {info.path} must declare viewBox="0 0 24 24"')
    path_count = len(_PATH_TAG_RE.findall(raw))
    if path_count != 1:
        raise ValueError(
            f"symbol {info.id!r} file {info.path} must contain exactly one <path>, "
            f"found {path_count}"
        )
    # L9 (2026-08 review): checked before _FORBIDDEN_ATTR_RE so a hostile
    # file with BOTH a <script> sibling and an onload= attribute gets the
    # more specific "must not contain a <script>" message, not a generic
    # attribute one.
    if _SCRIPT_TAG_RE.search(raw):
        raise ValueError(f"symbol {info.id!r} file {info.path} must not contain a <script> element")
    if _HREF_ATTR_RE.search(raw):
        raise ValueError(
            f"symbol {info.id!r} file {info.path} must not carry href/xlink:href attributes"
        )
    if _FORBIDDEN_ATTR_RE.search(raw):
        raise ValueError(
            f"symbol {info.id!r} file {info.path} must not carry style/font-family/event-handler "
            "attributes (see rasterize.py's font-family guard for why this matters)"
        )
    return match.group(1)


def resolve_symbol_path(info: SymbolInfo) -> Path:
    """SYMBOLS_DIR/info.path, resolved and containment-checked (review L9)
    -- the ONE choke point every SymbolInfo -> filesystem path resolution
    in this module goes through, shared by `_load_symbol_inner_svg` below
    and api/router_labels.py's GET /api/symbols/{id} (which serves the raw
    file directly, so it needs the Path itself for stat()-derived ETag/
    Last-Modified headers, not just the validated inner content
    `symbol_object()` wants). Mirrors render/images.py's `image_path()`/
    `_resolve_contained()` pattern: resolve the candidate, assert it's
    still under SYMBOLS_DIR's own resolved form, raise ValueError (never
    return an out-of-bounds path) otherwise.

    index.json's `path` field is committed content, not runtime-untrusted
    input the way an uploaded image_id is -- this is defense in depth
    against a future bad manifest entry or a symlink surprise, not a
    response to a live threat.
    """
    base = SYMBOLS_DIR.resolve()
    candidate = (base / info.path).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"symbol {info.id!r} path {info.path!r} escapes SYMBOLS_DIR")
    return candidate


def validate_symbol_svg(info: SymbolInfo, raw: str) -> None:
    """Public wrapper around this module's own shape/content checks
    (review L9): api/router_labels.py's GET /api/symbols/{id} calls this
    before streaming a catalog file back as active `image/svg+xml`
    content, so a future hostile/malformed manifest entry is rejected the
    same way a curation mistake already is at render time
    (`symbol_object()` -> `_load_symbol_inner_svg()` ->
    `_validate_symbol_svg()`) -- never served verbatim. Raises ValueError
    for anything `_validate_symbol_svg` would reject; its inner-content
    return value is irrelevant to a caller that serves the ORIGINAL bytes
    unchanged, so this discards it.
    """
    _validate_symbol_svg(info, raw)


def _load_symbol_inner_svg(info: SymbolInfo) -> str:
    ensure_symbols_dir()
    path = resolve_symbol_path(info)
    if not path.is_file():
        raise RuntimeError(f"symbol file missing: {path} (listed in index.json as id={info.id!r})")
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
