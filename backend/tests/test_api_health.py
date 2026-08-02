"""Tests for GET /api/health and GET /api/label-types."""

from __future__ import annotations


async def test_health_reports_ok_and_printer_mode(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    # task 4.2: `version` is additive (the diagnostics page's "App" section
    # wants something honest to show next to backend reachability) --
    # asserted as "a non-empty string" rather than pinned to "0.1.0" so this
    # test doesn't need editing every version bump; main.py's own
    # APP_VERSION docstring covers where the value comes from.
    assert body["status"] == "ok"
    assert body["printer_mode"] == "mock"
    assert isinstance(body["version"], str) and body["version"] != ""


async def test_health_reports_a_db_override_printer_mode(client):
    # Review fix: GET /api/health used to read `cfg.printer_mode` directly,
    # so a printer_mode override set via PUT /api/settings (settings
    # overlay, api/router_settings.py) never showed up here even though it
    # WAS already honored by the actual print path -- the diagnostics page
    # would show a stale mode. It now reads `app.state.settings.effective()`
    # the same as GET /api/printer/status.
    resp = await client.put("/api/settings", json={"printer_mode": "usb"})
    assert resp.status_code == 200

    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["printer_mode"] == "usb"


async def test_label_types_contains_text_with_schema(client):
    resp = await client.get("/api/label-types")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)

    text_type = next(t for t in body if t["type"] == "text")
    assert text_type["title"] == "Text"
    assert "lines" in text_type["params_schema"]["properties"]
    # task 2.7: the optional leading-art `icon` param (symbol/image) is
    # visible in the schema a UI would build a form from.
    assert "icon" in text_type["params_schema"]["properties"]


async def test_label_types_lists_eleven_types_with_categories(client):
    # Task 2.2: patch_panel/punch_down/faceplate join "text". Task 2.3:
    # terminal_block/breaker_box join those. Task 2.5: barcode joins "text"
    # in category "general". Task 2.6: cable_wrap/cable_flag join the
    # "network" group. Task 3.3: homebox_asset/homebox_location form their
    # own "homebox" group -- exactly these eleven (the registry-isolation
    # fixture in conftest.py, see test_render_registry.py, keeps test-only
    # "dummy" types from leaking into this count).
    resp = await client.get("/api/label-types")
    body = resp.json()
    by_type = {t["type"]: t for t in body}
    assert by_type.keys() == {
        "text",
        "barcode",
        "patch_panel",
        "punch_down",
        "faceplate",
        "cable_wrap",
        "cable_flag",
        "terminal_block",
        "breaker_box",
        "homebox_asset",
        "homebox_location",
    }

    for general_type in ("text", "barcode"):
        assert by_type[general_type]["category"] == "general"
    for network_type in ("patch_panel", "punch_down", "faceplate", "cable_wrap", "cable_flag"):
        assert by_type[network_type]["category"] == "network"
    for electrical_type in ("terminal_block", "breaker_box"):
        assert by_type[electrical_type]["category"] == "electrical"
    for homebox_type in ("homebox_asset", "homebox_location"):
        assert by_type[homebox_type]["category"] == "homebox"

    # min_tape_mm is always present (None = usable on any tape width; the
    # two homebox types are the first to advertise a non-None floor -- see
    # homebox_asset.py's own module docstring's "-- min_tape_mm --" section).
    for t in body:
        if t["type"] in ("homebox_asset", "homebox_location"):
            assert t["min_tape_mm"] == 12.0
        else:
            assert t["min_tape_mm"] is None
