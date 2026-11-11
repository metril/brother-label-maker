"""Zero-env-vars contract: the app reads no environment variables, paths are
fixed, and the operator-facing auth/CORS settings live in the DB overlay."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import respx
from test_api_auth import (
    _JWKS_PUBLIC,
    CLIENT_ID,
    CLIENT_SECRET,
    DISCOVERY_URL,
    ISSUER,
    JWKS_URL,
    TOKEN_URL,
    _discovery_document,
    _sign_id_token,
)

from labelmaker import paths
from labelmaker.cli import main as cli_main
from labelmaker.config import AppConfig
from labelmaker.db.database import Database
from labelmaker.main import create_app
from labelmaker.settings_overlay import OIDC_VERIFIED_KEY

SRC = Path(__file__).resolve().parents[1] / "src" / "labelmaker"
_ENV_USE = re.compile(r"os\.environ|getenv|from os import[^\n]*\benviron\b|environ\[")


def test_no_environment_reads_in_src():
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if _ENV_USE.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_legacy_env_module_is_gone():
    assert not (SRC / "legacy_env.py").exists()


def test_old_env_vars_are_ignored(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("CORS_ORIGINS", '["https://x.example"]')
    monkeypatch.setenv("DATA_DIR", "/nonexistent-env-dir")
    cfg = AppConfig()
    assert cfg.auth_mode == "none"
    assert cfg.cors_origins == ["http://localhost:5173"]
    assert str(cfg.data_dir) != "/nonexistent-env-dir"


def test_paths_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONTAINER_DATA_DIR", tmp_path / "missing")
    assert paths.default_data_dir() == paths.REPO_ROOT / "data"
    vol = tmp_path / "vol"
    vol.mkdir()
    monkeypatch.setattr(paths, "CONTAINER_DATA_DIR", vol)
    assert paths.default_data_dir() == vol

    fake_root = tmp_path / "repo"
    monkeypatch.setattr(paths, "REPO_ROOT", fake_root)
    img = tmp_path / "app-static"
    monkeypatch.setattr(paths, "CONTAINER_STATIC_DIR", img)
    assert paths.find_static_dir() is None
    img.mkdir()
    assert paths.find_static_dir() == img
    (fake_root / "frontend" / "dist").mkdir(parents=True)
    assert paths.find_static_dir() == fake_root / "frontend" / "dist"


# -- session secret ---------------------------------------------------------


async def test_session_secret_persists_across_restarts(tmp_path):
    cfg = AppConfig(printer_mode="mock", data_dir=tmp_path / "data")
    secrets_seen = []
    for _ in range(2):
        app = create_app(cfg, static_dir=None)
        async with app.router.lifespan_context(app):
            secrets_seen.append(app.state.settings.session_secret)
    assert len(secrets_seen[0]) >= 32
    assert secrets_seen[0] == secrets_seen[1]


async def test_session_secret_never_in_settings_get(client, app_and_client):
    app, _ = app_and_client
    text = (await client.get("/api/v1/settings")).text
    assert app.state.settings.session_secret not in text


# -- settings: secret write-only, validation, CORS ------------------------


async def test_oidc_secret_write_only_and_clearable(client):
    resp = await client.put("/api/v1/settings", json={"oidc_client_secret": "s3cr3t-plant-value"})
    assert resp.status_code == 200
    assert "s3cr3t-plant-value" not in resp.text
    row = {r["key"]: r for r in resp.json()["settings"]}["oidc_client_secret"]
    assert row["set"] is True and "value" not in row and row["source"] == "db"
    assert "s3cr3t-plant-value" not in (await client.get("/api/v1/settings")).text

    bad = await client.put("/api/v1/settings", json={"oidc_client_secret": "   "})
    assert bad.status_code == 422
    assert "   " not in bad.json()["error"]["message"].split(":", 1)[-1][:3]

    cleared = await client.put("/api/v1/settings", json={"oidc_client_secret": None})
    row = {r["key"]: r for r in cleared.json()["settings"]}["oidc_client_secret"]
    assert row["set"] is False


async def test_oidc_validators(client):
    for body in (
        {"oidc_scopes": "profile email"},
        {"oidc_issuer": "ftp://x"},
        {"session_max_age_s": 10},
        {"cors_origins": ["*"]},
        {"cors_origins": ["https://a.example/path"]},
    ):
        assert (await client.put("/api/v1/settings", json=body)).status_code == 422, body


async def test_cors_preflight_follows_settings_without_restart(client):
    def preflight(origin):
        return client.options(
            "/api/v1/tapes",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )

    assert "access-control-allow-origin" not in (await preflight("https://new.example")).headers
    resp = await client.put("/api/v1/settings", json={"cors_origins": ["https://new.example/"]})
    assert resp.status_code == 200
    got = await preflight("https://new.example")
    assert got.headers["access-control-allow-origin"] == "https://new.example"
    await client.put("/api/v1/settings", json={"cors_origins": None})
    assert "access-control-allow-origin" not in (await preflight("https://new.example")).headers


async def test_get_exposes_verified_status_and_redirect_uri(client):
    rows = {r["key"]: r for r in (await client.get("/api/v1/settings")).json()["settings"]}
    assert rows["oidc_verified"]["value"] is False
    assert rows["oidc_redirect_uri"]["value"] == "http://test/api/auth/callback"
    assert rows["oidc_redirect_uri"]["editable"] is False


# -- none -> oidc via test login -------------------------------------------


@pytest.fixture
def idp():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=_discovery_document()))
        mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_JWKS_PUBLIC))
        yield mock


_CANDIDATE = {
    "oidc_issuer": ISSUER,
    "oidc_client_id": CLIENT_ID,
    "oidc_client_secret": CLIENT_SECRET,
}


async def _test_login(client, idp, *, sub="user-1", bad_nonce=False):
    resp = await client.post("/api/v1/auth/oidc-test", json=_CANDIDATE)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["redirect_uri"] == "http://test/api/auth/callback"
    params = httpx.URL(body["authorize_url"]).params
    nonce = "wrong" if bad_nonce else params["nonce"]
    idp.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": _sign_id_token(nonce=nonce, sub=sub),
            },
        )
    )
    return await client.get(
        "/api/v1/auth/callback", params={"code": "c", "state": params["state"]}
    )


async def test_switch_to_oidc_requires_verified_test_login(app_and_client, idp):
    app, client = app_and_client
    await client.put("/api/v1/settings", json=_CANDIDATE)
    blocked = await client.put("/api/v1/settings", json={"auth_mode": "oidc"})
    assert blocked.status_code == 409

    cb = await _test_login(client, idp)
    assert cb.status_code == 302 and cb.headers["location"] == "/settings?oidc_test=ok"
    rows = {r["key"]: r for r in (await client.get("/api/v1/settings")).json()["settings"]}
    assert rows["oidc_verified"]["value"] is True

    ok = await client.put("/api/v1/settings", json={"auth_mode": "oidc"})
    assert ok.status_code == 200
    # Live switch, no restart: this browser was signed in by the test login...
    assert (await client.get("/api/v1/tapes")).status_code == 200
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["auth_mode"] == "oidc" and me["authenticated"] is True
    # ...while a fresh client is gated.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as anon:
        assert (await anon.get("/api/v1/tapes")).status_code == 401
        assert (await anon.post("/api/v1/auth/oidc-test", json=_CANDIDATE)).status_code == 401
        assert (await anon.post("/api/v1/auth/rotate-session-secret")).status_code == 401

    # Editing any OIDC field while oidc is active is refused (marker clears).
    assert (
        await client.put("/api/v1/settings", json={"oidc_scopes": "openid"})
    ).status_code == 409
    # Back to none first, then edit: marker cleared, oidc blocked again.
    assert (await client.put("/api/v1/settings", json={"auth_mode": "none"})).status_code == 200
    assert (await client.put("/api/v1/settings", json={"oidc_scopes": "openid"})).status_code == 200
    rows = {r["key"]: r for r in (await client.get("/api/v1/settings")).json()["settings"]}
    assert rows["oidc_verified"]["value"] is False
    assert (await client.put("/api/v1/settings", json={"auth_mode": "oidc"})).status_code == 409


async def test_failed_test_login_saves_nothing(client, idp):
    cb = await _test_login(client, idp, bad_nonce=True)
    assert cb.status_code == 302
    assert cb.headers["location"].startswith("/settings?oidc_test=error")
    rows = {r["key"]: r for r in (await client.get("/api/v1/settings")).json()["settings"]}
    assert rows["oidc_verified"]["value"] is False
    assert rows["oidc_issuer"]["source"] == "default"


async def test_api_key_cannot_change_auth_or_cors_in_oidc_mode(app_and_client, idp):
    from labelmaker.api import api_keys

    app, client = app_and_client
    await client.put("/api/v1/settings", json=_CANDIDATE)
    await _test_login(client, idp)
    assert (await client.put("/api/v1/settings", json={"auth_mode": "oidc"})).status_code == 200

    plaintext = "lm_" + "B" * 43
    await app.state.db.create_api_key(
        "t", "write", api_keys.lookup_prefix(plaintext), api_keys.hash_key(plaintext)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as keyed:
        assert (await keyed.get("/api/v1/tapes")).status_code == 200
        for body in ({"auth_mode": "none"}, {"cors_origins": ["https://evil.example"]}):
            assert (await keyed.put("/api/v1/settings", json=body)).status_code == 403
        # Non-protected settings stay writable with a write key.
        assert (
            await keyed.put("/api/v1/settings", json={"printer_flip_pins": False})
        ).status_code == 200
        assert (await keyed.post("/api/v1/auth/rotate-session-secret")).status_code == 403


async def test_rotate_session_secret_invalidates_existing_cookie(app_and_client, idp):
    app, client = app_and_client
    await client.put("/api/v1/settings", json=_CANDIDATE)
    await _test_login(client, idp)
    await client.put("/api/v1/settings", json={"auth_mode": "oidc"})
    old = app.state.settings.session_secret
    assert (await client.get("/api/v1/auth/me")).json()["authenticated"] is True

    assert (await client.post("/api/v1/auth/rotate-session-secret")).status_code == 204
    assert app.state.settings.session_secret != old
    assert (await client.get("/api/v1/auth/me")).json()["authenticated"] is False
    assert (await client.get("/api/v1/tapes")).status_code == 401


# -- reset-auth CLI --------------------------------------------------------


def test_reset_auth_cli(tmp_path):
    import asyncio

    data = tmp_path / "data"
    data.mkdir()

    async def seed():
        db = await Database.open(data / "labelmaker.db")
        await db.set_setting("cfg.auth_mode", "oidc")
        await db.set_setting("cfg.oidc_issuer", ISSUER)
        await db.set_setting(OIDC_VERIFIED_KEY, "x")
        await db.set_setting("auth.session_secret", "s" * 64)
        await db.close()

    async def read():
        db = await Database.open(data / "labelmaker.db")
        rows = await db.all_settings()
        await db.close()
        return rows

    asyncio.run(seed())
    assert cli_main(["reset-auth", "--data-dir", str(data)]) == 0
    rows = asyncio.run(read())
    assert "cfg.auth_mode" not in rows and OIDC_VERIFIED_KEY not in rows
    assert rows["cfg.oidc_issuer"] == ISSUER and "auth.session_secret" in rows

    cli_main(["reset-auth", "--data-dir", str(data), "--rotate-session-secret"])
    assert "auth.session_secret" not in asyncio.run(read())
