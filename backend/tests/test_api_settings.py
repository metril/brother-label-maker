"""Tests for GET/PUT /api/settings (task 4.5): the DB-backed settings
overlay's HTTP surface. See settings_overlay.py for the underlying model
these tests exercise through the real app (the `client`/`app_and_client`
fixtures), not `SettingsOverlay` directly -- that's test_settings_overlay.py's
job.
"""

from __future__ import annotations

import pytest

# The full, exact row-key set the Settings page renders -- asserted with
# `==` (not "is a subset of") so a future field addition to
# router_settings.py's `_FIELD_ORDER`/`_READONLY_FIELDS` is a conscious,
# reviewed change to this test, not a silent drift.
_EXPECTED_ROW_KEYS = {
    "printer_mode",
    "printer_init_strategy",
    "printer_bit_order",
    "printer_flip_pins",
    "els_tape_mm",
    "homebox_url",
    "homebox_api_key",
    "keep_printer_awake",
    "keep_awake_interval_min",
    "auth_mode",
    "els_enabled",
    "data_dir",
    "cors_origins",
}

# Nothing shaped like a secret (or OIDC/session config) may ever appear in
# the raw response text -- catches a future accidental
# `**cfg.model_dump()`-style shortcut even if it slipped past
# _EXPECTED_ROW_KEYS above (e.g. by renaming a secret field to something
# innocuous-looking).
_FORBIDDEN_SUBSTRINGS = ("oidc", "session_secret", "client_secret")


def _rows_by_key(body: dict) -> dict[str, dict]:
    return {row["key"]: row for row in body["settings"]}


# -- GET: shape, allowlist, no secret leakage -----------------------------


