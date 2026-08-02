"""Shared helpers for backend/scripts/symbols_pipeline/'s fetch_*.py scripts
(currently fetch_material.py, fetch_phosphor.py) -- manifest v2 read/write,
the SAME shape validation render/symbols.py's loader enforces at load time
(imported directly, not re-implemented, so the pipeline can never silently
drift from what the runtime loader accepts), and the pipeline-time
exhaustive rasterize gate the brief requires ("the PIPELINE itself must run
the exhaustive rasterize check when generating").

Not a runtime module: nothing under labelmaker/ imports this package, and
nothing here should assume anything beyond the dev environment (`uv sync`
from backend/ with the default dependency groups gets you everything this
module needs). A future source with multi-shape/colored source SVGs might
need a real flattening dependency of its own (see README.md's "Adding a
source" section) -- keep any such dependency script-only, in its own
`fetch_<source>.py`, never imported here or from runtime code.

Usage: each fetch_*.py builds a list[Candidate] (its own source-specific
download + curated-id-list parsing + normalization), then calls emit_source()
once to (idempotently) replace that source's slice of backend/assets/symbols/
and merge the result into index.json.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    # Makes `labelmaker` importable when this is run as a bare script (`uv run
    # python scripts/symbols_pipeline/fetch_material.py` from backend/) even
    # though nothing under labelmaker/ ever imports back into this package.
    sys.path.insert(0, str(SRC_DIR))

from PIL import Image  # noqa: E402

from labelmaker.render.document import RenderedLabel, _svg_document  # noqa: E402
from labelmaker.render.rasterize import rasterize  # noqa: E402
from labelmaker.render.symbols import SymbolInfo, _validate_symbol_svg  # noqa: E402

SYMBOLS_DIR = BACKEND_DIR / "assets" / "symbols"
INDEX_PATH = SYMBOLS_DIR / "index.json"

# The 7-bucket `category` enum manifest v2 entries must land in (render/
# symbols.py's SymbolInfo doesn't itself enforce this -- it's a pipeline/test
# convention, see test_symbols.py's category-coverage test).
VALID_CATEGORIES = {"general", "electrical", "network", "av", "arrow", "safety", "misc"}
MANIFEST_KEYS = {"id", "name", "tags", "path", "category", "source", "license"}

# The pre-manifest-v2 shape (existing 60's index.json entries before this
# pipeline ever ran) -- used only to detect "not upgraded yet" during
# upgrade_legacy_entries().
_LEGACY_KEYS = {"id", "name", "tags", "path"}

_PATH_TAG_RE = re.compile(r"<path\b", re.S)
_PATH_D_RE = re.compile(r'<path\b[^>]*\bd="([^"]*)"', re.S)
_SVG_INNER_RE = re.compile(r"<svg\b[^>]*>(.*)</svg>\s*\Z", re.S)
_CATEGORY_HEADER_RE = re.compile(r"^#\s*category:\s*(\w+)\s*$", re.I)
_ID_CHARSET_RE = re.compile(r"[a-z0-9_]+")

# extract_fill_path()'s parsing primitives (see its own docstring): a
# self-closing-or-not <path ...> element, and a generic attr="value" pair
# scraper applied to just that one element's text (not the whole document --
# every fetch_*.py source this is used against ships flat <path> siblings
# directly under <svg>, never nested groups, see that function's docstring).
_PATH_ELEMENT_RE = re.compile(r"<path\b[^>]*/?>", re.S)
_ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"([^"]*)"')
# Any element extract_fill_path can't safely fold into a plain <path> merge:
# other drawable primitives (a source using <circle>/<rect>/... instead of a
# <path> for a simple shape -- seen once, Bootstrap Icons' circle-fill.svg),
# or grouping/indirection constructs (<g> transforms, <clipPath>/<mask>/<use>
# indirection) that a naive "concatenate every <path> d string" merge cannot
# account for.
_OTHER_ELEMENT_RE = re.compile(
    r"<(circle|rect|ellipse|line|polyline|polygon|g|clipPath|mask|use|defs)\b", re.S
)

# Existing-60 entries were curated (task 2.7) from Material Symbols at this
# exact commit -- see assets/symbols/LICENSES.md's "Material Symbols" section.
# Distinct from the new material_* entries' source, which is the pinned npm
# package fetch_material.py downloads (a different upstream snapshot, hence a
# different `source` string even though both are Apache-2.0 Material Symbols
# icons).
_LEGACY_MATERIAL_SOURCE = "material-design-icons@528cb964c0"
_LEGACY_MATERIAL_LICENSE = "Apache-2.0"


@dataclass
class Candidate:
    """One accepted, already-normalized icon ready to be written to disk and
    added to the manifest. `svg_text` is a complete, shape-valid
    `<svg viewBox="0 0 24 24">...</svg>` document (single <path>, no
    style/font-family) -- everything upstream of emit_source() (curated-id
    lookup, download, single-path extraction, per-source transform) has
    already happened by the time a Candidate exists.

    `source`/`license` are per-candidate rather than a single value for the
    whole emit_source() call: fetch_material.py and fetch_phosphor.py both
    just set the same constant on every Candidate they build (one npm
    package version/license per run), but a future source whose per-file
    license can vary within a single run (e.g. a Commons-style source where
    different files carry different licenses) can set it per-candidate
    without any change to emit_source() itself.
    """

    base_id: str  # e.g. "wifi_off" -- WITHOUT the source's namespace prefix
    name: str
    tags: list[str]
    category: str
    source: str
    license: str
    svg_text: str


@dataclass
class SourceReport:
    prefix: str
    accepted: list[str]
    skipped: list[tuple[str, str]]  # (candidate identifier, reason)

    def summary(self) -> str:
        lines = [
            f"{self.prefix}: {len(self.accepted)} accepted, {len(self.skipped)} skipped"
        ]
        for ident, reason in self.skipped:
            lines.append(f"  skip {ident}: {reason}")
        return "\n".join(lines)


def humanize_id(base_id: str) -> str:
    """'wifi_off' -> 'Wifi Off'; 'arrow_back_ios' -> 'Arrow Back iOS'. A small
    acronym table covers the abbreviations that show up across both curated
    lists often enough to be worth spelling out correctly (matches the
    existing 60's hand-written names like "DNS/Server", "VPN Key", "USB")
    -- anything else just gets str.title()'d.
    """
    acronyms = {
        "tv": "TV", "usb": "USB", "dns": "DNS", "lan": "LAN", "nfc": "NFC",
        "sd": "SD", "hvac": "HVAC", "ac": "AC", "ios": "iOS", "qr": "QR",
        "id": "ID", "wifi": "Wifi", "2": "2",
    }
    words = [acronyms.get(w, w.capitalize()) for w in base_id.split("_")]
    return " ".join(words)


def parse_curated_ids_with_category(text: str, ids_filename: str) -> list[tuple[str, str]]:
    """Returns [(category, icon_id), ...] in file order, honoring
    '# category: <bucket>' section headers (case-insensitive) -- the format
    both material_ids.txt and phosphor_ids.txt document in their own header
    comments. Other '#'-prefixed lines are comments (including '##'
    human-only sub-headings), blank lines are skipped. `ids_filename` is
    used only to name the offending file in the error raised when an id line
    appears before any '# category:' header has been seen.

    Shared by fetch_material.py and fetch_phosphor.py so the '# category:'
    directive has exactly one implementation -- each fetch_*.py is still
    responsible for validating the returned category against
    VALID_CATEGORIES (raising on an unknown bucket) since that's the point
    at which "unknown category" is actually an error rather than a parse
    concern.
    """
    out: list[tuple[str, str]] = []
    category: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _CATEGORY_HEADER_RE.match(line)
            if m:
                category = m.group(1).lower()
            continue
        if category is None:
            raise ValueError(
                f"{ids_filename}: id {line!r} appears before any '# category:' header"
            )
        out.append((category, line))
    return out


def extract_single_path_d(svg_text: str) -> str | None:
    """The sole <path>'s `d` attribute, or None if `svg_text` has zero or
    more than one <path> element -- every fetch_*.py skips (and logs) a
    multi-path source icon rather than guessing which path to keep.
    """
    if len(_PATH_TAG_RE.findall(svg_text)) != 1:
        return None
    m = _PATH_D_RE.search(svg_text)
    return m.group(1) if m else None


def build_svg_document(d: str, transform: str = "", *, fill_rule: str | None = None) -> str:
    """Wraps a raw (verbatim, un-rewritten) path `d` string in the single
    viewBox="0 0 24 24" <svg> document shape render/symbols.py requires,
    applying `transform` to reconcile the source's native coordinate system
    with the 0..24 square -- same recipe as the existing 60 (see
    assets/symbols/LICENSES.md's "Normalization" section), just parameterized
    per source since Material (0,-960,960,960) and Phosphor (0,0,256,256)
    each need a different transform string.

    `transform` defaults to "" (attribute omitted entirely, not emitted as
    an empty `transform=""`) for the Track D2 sources whose native viewBox
    already IS "0 0 24 24" (Tabler/Remix/Fluent -- Bootstrap's 16-unit
    square still needs `scale(1.5)`). `fill_rule`, if given (e.g.
    "evenodd"), is emitted as an explicit `fill-rule="..."` attribute on the
    <path> -- required for a merged multi-path candidate (see
    extract_fill_path) or a single source path whose own hole geometry
    depends on evenodd rather than nonzero winding; omitted (SVG's implicit
    nonzero default applies) when None, matching every call site that
    predates Track D2.
    """
    attrs = [f'd="{d}"']
    if transform:
        attrs.append(f'transform="{transform}"')
    if fill_rule:
        attrs.append(f'fill-rule="{fill_rule}"')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path {" ".join(attrs)}/></svg>'
    )


def _path_attrs(path_element: str) -> dict[str, str]:
    return dict(_ATTR_RE.findall(path_element))


def extract_fill_path(svg_text: str) -> tuple[str, str] | None:
    """Source-agnostic single-OR-multi-<path> extraction for an
    already-filled source icon (Tabler/Remix/Bootstrap/Fluent's filled
    variants -- unlike Lucide's stroke-based markup, see fetch_lucide.py):
    returns `(merged_d, fill_rule)`, or None if `svg_text` can't be reduced
    to one same-fill shape this way (caller skips+logs; every fetch_*.py
    that calls this already prints WHY -- see e.g. fetch_tabler.py's
    docstring for the enumerated reject reasons below in prose).

    Unlike `extract_single_path_d` (which only ever accepts a lone <path>
    and throws away whatever `fill-rule` it may have declared), this:

    1. Drops every <path fill="none" .../> outright -- an explicitly
       fill="none" path paints NOTHING, so removing it never changes the
       rendered result; it's how several of these sources ship an invisible
       full-canvas hitbox/bounding-box path alongside the real glyph
       (Tabler's `<path stroke="none" d="M0 0h24v24H0z" fill="none" />` on
       literally every filled icon is the motivating case -- without this
       drop step EVERY Tabler candidate would look "multi-path" for no
       visual reason).
    2. Rejects (returns None) if:
       - zero <path> elements survive step 1 (nothing left to draw), or
       - any of `<circle>`/`<rect>`/`<ellipse>`/`<line>`/`<polyline>`/
         `<polygon>`/`<g>`/`<clipPath>`/`<mask>`/`<use>`/`<defs>` appears
         anywhere in the document (a shape or indirection this naive
         d-string concatenation can't safely fold in -- seen once in
         practice, Bootstrap Icons' circle-fill.svg uses a bare <circle>),
       - the surviving paths declare more than one distinct explicit `fill`
         value (a genuinely multi-color icon -- e.g. Fluent's
         flag_pride_*_24_filled.svg, each stripe its own hex color --
         can't be flattened into one single-fill path without silently
         discarding color information), or
       - any surviving path carries its own `stroke` (other than an
         explicit "none") or `transform` attribute (a per-path transform
         would need to be actually applied to that path's own `d`
         coordinates before concatenation could be correct -- raw string
         concatenation across differently-transformed local coordinate
         spaces would silently mangle the shape, so this rejects rather
         than pretending the transforms are identity).
    3. Rejects (returns None) if any NON-FIRST surviving path's `d`
       (lstripped) starts with a lowercase `m`: per the SVG path grammar a
       relative moveto is only treated as absolute-equivalent when it is
       the very FIRST command of the whole path. Concatenated after a
       preceding subpath's final command, it instead resolves against
       THAT subpath's current point, silently translating (and often
       displacing) everything that follows -- this shipped 17 visibly
       corrupted icons before this check existed (docs/code-review-2026-08.md
       H3; e.g. bootstrap_house's roof ends up as a diagonal slash through
       the body). Correcting it would require converting the relative `m`
       to an absolute `M`, which needs the preceding subpath's terminal
       current point -- i.e. actually interpreting the path, not just
       string-handling it -- so this function skips the merge rather than
       guessing.
    4. Otherwise concatenates the survivors' `d` strings (space-joined)
       into a candidate `merged_d`, and rejects (returns None) unless
       rendering `merged_d` as ONE <path> is pixel-EXACT (see
       `_render_equivalent`/`_RENDER_EQUIVALENCE_MAX_DIFF_PX` -- an
       empirical sweep of every real multi-path candidate across all four
       pinned Track D2 sources found no middle ground to build a nonzero
       tolerance out of: every genuinely safe merge rendered byte-
       identical, every corrupt one differed by 1+ pixels) to rendering
       the same survivors as separate sibling <path> elements at the same
       viewBox. This is necessary because fill-rule is resolved PER
       `<path>` over ALL of that path's own subpaths TOGETHER: two
       overlapping same-fill shapes that each paint solid on their own can
       cancel to a hole once folded into one multi-subpath path even
       though every subpath is a plain absolute `M` and nothing above
       rejected it -- this hollowed out shipped icons before this gate
       existed (docs/code-review-2026-08.md M5/M6; e.g.
       tabler_arrow_big_left_line's solid arrow rendered as a hollow
       outline). The check is a REAL render through the same resvg call
       sequence `rasterize_check`/`symbol_object` use, not a geometric
       analysis, because that is the only way to actually decide whether a
       merge changed the winding outcome -- though it is still bounded by
       the 24x24 raster it renders at: a real divergence thin enough to
       vanish at that resolution (one M5-named icon, see
       `_RENDER_EQUIVALENCE_MAX_DIFF_PX`'s comment) isn't something any
       pixel-comparison gate at this size can catch.
    5. Returns `(merged_d, fill_rule)`, where `fill_rule` is "evenodd" if
       ANY surviving path explicitly declares `fill-rule="evenodd"` (the
       whole merged shape must honor it for that path's hole geometry to
       survive the merge -- see README.md's "hole-shaped icon" spot-check
       note), else "nonzero" -- returned explicitly (never left implicit)
       so callers always emit an explicit `fill-rule` attribute rather than
       silently depending on SVG's default, the same reasoning
       fetch_lucide.py's own `_build_svg_document` already documents.

       This also *subsumes* the single-survivor case (the common one, most
       of these sources' icons stay single-path even after step 1): unlike
       extract_single_path_d, a lone survivor's own `fill-rule="evenodd"`
       (if it declares one) is preserved into the return value instead of
       silently discarded -- verified in practice against Bootstrap's own
       fill icons, ~70 of which declare fill-rule="evenodd" on a SINGLE
       <path> for ring/hole shapes (e.g. heart-fill.svg's cardioid cusp).
       A lone survivor never goes through step 4's render-equivalence
       gate -- there is nothing to merge, so nothing can change.
    """
    if _OTHER_ELEMENT_RE.search(svg_text):
        return None
    kept = []
    for element in _PATH_ELEMENT_RE.findall(svg_text):
        attrs = _path_attrs(element)
        if attrs.get("fill") == "none":
            continue
        if "d" not in attrs:
            continue
        kept.append(attrs)
    if not kept:
        return None
    fills = {a["fill"] for a in kept if "fill" in a}
    if len(fills) > 1:
        return None
    if any(a.get("stroke", "none") != "none" for a in kept):
        return None
    if any("transform" in a for a in kept):
        return None
    if any(a["d"].lstrip().startswith("m") for a in kept[1:]):
        return None
    fill_rule = "evenodd" if any(a.get("fill-rule") == "evenodd" for a in kept) else "nonzero"
    merged_d = " ".join(a["d"] for a in kept)
    if len(kept) > 1 and not _render_equivalent(kept, merged_d, fill_rule):
        return None
    return merged_d, fill_rule


# classify_by_keyword()'s bucket -> token-set table, applied in this fixed
# priority order (first bucket with a matching token wins -- e.g.
# "battery-warning" lands electrical via "battery" before safety's "warning"
# is ever checked, the same priority-order approach lucide_ids.txt's header
# documents its own from-scratch keyword-map having used). "general" and
# "misc" are deliberately not table-driven: "general" is reserved for
# hand-curated sources (the legacy 60 / Material's selection, see
# common.VALID_CATEGORIES and the pipeline README), and "misc" is the
# fallback for a token set that matches nothing below, not a bucket this
# table can itself decide *into*.
_KEYWORD_CATEGORY_TABLE: tuple[tuple[str, frozenset[str]], ...] = (
    ("electrical", frozenset({
        "battery", "batteries", "bolt", "plug", "plugged", "outlet", "socket",
        "volt", "voltage", "watt", "amp", "ampere", "amperage", "circuit",
        "resistor", "capacitor", "solar", "charging", "charge", "charger",
        "fuse", "breaker", "electric", "electrical", "electricity",
        "lightning", "cable", "wire", "wiring", "plugin",
    })),
    ("network", frozenset({
        "wifi", "bluetooth", "router", "signal", "cloud", "server", "dns",
        "lan", "wan", "vpn", "ethernet", "network", "hotspot", "satellite",
        "antenna", "rss", "nfc", "modem", "gateway", "node", "sim",
        "cellular", "airplay", "cast", "rfid",
    })),
    ("av", frozenset({
        "camera", "video", "film", "movie", "music", "headphone",
        "headphones", "headset", "speaker", "volume", "mic", "microphone",
        "play", "pause", "record", "tv", "television", "monitor", "screen",
        "projector", "radio", "podcast", "photo", "photos", "image",
        "gallery", "disc", "album", "audio", "sound", "media", "subtitle",
        "subtitles", "clapperboard", "equalizer", "broadcast",
    })),
    ("arrow", frozenset({"arrow", "arrows", "chevron", "chevrons", "caret"})),
    ("safety", frozenset({
        "alert", "warning", "danger", "hazard", "shield", "alarm", "fire",
        "smoke", "extinguisher", "emergency", "biohazard", "radiation",
        "radioactive", "caution", "siren", "helmet", "protect",
        "protection", "security", "secure", "lock", "unlock", "padlock",
        "key", "exclamation", "hazmat", "evacuation", "panic", "forbidden",
        "prohibited",
    })),
)


def classify_by_keyword(
    tokens: Iterable[str], *, overrides: Mapping[str, str] | None = None, base_id: str = ""
) -> str:
    """Deterministic, priority-ordered keyword-map from a bag of lowercase
    tokens (an id's own hyphen/underscore-split words, optionally unioned
    with richer metadata like a source's own free-text tags -- see
    fetch_tabler.py, which folds in icons.json's `tags` array) to one of
    common.VALID_CATEGORIES' five domain buckets, or "misc" if nothing
    matches. Shared by fetch_bootstrap.py and fetch_fluent.py (neither
    source ships category metadata) and fetch_tabler.py (as the fallback
    for an icon icons.json has no usable category for); fetch_remix.py
    doesn't need this at all, since Remix ships its own folder-per-category
    layout (a strictly better signal than guessing from tokens -- see
    fetch_remix.py's module docstring).

    `overrides`, if given, is checked FIRST against `base_id` (the
    underscore-joined manifest id, e.g. "cable_car") and short-circuits the
    whole token walk when it matches -- for the small, hand-picked set of
    ids where a bare token would land the wrong bucket (the same escape
    hatch lucide_ids.txt's own header documents needing, e.g. "cable-car"
    is a vehicle, not electrical wiring, even though "cable" alone is in
    the electrical token set above).

    Absent an override, walks `_KEYWORD_CATEGORY_TABLE` in its fixed
    (electrical, network, av, arrow, safety) priority order and returns the
    first bucket whose token set intersects `tokens`; "misc" if none do.
    """
    if overrides and base_id in overrides:
        return overrides[base_id]
    token_set = {t.lower() for t in tokens}
    for category, keywords in _KEYWORD_CATEGORY_TABLE:
        if token_set & keywords:
            return category
    return "misc"


def validate_shape(symbol_id: str, filename: str, svg_text: str) -> None:
    """Re-runs the EXACT same checks render/symbols.py's loader applies at
    load time (single <path>, viewBox="0 0 24 24", no style/font-family) by
    calling its private `_validate_symbol_svg` directly -- so this pipeline
    can never accept a file the runtime loader would then reject. Raises
    ValueError naming what's wrong (propagates from _validate_symbol_svg).
    """
    info = SymbolInfo(
        id=symbol_id, name=symbol_id, tags=[], path=filename,
        category="misc", source="pipeline-validation", license="",
    )
    _validate_symbol_svg(info, svg_text)


# extract_fill_path's render-equivalence gate (step 4 of its docstring):
# how many of the 24x24 = 576 raster pixels are allowed to differ between
# the merged candidate and the same survivors drawn as separate siblings
# before the merge is rejected as NOT equivalent. Set to 0 (exact match
# required), not a hedge value, from an empirical sweep of every real
# multi-path candidate across all four pinned Track D2 tarballs
# (docs/code-review-2026-08.md's own four sources): 398 candidates total
# (229 Tabler, 149 Bootstrap, 0 Remix -- Remix's curated set never has 2+
# real glyph paths -- 20 Fluent), of which every genuinely safe one
# (disjoint survivors, or an overlap whose winding direction happens not
# to matter) rendered BYTE-IDENTICAL (0 differing pixels) between the
# merged and sibling forms, while every winding/fill-rule corruption
# case -- including the review's own H3/M5 names -- differed by 1 to 66
# pixels (tabler_sunrise 1px, bootstrap sign-railroad/rocket-takeoff/
# sign-dead-end 1px, bootstrap sign-do-not-enter/sign-stop/sign-yield 2px,
# tabler_sitemap 12px, tabler_escalator_up 61px,
# tabler_arrow_big_left_line 66px). There is no observed middle ground at
# this resolution to build a tolerance out of -- a nonzero threshold would
# only let the smaller real corruptions back through (tabler_sunrise's
# 1px is the whole reason this is 0 and not e.g. 2). One known gap this
# still can't see: bootstrap_envelope_open_heart (also named in M5)
# rendered pixel-IDENTICAL between merged and sibling forms at every
# raster size checked (24 through 192px, with and without the source's
# scale(1.5) normalization transform) -- if that icon's divergence is
# real, it's below what any practical raster can distinguish, so this
# gate (at any tolerance) can't act on it; it ships unchanged.
_RENDER_EQUIVALENCE_MAX_DIFF_PX = 0


def _rasterize_fragment_24(body: str) -> Image.Image:
    """Renders an arbitrary sibling-element SVG fragment (no outer <svg>
    wrapper of its own) at 24x24 through the exact resvg call sequence
    test_symbols.py's own rasterize test and symbol_object() use
    (RenderedLabel/_svg_document/rasterize) -- the shared rasterize
    primitive behind both `rasterize_check` (one candidate, ink+background)
    and `_render_equivalent` (two candidates, pixel comparison).
    """
    label = RenderedLabel(svg=_svg_document(24, 24, f"<g>{body}</g>"), width_px=24, height_px=24)
    return rasterize(label)


def _render_equivalent(kept: list[dict[str, str]], merged_d: str, fill_rule: str) -> bool:
    """The M5/M6 render-equivalence gate: True if rendering `merged_d` as
    ONE <path fill-rule=fill_rule> rasterizes the same (within
    `_RENDER_EQUIVALENCE_MAX_DIFF_PX`) as rendering every entry of `kept`
    as its OWN separate sibling <path>, each keeping its own individually
    declared `fill-rule` (defaulting to "nonzero", SVG's own default, when
    a survivor doesn't declare one) -- the exact semantics those paths had
    in the original, unmerged source document. Neither render carries the
    source's `fill` color (irrelevant to ink-vs-background, and
    build_svg_document never emits one either) or any coordinate
    `transform` (extract_fill_path already rejects any survivor that has
    one, and a transform applied identically to both renders can't change
    whether they agree).

    This is what actually decides every multi-path merge: fill-rule is
    resolved per-<path> over ALL of that path's own subpaths together, so
    two overlapping same-fill shapes that stay solid as separate elements
    can cancel to a hole once concatenated into one path's subpath list --
    a purely geometric analysis of the `d` strings can't tell safe merges
    from that failure mode nearly as reliably as just rendering both and
    comparing pixels.
    """
    merged_body = f'<path d="{merged_d}" fill-rule="{fill_rule}"/>'
    siblings_body = "".join(
        f'<path d="{a["d"]}" fill-rule="{a.get("fill-rule", "nonzero")}"/>' for a in kept
    )
    merged_img = _rasterize_fragment_24(merged_body)
    siblings_img = _rasterize_fragment_24(siblings_body)
    diff = sum(
        1
        for a, b in zip(merged_img.getdata(), siblings_img.getdata(), strict=True)
        if a != b
    )
    return diff <= _RENDER_EQUIVALENCE_MAX_DIFF_PX


def rasterize_check(svg_text: str) -> bool:
    """The pipeline-time exhaustive rasterize gate: renders `svg_text` (a
    complete, already shape-valid 24x24 <svg> document) through the REAL
    resvg pipeline (the same `_rasterize_fragment_24` primitive
    `_render_equivalent` uses -- the identical call sequence
    test_symbols.py's own rasterize test and symbol_object() itself use)
    and requires BOTH some ink (extrema[0] == 0) AND some untouched
    background (extrema[1] == 255).

    The second half of that requirement is deliberate, not just a
    non-blank check: a normalization bug that accidentally keeps the WRONG
    layer of a source SVG (e.g. a background instead of a pictogram, for a
    hypothetical future multi-layer source -- see README.md's "Adding a
    source" section) tends to produce a solid fully-inked 24x24 square,
    which a bare "not blank" check would wrongly accept. Every legitimate
    icon in this catalog has visible padding around its glyph, so requiring
    some surviving white pixels catches that failure mode too.
    """
    inner_match = _SVG_INNER_RE.match(svg_text.strip())
    if inner_match is None:
        return False
    img = _rasterize_fragment_24(inner_match.group(1))
    return img.getextrema() == (0, 255)


def load_index() -> list[dict]:
    if not INDEX_PATH.is_file():
        raise RuntimeError(f"symbols index not found: {INDEX_PATH}")
    return json.loads(INDEX_PATH.read_text())


def save_index(entries: list[dict]) -> None:
    for entry in entries:
        if set(entry) != MANIFEST_KEYS:
            raise ValueError(
                f"entry {entry.get('id')!r} has keys {set(entry)}, expected {MANIFEST_KEYS}"
            )
        if entry["category"] not in VALID_CATEGORIES:
            raise ValueError(f"entry {entry['id']!r} has invalid category {entry['category']!r}")
        if not entry["source"]:
            raise ValueError(f"entry {entry['id']!r} has an empty source field")
        if not entry["license"]:
            raise ValueError(f"entry {entry['id']!r} has an empty license field")
    INDEX_PATH.write_text(json.dumps(entries, indent=2) + "\n")


def _legacy_category_from_tags(tags: list[str]) -> str:
    for anchor in ("electrical", "network", "av", "arrow"):
        if anchor in tags:
            return anchor
    return "misc"  # the existing 60's own historical catch-all tag


def upgrade_legacy_entries(entries: list[dict]) -> list[dict]:
    """Existing-60 entries were written before manifest v2 (just {id, name,
    tags, path}) -- adds category/source/license in place (same id/name/
    tags/path, same .svg files, byte-for-byte untouched) so index.json is
    uniformly v2-shaped. Idempotent: an entry that already has all v2 keys
    (including a re-run over entries this same function already upgraded)
    passes through unchanged.
    """
    upgraded = []
    for entry in entries:
        if set(entry) == MANIFEST_KEYS:
            upgraded.append(entry)
            continue
        if set(entry) != _LEGACY_KEYS:
            raise ValueError(f"entry {entry.get('id')!r} has an unrecognized key set {set(entry)}")
        upgraded.append({
            **entry,
            "category": _legacy_category_from_tags(entry["tags"]),
            "source": _LEGACY_MATERIAL_SOURCE,
            "license": _LEGACY_MATERIAL_LICENSE,
        })
    return upgraded


def emit_source(*, prefix: str, candidates: list[Candidate]) -> SourceReport:
    """Idempotently (re-)generates one source's slice of the catalog:

    1. Deletes every `<prefix>_*.svg` file under SYMBOLS_DIR and every
       index.json entry whose id starts with `<prefix>_` (so re-running a
       fetch script against a shrunk/changed curated id-list can't leave
       stale files or manifest entries behind).
    2. For each candidate (already normalized+shape-valid by the caller):
       runs the pipeline-time rasterize gate (see rasterize_check's
       docstring); accepts it (writes the .svg file, builds its manifest
       entry) or skips+logs it.
    3. Upgrades any pre-v2 legacy entries still in index.json, merges in the
       newly-accepted entries, and writes index.json back out.

    Returns a SourceReport (accepted ids, skipped (id, reason) pairs) --
    every fetch_*.py prints report.summary() so a run's skip log is always
    visible, matching the brief's "log skips" requirement.
    """
    SYMBOLS_DIR.mkdir(parents=True, exist_ok=True)
    stale_svgs = list(SYMBOLS_DIR.glob(f"{prefix}_*.svg"))
    for f in stale_svgs:
        f.unlink()

    entries = load_index() if INDEX_PATH.is_file() else []
    entries = upgrade_legacy_entries(entries)
    entries = [e for e in entries if not e["id"].startswith(f"{prefix}_")]

    report = SourceReport(prefix=prefix, accepted=[], skipped=[])
    for cand in candidates:
        if not _ID_CHARSET_RE.fullmatch(cand.base_id):
            raise ValueError(
                f"{prefix}_{cand.base_id}: base_id {cand.base_id!r} must match "
                f"{_ID_CHARSET_RE.pattern!r} (lowercase ascii, digits, underscore only) -- "
                "a curated id list produced something outside this charset, fix the "
                "source id list rather than the generated id"
            )
        full_id = f"{prefix}_{cand.base_id}"
        filename = f"{full_id}.svg"
        try:
            validate_shape(full_id, filename, cand.svg_text)
        except ValueError as exc:
            report.skipped.append((full_id, f"shape validation failed: {exc}"))
            continue
        if not rasterize_check(cand.svg_text):
            report.skipped.append((full_id, "rasterize gate failed (blank or fully solid)"))
            continue
        (SYMBOLS_DIR / filename).write_text(cand.svg_text)
        entries.append({
            "id": full_id,
            "name": cand.name,
            "tags": cand.tags,
            "path": filename,
            "category": cand.category,
            "source": cand.source,
            "license": cand.license,
        })
        report.accepted.append(full_id)

    # Sorted by id rather than left in per-source append order: index.json's
    # on-disk order would otherwise encode which fetch_*.py happened to run
    # last (this source's entries always land at the end of the list right
    # before this point), making a semantically-identical catalog produce a
    # different diff depending on invocation order. Sorting makes the
    # committed file byte-identical regardless of which script ran when --
    # see README.md's "reproducible ... given the pinned versions" claim.
    entries.sort(key=lambda e: e["id"])
    save_index(entries)
    return report
