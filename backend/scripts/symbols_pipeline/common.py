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


def build_svg_document(d: str, transform: str) -> str:
    """Wraps a raw (verbatim, un-rewritten) path `d` string in the single
    viewBox="0 0 24 24" <svg> document shape render/symbols.py requires,
    applying `transform` to reconcile the source's native coordinate system
    with the 0..24 square -- same recipe as the existing 60 (see
    assets/symbols/LICENSES.md's "Normalization" section), just parameterized
    per source since Material (0,-960,960,960) and Phosphor (0,0,256,256)
    each need a different transform string.
    """
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path d="{d}" transform="{transform}"/></svg>'
    )


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


def rasterize_check(svg_text: str) -> bool:
    """The pipeline-time exhaustive rasterize gate: renders `svg_text` (a
    complete, already shape-valid 24x24 <svg> document) through the REAL
    resvg pipeline (RenderedLabel/_svg_document/rasterize -- the identical
    call sequence test_symbols.py's own rasterize test and symbol_object()
    itself use) and requires BOTH some ink (extrema[0] == 0) AND some
    untouched background (extrema[1] == 255).

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
    inner = inner_match.group(1)
    label = RenderedLabel(svg=_svg_document(24, 24, f"<g>{inner}</g>"), width_px=24, height_px=24)
    img = rasterize(label)
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
