"""Tests for GET /api/fonts, GET /api/tapes, GET /api/symbols, and
GET /api/symbols/{id} -- the static catalog endpoints B2/2.7 add so the
frontend can stop hardcoding font families (stores/designer.ts's old
FONT_FAMILIES), TZe widths (TZE_WIDTHS_MM), and (2.7) the symbol icon
library that had to be hand-kept in lockstep with the backend's own
tables.

The "H4/H5" tests below (docs/code-review-2026-08.md) cover the two
symbol routes' serving-cost fixes: GET /api/symbols returning
render/symbols.py's pre-encoded, mtime-cached response bytes instead of
paying a deep-copy + re-encode of every model per request (H4), and both
routes' ETag/Cache-Control/conditional-GET/gzip behavior (H5). The
mtime-invalidation test replicates -- rather than imports or edits --
test_symbols.py's own tmp-dir monkeypatch pattern
(test_list_symbols_and_get_symbol_info_invalidate_on_index_mtime_change),
since that file is a different agent's scope; this file is a route-level
test hitting the same mechanism through the ASGI client instead of calling
render/symbols.py's functions directly.
"""

from __future__ import annotations

import json
import os

from labelmaker.driver.geometry import dots_to_mm
from labelmaker.render import symbols as symbols_module
from labelmaker.render.symbols import list_symbols


async def test_fonts_returns_the_four_bundled_families_with_expected_shape(client):
    resp = await client.get("/api/fonts")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 4
    for font in body:
        assert set(font.keys()) == {"family", "display_name", "monospace", "has_bold"}

    by_family = {f["family"]: f for f in body}
    assert by_family.keys() == {"Inter", "Roboto Condensed", "JetBrains Mono", "DejaVu Sans"}
    assert by_family["JetBrains Mono"]["monospace"] is True
    assert by_family["Inter"]["monospace"] is False
    assert all(f["has_bold"] for f in body)


async def test_tapes_returns_all_fifteen_tze_and_hse(client):
    resp = await client.get("/api/tapes")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 15
    for tape in body:
        assert set(tape.keys()) == {
            "nominal_mm",
            "family",
            "print_dots",
            "print_mm",
            "max_length_mm",
        }
        assert tape["family"] in {"tze", "hse_2_1", "hse_3_1"}


async def test_tapes_tze_family_has_the_six_expected_widths_in_order(client):
    resp = await client.get("/api/tapes")
    body = resp.json()
    tze = [t for t in body if t["family"] == "tze"]
    assert [t["nominal_mm"] for t in tze] == [3.5, 6, 9, 12, 18, 24]


async def test_tapes_print_mm_is_dots_to_mm_of_print_dots_rounded_to_0_1(client):
    resp = await client.get("/api/tapes")
    body = resp.json()
    tape_24mm_tze = next(t for t in body if t["family"] == "tze" and t["nominal_mm"] == 24)
    assert tape_24mm_tze["print_dots"] == 128
    assert tape_24mm_tze["print_mm"] == round(dots_to_mm(128), 1)


async def test_tapes_max_length_mm_matches_family(client):
    resp = await client.get("/api/tapes")
    body = resp.json()
    tze = next(t for t in body if t["family"] == "tze" and t["nominal_mm"] == 24)
    hse = next(t for t in body if t["family"] == "hse_2_1" and t["nominal_mm"] == 23.6)
    assert tze["max_length_mm"] == 1000.0
    assert hse["max_length_mm"] == 500.0


# --- Symbols (task 2.7) ------------------------------------------------------


async def test_symbols_returns_the_full_curated_catalog(client):
    resp = await client.get("/api/symbols")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == len(list_symbols())
    # Manifest v2 (commit 7's symbols pipeline): gained category/source/
    # license alongside the original id/name/tags/path -- additive only, so
    # this stays an exact-key-set check rather than a subset check (a
    # regression that silently drops one of the new fields from the API
    # response, while list_symbols() itself still has it, should fail here).
    for entry in body:
        assert set(entry.keys()) == {"id", "name", "tags", "path", "category", "source", "license"}
    ids = {entry["id"] for entry in body}
    assert "bolt" in ids
    assert "wifi" in ids


