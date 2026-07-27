"""Tests for GET /api/fonts and GET /api/tapes -- the two static catalog
endpoints B2 adds so the frontend can stop hardcoding font families
(stores/designer.ts's old FONT_FAMILIES) and TZe widths (TZE_WIDTHS_MM)
that had to be hand-kept in lockstep with the backend's own tables."""

from __future__ import annotations

from labelmaker.driver.geometry import dots_to_mm


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
