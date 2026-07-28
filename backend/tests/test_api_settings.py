"""Tests for GET /api/settings/runtime (task 4.2)."""

from __future__ import annotations

import pytest

# The full, exact key set the Settings page's read-only config panel
# renders -- asserted with `==` (not "is a subset of") so a future field
# addition to router_settings.py's RuntimeSettings is a conscious,
# reviewed change to this test, not a silent drift.
_EXPECTED_KEYS = {
    "printer_mode",
    "printer_init_strategy",
    "printer_bit_order",
    "printer_flip_pins",
    "els_enabled",
    "els_tape_mm",
    "auth_mode",
    "homebox_configured",
}

# Nothing shaped like a secret may ever appear here -- these are the actual
# AppConfig field names that guard credentials (config.py), so a future
# accidental `**cfg.model_dump()`-style shortcut in router_settings.py
# would be caught by this list even if it slipped past _EXPECTED_KEYS
# above (e.g. by renaming a secret field to something innocuous-looking).
_FORBIDDEN_KEYS = {
    "homebox_api_key",
    "homebox_url",
    "oidc_client_secret",
    "session_secret",
    "oidc_client_id",
}


async def test_runtime_settings_returns_exactly_the_allowlisted_keys(client):
    resp = await client.get("/api/settings/runtime")
    assert resp.status_code == 200
    body = resp.json()
    assert body.keys() == _EXPECTED_KEYS
    assert not (body.keys() & _FORBIDDEN_KEYS)


async def test_runtime_settings_reflects_app_config_defaults(client):
    resp = await client.get("/api/settings/runtime")
    body = resp.json()
    assert body["printer_mode"] == "mock"
    assert body["printer_init_strategy"] == "classic"
    assert body["printer_bit_order"] == "msb_first"
    # app_config's fixture default (conftest.py's _DEFAULT_APP_CONFIG_KWARGS)
    # is False here -- distinct from the AppConfig class's own True default,
    # see that fixture's docstring for why tests pin this explicitly.
    assert body["printer_flip_pins"] is False
    assert body["els_enabled"] is False
    assert body["els_tape_mm"] == 24.0
    assert body["auth_mode"] == "none"
    assert body["homebox_configured"] is False


@pytest.mark.parametrize(
    "app_config",
    [{"homebox_url": "https://hb.test", "homebox_api_key": "hb_k"}],
    indirect=True,
)
async def test_runtime_settings_reports_homebox_configured_true_when_both_set(client):
    resp = await client.get("/api/settings/runtime")
    body = resp.json()
    assert body["homebox_configured"] is True
    # Still never the actual url/key values.
    assert "homebox_url" not in body
    assert "homebox_api_key" not in body