async def test_symbol_svg_returns_the_raw_svg_for_a_known_id(client):
    resp = await client.get("/api/symbols/bolt")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"
    assert resp.text.strip().startswith("<svg")
    assert 'viewBox="0 0 24 24"' in resp.text


async def test_symbol_svg_unknown_id_returns_404(client):
    resp = await client.get("/api/symbols/not-a-real-icon")
    assert resp.status_code == 404


# --- H4/H5: serving-cost fixes (docs/code-review-2026-08.md) ----------------


def _write_symbols_index(tmp_path, entries: list[dict]) -> None:
    (tmp_path / "index.json").write_text(json.dumps(entries))


async def test_symbols_route_serves_cached_bytes_and_invalidates_on_index_mtime_change(
    client, monkeypatch, tmp_path
):
    """H4: GET /api/symbols must go through list_symbols_json()'s
    pre-encoded-bytes cache, keyed on index.json's (path, mtime_ns) --
    same identity as render/symbols.py's `_cache_key()`. This replicates
    test_symbols.py's mtime-invalidation pattern at the route level: a
    request must reflect a rewritten index.json (with its mtime bumped)
    on the very next call, with no explicit invalidation, and the route's
    ETag must move in lockstep with the cached bytes.
    """
    entry_a = {
        "id": "a",
        "name": "A",
        "tags": [],
        "path": "a.svg",
        "category": "misc",
        "source": "test",
        "license": "test",
    }
    _write_symbols_index(tmp_path, [entry_a])
    (tmp_path / "a.svg").write_text('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>')
    # L9 (2026-08 review): router_labels.py no longer imports its own
    # SYMBOLS_DIR name -- GET /api/symbols/{id} resolves the file through
    # symbols.resolve_symbol_path(), which reads THIS module's SYMBOLS_DIR
    # live at call time, so patching it here is the only patch needed (the
    # route-level monkeypatch this test previously also needed is gone).
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    resp = await client.get("/api/symbols")
    assert resp.status_code == 200
    assert [entry["id"] for entry in resp.json()] == ["a"]
    first_etag = resp.headers["etag"]

    # Rewrite index.json with a second entry and force a distinct mtime_ns
    # (os.utime rather than trusting two back-to-back writes to land in
    # different nanosecond buckets on every filesystem) -- the exact
    # scenario the cache key is meant to detect: same path, changed content.
    entry_b = {
        "id": "b",
        "name": "B",
        "tags": [],
        "path": "b.svg",
        "category": "misc",
        "source": "test",
        "license": "test",
    }
    _write_symbols_index(tmp_path, [entry_a, entry_b])
    (tmp_path / "b.svg").write_text('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>')
    index_path = tmp_path / "index.json"
    newer_ns = index_path.stat().st_mtime_ns + 1_000_000_000  # +1s, unambiguously newer
    os.utime(index_path, ns=(newer_ns, newer_ns))

    resp2 = await client.get("/api/symbols")
    assert resp2.status_code == 200
    assert {entry["id"] for entry in resp2.json()} == {"a", "b"}, (
        "GET /api/symbols served stale cached bytes across an index.json mtime change"
    )
    assert resp2.headers["etag"] != first_etag, "ETag did not change with the cached bytes"


async def test_symbols_route_sets_etag_and_cache_control(client):
    resp = await client.get("/api/symbols")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=86400"
    assert resp.headers["etag"].startswith('W/"')


async def test_symbols_route_returns_304_when_if_none_match_matches(client):
    resp = await client.get("/api/symbols")
    etag = resp.headers["etag"]

    resp2 = await client.get("/api/symbols", headers={"If-None-Match": etag})
    assert resp2.status_code == 304
    assert resp2.headers["etag"] == etag
    assert resp2.content == b""