async def test_get_settings_returns_exactly_the_allowlisted_keys(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    rows = _rows_by_key(resp.json())
    assert rows.keys() == _EXPECTED_ROW_KEYS


async def test_get_settings_reflects_app_config_defaults(client):
    resp = await client.get("/api/settings")
    rows = _rows_by_key(resp.json())
    assert rows["printer_mode"]["value"] == "mock"
    assert rows["printer_init_strategy"]["value"] == "classic"
    assert rows["printer_bit_order"]["value"] == "msb_first"
    # app_config's fixture default (conftest.py's _DEFAULT_APP_CONFIG_KWARGS)
    # is False here -- distinct from the AppConfig class's own True default,
    # see that fixture's docstring for why tests pin this explicitly.
    assert rows["printer_flip_pins"]["value"] is False
    assert rows["els_tape_mm"]["value"] == 24.0
    assert rows["els_enabled"]["value"] is False
    assert rows["auth_mode"]["value"] == "none"
    assert rows["homebox_url"]["value"] is None
    assert rows["homebox_api_key"]["set"] is False
    assert "value" not in rows["homebox_api_key"]
    # DB-only fields, no override stored yet -> their hardcoded defaults.
    assert rows["keep_printer_awake"]["value"] is False
    assert rows["keep_awake_interval_min"]["value"] == 5
    # Every conftest-pinned field is explicitly provided to AppConfig's
    # constructor (see _DEFAULT_APP_CONFIG_KWARGS's own docstring), so it
    # reads as "env" provenance here even though it equals the class
    # default -- this mirrors real deployments where an operator export
    # sets the SAME value the class would have defaulted to anyway.
    assert rows["printer_flip_pins"]["source"] == "env"
    assert rows["data_dir"]["editable"] is False
    assert rows["cors_origins"]["editable"] is False
    assert rows["auth_mode"]["editable"] is False
    assert rows["els_enabled"]["editable"] is False
    for field in _EXPECTED_ROW_KEYS - {"auth_mode", "els_enabled", "data_dir", "cors_origins"}:
        assert rows[field]["editable"] is True


async def test_get_settings_never_leaks_oidc_or_session_material(client):
    resp = await client.get("/api/settings")
    text = resp.text.lower()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in text


@pytest.mark.parametrize(
    "app_config",
    [{"homebox_url": "https://hb.test", "homebox_api_key": "hb_env_key_plant"}],
    indirect=True,
)
async def test_get_settings_reports_homebox_env_config_without_leaking_the_key(client):
    resp = await client.get("/api/settings")
    rows = _rows_by_key(resp.json())
    assert rows["homebox_url"]["value"] == "https://hb.test"
    assert rows["homebox_url"]["source"] == "env"
    assert rows["homebox_api_key"]["set"] is True
    assert rows["homebox_api_key"]["source"] == "env"
    assert "value" not in rows["homebox_api_key"]
    assert "hb_env_key_plant" not in resp.text


# -- PUT: the secret is never echoed back, in any provenance state --------


async def test_put_homebox_api_key_never_echoes_the_planted_value(client):
    resp = await client.put("/api/settings", json={"homebox_api_key": "hb_super_secret_plant"})
    assert resp.status_code == 200
    assert "hb_super_secret_plant" not in resp.text
    row = _rows_by_key(resp.json())["homebox_api_key"]
    assert "value" not in row
    assert row["set"] is True
    assert row["source"] == "db"

    resp = await client.get("/api/settings")
    assert "hb_super_secret_plant" not in resp.text


# -- PUT: roundtrip changes provenance, null reverts -----------------------


async def test_put_printer_flip_pins_roundtrip_changes_provenance(client):
    resp = await client.get("/api/settings")
    row = _rows_by_key(resp.json())["printer_flip_pins"]
    assert row["value"] is False
    assert row["source"] == "env"

    resp = await client.put("/api/settings", json={"printer_flip_pins": True})
    assert resp.status_code == 200
    row = _rows_by_key(resp.json())["printer_flip_pins"]
    assert row["value"] is True
    assert row["source"] == "db"

    # Persists across a fresh GET, not just the PUT's own echoed response.
    resp = await client.get("/api/settings")
    row = _rows_by_key(resp.json())["printer_flip_pins"]
    assert row["value"] is True
    assert row["source"] == "db"

    resp = await client.put("/api/settings", json={"printer_flip_pins": None})
    assert resp.status_code == 200
    row = _rows_by_key(resp.json())["printer_flip_pins"]
    assert row["value"] is False
    assert row["source"] == "env"


async def test_put_is_a_true_partial_update(client):
    """Setting one field leaves every other field's provenance untouched."""
    resp = await client.put("/api/settings", json={"printer_bit_order": "lsb_first"})
    assert resp.status_code == 200
    rows = _rows_by_key(resp.json())
    assert rows["printer_bit_order"]["value"] == "lsb_first"
    assert rows["printer_bit_order"]["source"] == "db"
    assert rows["printer_flip_pins"]["source"] == "env"
    assert rows["printer_mode"]["source"] == "env"


# -- PUT: validation --------------------------------------------------------


async def test_put_unknown_key_is_422(client):
    resp = await client.put("/api/settings", json={"bogus_field": 1})
    assert resp.status_code == 422
    assert "bogus_field" in resp.json()["detail"]


async def test_put_invalid_literal_is_422(client):
    resp = await client.put("/api/settings", json={"printer_mode": "not-a-mode"})
    assert resp.status_code == 422


async def test_put_els_tape_mm_out_of_bounds_is_422(client):
    resp = await client.put("/api/settings", json={"els_tape_mm": 100})
    assert resp.status_code == 422


async def test_put_homebox_url_bad_scheme_is_422(client):
    resp = await client.put("/api/settings", json={"homebox_url": "ftp://x"})
    assert resp.status_code == 422


async def test_put_homebox_api_key_blank_is_422(client):
    resp = await client.put("/api/settings", json={"homebox_api_key": "   "})
    assert resp.status_code == 422


async def test_put_invalid_batch_applies_nothing(client):
    """A batch with one bad field must not partially apply the good ones."""
    resp = await client.put(
        "/api/settings", json={"printer_flip_pins": True, "printer_mode": "not-a-mode"}
    )
    assert resp.status_code == 422

    resp = await client.get("/api/settings")
    row = _rows_by_key(resp.json())["printer_flip_pins"]
    assert row["value"] is False
    assert row["source"] == "env"


# -- PUT homebox_url/homebox_api_key rebuilds app.state.homebox -----------


_ENV_KEY_ONLY = pytest.mark.parametrize(
    "app_config",
    [{"homebox_api_key": "hb_env_key"}],
    indirect=True,
)


@_ENV_KEY_ONLY
async def test_put_homebox_url_rebuilds_client_using_effective_env_key(app_and_client):
    app, client = app_and_client
    assert app.state.homebox is None  # url unset even though the key is (env)

    resp = await client.put("/api/settings", json={"homebox_url": "https://hb2.test"})
    assert resp.status_code == 200
    assert app.state.homebox is not None
    assert app.state.homebox.base_url == "https://hb2.test"
    assert app.state.homebox._client.headers["Authorization"] == "Bearer hb_env_key"

    resp = await client.put("/api/settings", json={"homebox_url": None})
    assert resp.status_code == 200
    assert app.state.homebox is None  # key alone isn't enough once the url override clears


async def test_put_homebox_url_and_key_together_builds_and_closes_old_client(app_and_client):
    app, client = app_and_client
    assert app.state.homebox is None

    resp = await client.put(
        "/api/settings",
        json={"homebox_url": "https://hb3.test", "homebox_api_key": "hb_new_key"},
    )
    assert resp.status_code == 200
    first_client = app.state.homebox
    assert first_client is not None
    assert first_client.base_url == "https://hb3.test"
    assert first_client._client.is_closed is False

    # A second PUT rebuilds AGAIN -- the first client is not reused, and is
    # actually closed, not just discarded and left dangling.
    resp = await client.put("/api/settings", json={"homebox_url": "https://hb4.test"})
    assert resp.status_code == 200
    second_client = app.state.homebox
    assert second_client is not first_client
    assert second_client.base_url == "https://hb4.test"
    assert first_client._client.is_closed is True

    resp = await client.put(
        "/api/settings", json={"homebox_url": None, "homebox_api_key": None}
    )
    assert resp.status_code == 200
    assert app.state.homebox is None
    assert second_client._client.is_closed is True


async def test_put_unrelated_field_does_not_touch_homebox_client(app_and_client):
    app, client = app_and_client
    assert app.state.homebox is None

    resp = await client.put("/api/settings", json={"printer_flip_pins": True})
    assert resp.status_code == 200
    assert app.state.homebox is None
