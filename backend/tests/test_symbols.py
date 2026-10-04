"""Tests for labelmaker.render.symbols: the curated icon library (task 2.7,
expanded to 1000+ icons across Material Symbols and Phosphor by commit 7's
symbols pipeline, backend/scripts/symbols_pipeline/) -- index parsing,
per-file asset integrity, mtime-keyed caching, and symbol_object()'s
placement/scaling.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

import pytest

from labelmaker.render import symbols as symbols_module
from labelmaker.render.document import RenderedLabel, _svg_document
from labelmaker.render.rasterize import rasterize
from labelmaker.render.symbols import (
    SYMBOLS_DIR,
    SymbolInfo,
    ensure_symbols_dir,
    get_symbol_info,
    list_symbols,
    symbol_object,
)

# The id "groups" the manifest can currently contain: the original 60
# (bare ids, no prefix) plus one prefix per pipeline source. Every test
# below that talks about "every source" means these groups. A new source
# must add its prefix here (the pipeline README's "Adding a source" step 8
# points at this tuple).
_SOURCE_PREFIXES = (
    "material_", "phosphor_", "lucide_", "tabler_", "remix_", "bootstrap_", "fluent_",
)


def _source_group(symbol_id: str) -> str:
    for prefix in _SOURCE_PREFIXES:
        if symbol_id.startswith(prefix):
            return prefix
    return "legacy"


# --- 1. ensure_symbols_dir() -------------------------------------------------


def test_ensure_symbols_dir_passes_when_present():
    ensure_symbols_dir()  # the real bundled directory -- no raise


def test_ensure_symbols_dir_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path / "does-not-exist")
    with pytest.raises(RuntimeError, match="symbols directory not found"):
        ensure_symbols_dir()


# --- 2. list_symbols() / index parsing --------------------------------------


def test_list_symbols_meets_floor_and_every_source_contributes():
    # Floors near committed reality, not just "greater than zero" -- tight
    # enough that a source silently dropping most of its entries (a bad
    # curated-id-list edit, a pipeline regression) fails this test, loose
    # enough that adding MORE ids to either *_ids.txt and re-running the
    # fetch script never breaks it. legacy is pinned exactly at 60: it's the
    # original hand-curated set (task 2.7) and nothing ever adds to or
    # removes from it (see fetch_*.py's "Backward compatibility" -- neither
    # script's stale-file glob ever touches a bare id). material_'s floor
    # (>= 700) reflects material_ids.txt post-dedup (see the pipeline README's
    # dedup note: 38 ids were dropped because a legacy bare id already covers
    # the same concept) -- currently 743. phosphor_'s floor (>= 50) reflects
    # phosphor_ids.txt's currently-curated 55. The four Track D2 full-set
    # sources' floors sit a little below their currently-committed counts
    # (same margin-for-later-edits reasoning): tabler_ (>= 1000, currently
    # 1050 -- down from 1054 pre-fix: docs/code-review-2026-08.md H3/M5's
    # extract_fill_path render-equivalence + relative-m gates now skip+log
    # arrow-big-left-line/escalator-up/sitemap/sunrise rather than shipping
    # them geometrically corrupt), remix_ (>= 1500, currently 1539 --
    # unaffected, Remix's curated set never has 2+ real glyph paths),
    # bootstrap_ (>= 630, LOWERED from 650 by the same H3/M5 fix -- currently
    # 648 curated / accepted, down from 669: circle-fill.svg's bare <circle>
    # plus 21 new skips, 15 relative-m house_*/cassette/cup_hot/layers ids
    # (H3) and 6 render-equivalence-gate rejects, sign-do-not-enter/
    # sign-stop/sign-yield/rocket-takeoff/sign-dead-end/sign-railroad (M5) --
    # see bootstrap_ids.txt's header), fluent_ (>= 2400, currently 2490
    # curated / 2484 accepted -- the flag_pride_* family's 4 genuinely
    # multi-color icons plus 2 new H3 relative-m skips, image_globe and
    # slide_eraser, are the skips, see fluent_ids.txt's header).
    infos = list_symbols()
    assert all(isinstance(i, SymbolInfo) for i in infos)

    by_group: dict[str, list[SymbolInfo]] = {}
    for info in infos:
        by_group.setdefault(_source_group(info.id), []).append(info)

    legacy_count = len(by_group.get("legacy", []))
    assert legacy_count == 60, f"legacy group must stay exactly 60, found {legacy_count}"

    floors = {
        "material_": 700, "phosphor_": 50,
        "tabler_": 1000, "remix_": 1500, "bootstrap_": 630, "fluent_": 2400,
    }
    for group, floor in floors.items():
        count = len(by_group.get(group, []))
        assert count >= floor, f"source group {group!r} has {count} symbols, expected >= {floor}"


def test_list_symbols_ids_are_unique():
    ids = [i.id for i in list_symbols()]
    assert len(ids) == len(set(ids))


def test_list_symbols_covers_expected_categories_via_tags():
    # "safety" is deliberately not in this list: it's a valid manifest
    # category (see common.VALID_CATEGORIES) reserved for a possible future
    # source, but nothing currently populates it -- see
    # backend/scripts/symbols_pipeline/README.md.
    all_tags = {tag for info in list_symbols() for tag in info.tags}
    for expected in ("electrical", "network", "av", "arrow", "misc"):
        assert expected in all_tags, f"no symbol tagged {expected!r}"


def test_list_symbols_every_entry_has_a_non_empty_license():
    for info in list_symbols():
        assert info.license, f"{info.id}: empty license field"


def test_index_json_is_a_flat_list_of_the_documented_manifest_v2_shape():
    raw = json.loads((SYMBOLS_DIR / "index.json").read_text())
    assert isinstance(raw, list)
    valid_categories = {"general", "electrical", "network", "av", "arrow", "safety", "misc"}
    for entry in raw:
        assert set(entry) == {"id", "name", "tags", "path", "category", "source", "license"}
        assert entry["path"] == f"{entry['id']}.svg"
        bad_category = f"{entry['id']}: bad category {entry['category']!r}"
        assert entry["category"] in valid_categories, bad_category
        assert entry["source"], f"{entry['id']}: empty source field"
        assert entry["license"], f"{entry['id']}: empty license field"


# --- 2b. mtime-keyed caching -------------------------------------------------


def _write_index(tmp_path, entries: list[dict]) -> None:
    (tmp_path / "index.json").write_text(json.dumps(entries))


def test_list_symbols_and_get_symbol_info_invalidate_on_index_mtime_change(monkeypatch, tmp_path):
    entry_a = {
        "id": "a", "name": "A", "tags": [], "path": "a.svg",
        "category": "misc", "source": "test", "license": "test",
    }
    _write_index(tmp_path, [entry_a])
    (tmp_path / "a.svg").write_text('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>')
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    first = list_symbols()
    assert [i.id for i in first] == ["a"]
    assert get_symbol_info("a").id == "a"

    # Rewrite index.json with a second entry, forcing a distinct mtime_ns
    # (os.utime, rather than trusting two back-to-back writes to land in
    # different nanosecond buckets on every filesystem) -- this is the exact
    # scenario the cache key is meant to detect: same path, changed content.
    entry_b = {
        "id": "b", "name": "B", "tags": [], "path": "b.svg",
        "category": "misc", "source": "test", "license": "test",
    }
    _write_index(tmp_path, [entry_a, entry_b])
    (tmp_path / "b.svg").write_text('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>')
    index_path = tmp_path / "index.json"
    newer_ns = index_path.stat().st_mtime_ns + 1_000_000_000  # +1s, unambiguously newer
    os.utime(index_path, ns=(newer_ns, newer_ns))

    second = list_symbols()
    assert [i.id for i in second] == ["a", "b"], "list_symbols() served a stale cached value"
    assert get_symbol_info("b").id == "b", "get_symbol_info() served a stale cached value"


def test_list_symbols_returns_a_copy_callers_cant_use_to_corrupt_the_cache(monkeypatch, tmp_path):
    entry = {
        "id": "a", "name": "A", "tags": ["x"], "path": "a.svg",
        "category": "misc", "source": "test", "license": "test",
    }
    _write_index(tmp_path, [entry])
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    # 1. Appending to the returned LIST must not affect a later call.
    infos = list_symbols()
    extra = SymbolInfo(
        id="z", name="Z", tags=[], path="z.svg", category="misc", source="t", license="t"
    )
    infos.append(extra)
    assert [i.id for i in list_symbols()] == ["a"]

    # 2. Mutating a returned SymbolInfo's `.tags` (a mutable list field) must
    # not reach the cached instance either -- a `list(cached)` shallow copy
    # would pass check 1 above but still share the SAME SymbolInfo objects
    # (and their tags lists) with the cache, so this needs a real deep copy.
    infos = list_symbols()
    infos[0].tags.append("mutated-via-list-entry")
    assert list_symbols()[0].tags == ["x"], "list_symbols() leaked a mutable cached tags list"

    # 3. Same requirement for get_symbol_info(): it must never return the
    # cached instance itself.
    info = get_symbol_info("a")
    info.tags.append("mutated-via-get-symbol-info")
    assert get_symbol_info("a").tags == ["x"], "get_symbol_info() returned the cached instance"
    assert list_symbols()[0].tags == ["x"], "get_symbol_info() mutation leaked into list_symbols()"


# --- 3. Asset integrity: every listed file exists, is valid, 24x24 ---------


def test_every_indexed_symbol_file_exists():
    for info in list_symbols():
        path = SYMBOLS_DIR / info.path
        assert path.is_file(), f"{info.id}: {path} missing"
        assert path.stat().st_size > 0


_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"0 0 24 24"')
_PATH_RE = re.compile(r"<path\b")


def test_every_indexed_symbol_file_is_a_single_path_24x24_svg():
    for info in list_symbols():
        raw = (SYMBOLS_DIR / info.path).read_text()
        assert raw.strip().startswith("<svg"), f"{info.id}: doesn't start with <svg"
        assert raw.strip().endswith("</svg>"), f"{info.id}: doesn't end with </svg>"
        assert _VIEWBOX_RE.search(raw), f"{info.id}: missing viewBox=\"0 0 24 24\""
        assert len(_PATH_RE.findall(raw)) == 1, f"{info.id}: expected exactly one <path>"
        assert "style" not in raw, f"{info.id}: unexpected style attribute"
        assert "font-family" not in raw, f"{info.id}: unexpected font-family attribute"


_RASTERIZE_SAMPLE_SIZE = 100


def _stratified_rasterize_sample(infos: list[SymbolInfo]) -> list[SymbolInfo]:
    """A deterministic, hash-stratified sample targeting _RASTERIZE_SAMPLE_SIZE
    total. Deterministic (sha256 of the id, not `random`) so a failure is
    reproducible across runs/machines without pinning a seed; "stratified"
    means every source group gets some representation rather than a plain
    sort-by-hash-and-take-N-from-the-front risking one large source (e.g.
    material_*, ~700+ entries) crowding out a small one.

    This is deliberately a SAMPLE, not the full catalog: the pipeline itself
    already rasterize-gates every single file at generation time (see
    common.rasterize_check + backend/scripts/symbols_pipeline/README.md's
    "pipeline-time quality gate" section) -- this test is a regression check
    against the committed files drifting or bitrotting later, not the first
    line of defense. Set SYMBOLS_FULL_SWEEP=1 to check every file instead
    (slow: this rasterizes real SVGs through resvg one at a time).
    """
    if os.environ.get("SYMBOLS_FULL_SWEEP") == "1":
        return infos

    by_group: dict[str, list[SymbolInfo]] = {}
    for info in infos:
        by_group.setdefault(_source_group(info.id), []).append(info)
    for group in by_group.values():
        group.sort(key=lambda i: hashlib.sha256(i.id.encode()).hexdigest())

    sample: list[SymbolInfo] = []
    remaining_groups = [g for g in by_group.values() if g]
    per_group = max(_RASTERIZE_SAMPLE_SIZE // max(len(remaining_groups), 1), 1)
    for group in remaining_groups:
        sample.extend(group[:per_group])
    return sample


def test_indexed_symbol_files_render_nonblank_via_resvg():
    # Belt-and-suspenders over the string-shape check above: every sampled
    # file actually rasterizes to *some* ink, through the real resvg
    # pipeline, not just a string that superficially looks like valid SVG.
    # See _stratified_rasterize_sample()'s docstring for sample vs.
    # SYMBOLS_FULL_SWEEP=1 full-sweep semantics.
    sample = _stratified_rasterize_sample(list_symbols())
    assert sample, "sample is empty -- list_symbols() returned nothing?"
    for info in sample:
        svg_group = symbol_object(info.id, size_px=24)
        label = RenderedLabel(
            svg=_svg_document(24, 24, svg_group), width_px=24, height_px=24
        )
        img = rasterize(label)
        assert img.getextrema() != (255, 255), f"{info.id}: rendered blank"


# --- 4. get_symbol_info() ----------------------------------------------------


def test_get_symbol_info_returns_matching_entry():
    info = get_symbol_info("bolt")
    assert info.id == "bolt"
    assert info.path == "bolt.svg"


def test_get_symbol_info_unknown_id_raises_value_error_listing_count():
    with pytest.raises(ValueError, match="unknown symbol id 'not-a-real-icon'"):
        get_symbol_info("not-a-real-icon")


# --- 5. symbol_object(): placement + scaling --------------------------------


def test_symbol_object_returns_group_with_translate_and_scale():
    svg_group = symbol_object("bolt", size_px=48, x=10, y=20)
    assert svg_group.startswith("<g ")
    assert "translate(10,20)" in svg_group
    assert "scale(2)" in svg_group  # 48/24 == 2


def test_symbol_object_default_position_is_origin():
    svg_group = symbol_object("bolt", size_px=24)
    assert "translate(0,0)" in svg_group


def test_symbol_object_rejects_non_positive_size():
    with pytest.raises(ValueError, match="size_px"):
        symbol_object("bolt", size_px=0)


def test_symbol_object_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown symbol id"):
        symbol_object("not-a-real-icon", size_px=24)


def test_symbol_object_rasterizes_to_expected_size_and_position():
    # 24px icon placed at (10, 10) inside a 44x44 canvas: ink must appear
    # only within the [10, 34) x [10, 34) box, nowhere else.
    svg_group = symbol_object("close", size_px=24, x=10, y=10)
    label = RenderedLabel(svg=_svg_document(44, 44, svg_group), width_px=44, height_px=44)
    img = rasterize(label)
    assert img.getextrema() != (255, 255)

    def ink(x: int, y: int) -> bool:
        return img.getpixel((x, y)) == 0

    # Corners of the canvas, well outside the icon's box, must be blank.
    for x, y in [(0, 0), (43, 0), (0, 43), (43, 43)]:
        assert not ink(x, y), f"unexpected ink at ({x},{y})"


def test_symbol_object_larger_size_produces_more_ink_pixels():
    # A coarse but robust scaling sanity check: doubling size_px should
    # roughly quadruple the ink pixel count (area scales with size^2).
    def ink_count(size_px: int) -> int:
        canvas = size_px + 4
        svg_group = symbol_object("bolt", size_px=size_px, x=2, y=2)
        label = RenderedLabel(
            svg=_svg_document(canvas, canvas, svg_group), width_px=canvas, height_px=canvas
        )
        img = rasterize(label)
        return sum(1 for x in range(canvas) for y in range(canvas) if img.getpixel((x, y)) == 0)

    small = ink_count(24)
    large = ink_count(48)
    assert small > 0
    assert large > small * 2  # comfortably more than linear growth


# --- 6. Validation catches a deliberately-broken file (not just the real ---
# assets, which already pass) -- exercises _validate_symbol_svg's error
# paths directly via a monkeypatched SYMBOLS_DIR.


def _write_index_and_file(tmp_path, filename: str, svg_text: str):
    index = [{
        "id": "broken", "name": "Broken", "tags": ["misc"], "path": filename,
        "category": "misc", "source": "test", "license": "test",
    }]
    (tmp_path / "index.json").write_text(json.dumps(index))
    (tmp_path / filename).write_text(svg_text)


def test_symbol_object_raises_on_wrong_viewbox(monkeypatch, tmp_path):
    _write_index_and_file(
        tmp_path, "broken.svg", '<svg viewBox="0 0 48 48"><path d="M0 0"/></svg>'
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="viewBox"):
        symbol_object("broken", size_px=24)


def test_symbol_object_raises_on_multiple_paths(monkeypatch, tmp_path):
    _write_index_and_file(
        tmp_path,
        "broken.svg",
        '<svg viewBox="0 0 24 24"><path d="M0 0"/><path d="M1 1"/></svg>',
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        symbol_object("broken", size_px=24)


def test_symbol_object_raises_on_style_attribute(monkeypatch, tmp_path):
    _write_index_and_file(
        tmp_path,
        "broken.svg",
        '<svg viewBox="0 0 24 24"><path style="font-family: Arial" d="M0 0"/></svg>',
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="style/font-family"):
        symbol_object("broken", size_px=24)


def test_symbol_object_raises_on_missing_file(monkeypatch, tmp_path):
    index = [{
        "id": "ghost", "name": "Ghost", "tags": [], "path": "ghost.svg",
        "category": "misc", "source": "test", "license": "test",
    }]
    (tmp_path / "index.json").write_text(json.dumps(index))
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="symbol file missing"):
        symbol_object("ghost", size_px=24)
