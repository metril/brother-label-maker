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
