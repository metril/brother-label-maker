"""Tests for GET /api/printer/status."""

from __future__ import annotations

import httpx

from labelmaker.config import AppConfig
from labelmaker.driver.transport import PrinterNotFoundError
from labelmaker.main import create_app


async def test_printer_status_mock_mode_reports_connected_reference_status(client):
    resp = await client.get("/api/printer/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["connected"] is True
    assert body["printer_mode"] == "mock"
    assert body["error"] is None
    assert body["status"]["media_width_mm"] == 24
    assert "raw_hex" in body["status"]
    assert len(bytes.fromhex(body["status"]["raw_hex"])) == 32
    assert body["status"]["is_e720bt"] is True


async def test_printer_status_includes_a_keep_alive_block(client):
    # commit 6: additive field -- present alongside every existing key
    # (connected/printer_mode/status/error), not replacing any of them.
    # keep_printer_awake defaults False (DB-only, no override stored), so
    # right after boot the poller has never actually attempted a poll yet.
    resp = await client.get("/api/printer/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["connected"] is True  # every other pre-existing key still present
    assert body["printer_mode"] == "mock"
    keep_alive = body["keep_alive"]
    assert keep_alive == {
        "enabled": False,
        "last_attempt_at": None,
        "last_result": None,
        "last_error": None,
    }


async def test_printer_status_usb_mode_no_device_reports_disconnected(tmp_path, monkeypatch):
    # No real USB hardware in CI/dev -- PyUsbTransport.open() raising
    # PrinterNotFoundError (its documented behavior when no device matches)
    # is the realistic no-printer-attached case this endpoint must turn into
    # a 200 {"connected": false, "error": "..."} response, never a 500.
    def _raise_not_found(*args, **kwargs):
        raise PrinterNotFoundError("no USB printer found for vendor_id=0x04f9 product_id=0x224a")

    monkeypatch.setattr(
        "labelmaker.api.router_printer.PyUsbTransport.open", staticmethod(_raise_not_found)
    )

    config = AppConfig(printer_mode="usb", data_dir=tmp_path / "data")
    app = create_app(config)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/printer/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["printer_mode"] == "usb"
    assert body["status"] is None
    assert "no USB printer found" in body["error"]
    assert "keep_alive" in body  # additive, present on the disconnected branch too


async def test_printer_status_honors_a_db_override_over_the_config_printer_mode(
    client, monkeypatch
):
    # The `client` fixture's app boots in mock mode (conftest.py). A DB
    # override set via PUT /api/settings must be reflected here -- both the
    # transport this endpoint actually probes AND the `printer_mode` it
    # reports -- without a restart (review fix: this endpoint used to read
    # `config.printer_mode` directly, ignoring any settings-overlay
    # override entirely). No real USB hardware in CI/dev, so -- same as
    # test_printer_status_usb_mode_no_device_reports_disconnected above --
    # PyUsbTransport.open() is monkeypatched to deterministically raise
    # PrinterNotFoundError, giving a connected=false/error response whose
    # shape doesn't depend on what's actually plugged into this host.
    def _raise_not_found(*args, **kwargs):
        raise PrinterNotFoundError("no USB printer found for vendor_id=0x04f9 product_id=0x224a")

    monkeypatch.setattr(
        "labelmaker.api.router_printer.PyUsbTransport.open", staticmethod(_raise_not_found)
    )

    resp = await client.put("/api/settings", json={"printer_mode": "usb"})
    assert resp.status_code == 200

    resp = await client.get("/api/printer/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["printer_mode"] == "usb"
    assert body["status"] is None
    assert "no USB printer found" in body["error"]
