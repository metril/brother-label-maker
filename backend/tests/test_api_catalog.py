"""Tests for GET /api/fonts, GET /api/tapes, GET /api/symbols, and
GET /api/symbols/{id} -- the static catalog endpoints B2/2.7 add so the
frontend can stop hardcoding font families (stores/designer.ts's old
FONT_FAMILIES), TZe widths (TZE_WIDTHS_MM), and (2.7) the symbol icon
library that had to be hand-kept in lockstep with the backend's own
tables."""

from __future__ import annotations

from labelmaker.driver.geometry import dots_to_mm
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
