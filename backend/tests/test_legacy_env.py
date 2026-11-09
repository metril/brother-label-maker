"""config.py's env allowlist and legacy_env.py's one-time import."""

import logging

import pytest

from labelmaker.config import ENV_FIELDS, AppConfig
from labelmaker.db.database import Database
from labelmaker.legacy_env import LEGACY_ENV_FIELDS, import_legacy_env
from labelmaker.settings_overlay import SettingsOverlay

REMOVED = {
    "PRINTER_MODE": "usb",
    "PRINTER_BRIDGE_ADDRESS": "pi.local",
    "PRINTER_BRIDGE_CERT": "x",
    "PRINTER_INIT_STRATEGY": "e310bt",
    "PRINTER_BIT_ORDER": "lsb_first",
    "PRINTER_FLIP_PINS": "false",
    "HOMEBOX_URL": "https://hb.test",
    "HOMEBOX_API_KEY": "hb_secret",
    "HOMEBOX_WRITES_ENABLED": "true",
    "ELS_ENABLED": "true",
    "ELS_TAPE_MM": "12",
}


def test_removed_env_vars_do_not_change_appconfig(monkeypatch):
    assert set(REMOVED) == set(LEGACY_ENV_FIELDS)
    base = AppConfig().model_dump()
    for name, value in REMOVED.items():
        monkeypatch.setenv(name, value)
    cfg = AppConfig()
    assert cfg.model_dump() == base
    assert cfg.model_fields_set == set()


@pytest.mark.parametrize(
    ("name", "value", "attr", "expected"),
    [
        ("DATA_DIR", "/somewhere", "data_dir", "/somewhere"),
        ("CORS_ORIGINS", '["https://a.test"]', "cors_origins", ["https://a.test"]),
        ("AUTH_MODE", "oidc", "auth_mode", "oidc"),
        ("OIDC_ISSUER", "https://idp.test", "oidc_issuer", "https://idp.test"),
        ("OIDC_CLIENT_ID", "cid", "oidc_client_id", "cid"),
        ("OIDC_CLIENT_SECRET", "sec", "oidc_client_secret", "sec"),
        ("OIDC_SCOPES", "openid", "oidc_scopes", "openid"),
        ("SESSION_SECRET", "s" * 32, "session_secret", "s" * 32),
        ("SESSION_MAX_AGE_S", "600", "session_max_age_s", 600),
        ("SESSION_COOKIE_SECURE", "true", "session_cookie_secure", True),
    ],
)
def test_kept_env_vars_still_work(monkeypatch, name, value, attr, expected):
    assert attr in ENV_FIELDS
    monkeypatch.setenv(name, value)
    got = getattr(AppConfig(), attr)
    assert str(got) == expected if attr == "data_dir" else got == expected


def test_constructor_kwargs_still_work():
    assert AppConfig(printer_mode="usb", els_tape_mm=12).printer_mode == "usb"


@pytest.fixture
async def overlay(tmp_path):
    db = await Database.open(tmp_path / "t.db")
    yield await SettingsOverlay.create(AppConfig(data_dir=tmp_path), db)
    await db.close()


async def test_imports_once_and_warns_without_values(overlay, caplog):
    caplog.set_level(logging.WARNING)
    env = {
        "PRINTER_INIT_STRATEGY": "e310bt",
        "HOMEBOX_API_KEY": "hb_topsecret",
        "ELS_TAPE_MM": "12",
    }
    assert sorted(await import_legacy_env(overlay, env)) == sorted(env)
    eff = overlay.effective()
    assert (eff.printer_init_strategy, eff.homebox_api_key, eff.els_tape_mm) == (
        "e310bt",
        "hb_topsecret",
        12,
    )
    assert "HOMEBOX_API_KEY" in caplog.text
    assert "hb_topsecret" not in caplog.text
    # Idempotent: second start stores nothing, changes nothing, warns again.
    caplog.clear()
    assert await import_legacy_env(overlay, env) == []
    assert overlay.effective().printer_init_strategy == "e310bt"
    assert "PRINTER_INIT_STRATEGY" in caplog.text


async def test_stored_override_wins(overlay, caplog):
    await overlay.set_many({"printer_bit_order": "msb_first"})
    caplog.set_level(logging.WARNING)
    assert await import_legacy_env(overlay, {"PRINTER_BIT_ORDER": "lsb_first"}) == []
    assert overlay.effective().printer_bit_order == "msb_first"
    assert "PRINTER_BIT_ORDER" in caplog.text


async def test_invalid_value_skipped_others_imported(overlay, caplog):
    caplog.set_level(logging.WARNING)
    env = {"PRINTER_MODE": "banana", "ELS_ENABLED": "true"}
    assert await import_legacy_env(overlay, env) == ["ELS_ENABLED"]
    assert overlay.effective().printer_mode == "mock"
    assert overlay.effective().els_enabled is True
    assert "PRINTER_MODE" in caplog.text and "banana" not in caplog.text


async def test_empty_env_var_ignored(overlay):
    assert await import_legacy_env(overlay, {"PRINTER_MODE": "  "}) == []


async def test_incomplete_remote_warns_and_imports_the_rest(overlay, caplog):
    caplog.set_level(logging.WARNING)
    env = {"PRINTER_MODE": "remote", "PRINTER_BRIDGE_ADDRESS": "pi.local", "ELS_ENABLED": "1"}
    assert await import_legacy_env(overlay, env) == ["PRINTER_BRIDGE_ADDRESS", "ELS_ENABLED"]
    eff = overlay.effective()
    assert eff.printer_mode == "mock"
    assert eff.els_enabled is True
    assert "PRINTER_MODE was not imported" in caplog.text


async def test_complete_remote_imported_together(overlay, tmp_path):
    from labelmaker.driver.bridge_identity import ensure_identity

    _k, cert = ensure_identity(tmp_path / "id", "bridge")
    env = {
        "PRINTER_MODE": "remote",
        "PRINTER_BRIDGE_ADDRESS": "pi.local:9177",
        "PRINTER_BRIDGE_CERT": cert.read_text(),
    }
    assert len(await import_legacy_env(overlay, env)) == 3
    assert overlay.effective().printer_mode == "remote"