async def test_symbols_route_is_gzip_compressed_when_accepted(client):
    resp = await client.get("/api/symbols", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    # `content-length` reflects the bytes actually sent over the wire
    # (compressed); httpx transparently decodes the body it hands back via
    # `.content`/`.json()`, so comparing the two is a real compression-ratio
    # check, not a tautology. 1.5MB of this catalog's JSON gzips ~10x
    # (H5's own measurement); assert a conservative fraction of that.
    decoded_len = len(resp.content)
    wire_len = int(resp.headers["content-length"])
    assert wire_len < decoded_len / 3, (
        f"expected gzip to shrink the response by more than 3x, got {decoded_len} -> {wire_len}"
    )


async def test_symbols_route_not_compressed_when_gzip_not_accepted(client):
    resp = await client.get("/api/symbols", headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers


async def test_symbol_svg_route_sets_etag_last_modified_and_cache_control(client):
    resp = await client.get("/api/symbols/bolt")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=86400"
    assert resp.headers["etag"].startswith('W/"')
    assert "last-modified" in resp.headers


async def test_symbol_svg_route_returns_304_when_if_none_match_matches(client):
    resp = await client.get("/api/symbols/bolt")
    etag = resp.headers["etag"]

    resp2 = await client.get("/api/symbols/bolt", headers={"If-None-Match": etag})
    assert resp2.status_code == 304
    assert resp2.headers["etag"] == etag
    assert resp2.content == b""


# --- L9 (2026-08 review): SVGs served as active content -- validation and --
# path containment on the serve path, not just at render time.


async def test_symbol_svg_route_sets_nosniff_header_for_a_normal_symbol(client):
    resp = await client.get("/api/symbols/bolt")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_symbol_svg_route_rejects_script_sibling(client, monkeypatch, tmp_path):
    entries = [
        {
            "id": "hostile_script",
            "name": "Hostile",
            "tags": [],
            "path": "hostile.svg",
            "category": "misc",
            "source": "test",
            "license": "test",
        }
    ]
    _write_symbols_index(tmp_path, entries)
    (tmp_path / "hostile.svg").write_text(
        '<svg viewBox="0 0 24 24"><path d="M0 0"/><script>alert(1)</script></svg>'
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    resp = await client.get("/api/symbols/hostile_script")
    assert resp.status_code == 404


async def test_symbol_svg_route_rejects_onload_attribute(client, monkeypatch, tmp_path):
    entries = [
        {
            "id": "hostile_onload",
            "name": "Hostile",
            "tags": [],
            "path": "hostile.svg",
            "category": "misc",
            "source": "test",
            "license": "test",
        }
    ]
    _write_symbols_index(tmp_path, entries)
    (tmp_path / "hostile.svg").write_text(
        '<svg viewBox="0 0 24 24" onload="alert(1)"><path d="M0 0"/></svg>'
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    resp = await client.get("/api/symbols/hostile_onload")
    assert resp.status_code == 404


async def test_symbol_svg_route_rejects_xlink_href(client, monkeypatch, tmp_path):
    entries = [
        {
            "id": "hostile_xlink",
            "name": "Hostile",
            "tags": [],
            "path": "hostile.svg",
            "category": "misc",
            "source": "test",
            "license": "test",
        }
    ]
    _write_symbols_index(tmp_path, entries)
    (tmp_path / "hostile.svg").write_text(
        '<svg viewBox="0 0 24 24"><path d="M0 0"/>'
        '<image xlink:href="https://evil.example/x.png"/></svg>'
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    resp = await client.get("/api/symbols/hostile_xlink")
    assert resp.status_code == 404


async def test_symbol_svg_route_404s_when_manifest_path_escapes_symbols_dir(
    client, monkeypatch, tmp_path
):
    """resolve_symbol_path() containment-checks the manifest's `path` field
    the same way render/images.py's image_path() does for uploads -- a bad
    manifest entry (or a symlink) that resolves outside SYMBOLS_DIR must
    404, never serve whatever it points at."""
    outside = tmp_path.parent / "outside-symbols"
    outside.mkdir(parents=True, exist_ok=True)
    secret = outside / "secret.svg"
    secret.write_text('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>')

    entries = [
        {
            "id": "escaping",
            "name": "Escaping",
            "tags": [],
            "path": "../outside-symbols/secret.svg",
            "category": "misc",
            "source": "test",
            "license": "test",
        }
    ]
    _write_symbols_index(tmp_path, entries)
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)

    resp = await client.get("/api/symbols/escaping")
    assert resp.status_code == 404
