"""Tests for GET /api/health and GET /api/label-types."""

from __future__ import annotations


async def test_health_reports_ok_and_printer_mode(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "printer_mode": "mock"}


async def test_label_types_contains_text_with_schema(client):
    resp = await client.get("/api/label-types")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)

    text_type = next(t for t in body if t["type"] == "text")
    assert text_type["title"] == "Text"
    assert "lines" in text_type["params_schema"]["properties"]


async def test_label_types_lists_four_types_with_categories(client):
    # Task 2.2: patch_panel/punch_down/faceplate join "text" -- exactly
    # these four (the registry-isolation fixture in conftest.py, see
    # test_render_registry.py, keeps test-only "dummy" types from leaking
    # into this count).
    resp = await client.get("/api/label-types")
    body = resp.json()
    by_type = {t["type"]: t for t in body}
    assert by_type.keys() == {"text", "patch_panel", "punch_down", "faceplate"}

    assert by_type["text"]["category"] == "general"
    for network_type in ("patch_panel", "punch_down", "faceplate"):
        assert by_type[network_type]["category"] == "network"

    # min_tape_mm is always present (None = usable on any tape width).
    assert all(t["min_tape_mm"] is None for t in body)
