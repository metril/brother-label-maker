"""API keys (bearer auth under OIDC), scopes, key-management isolation, WS tickets."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_api_auth import _OIDC_APP_CONFIG_OVERRIDES, _OIDC_CONFIGURED, _complete_login, idp_mock

from labelmaker.api import api_keys
from labelmaker.config import AppConfig
from labelmaker.main import create_app

__all__ = ["idp_mock"]


async def _make_key(client, scope="write", name="ci"):
    resp = await client.post("/api/v1/api-keys", json={"name": name, "scope": scope})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def signed_in(client, idp_mock):
    await _complete_login(client, idp_mock)
    return client


async def test_keys_usable_without_session_in_none_mode(client):
    created = await _make_key(client)
    assert created["key"].startswith("lm_")
    assert (await client.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 204


async def test_bearer_ignored_in_none_mode(client):
    resp = await client.get("/api/v1/tapes", headers={"Authorization": "Bearer lm_garbage"})
    assert resp.status_code == 200


@_OIDC_CONFIGURED
async def test_create_list_revoke_never_exposes_plaintext(signed_in):
    c = signed_in
    created = await _make_key(c)
    assert set(created) >= {"id", "name", "prefix", "scope", "created_at", "key"}
    assert created["prefix"] == api_keys.lookup_prefix(created["key"])
    listed = (await c.get("/api/v1/api-keys")).json()
    assert [k["id"] for k in listed] == [created["id"]]
    assert created["key"] not in (await c.get("/api/v1/api-keys")).text
    assert "sha256_hash" not in listed[0] and "key" not in listed[0]
    assert (await c.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 204
    assert (await c.get("/api/v1/api-keys")).json() == []
    assert (await c.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 404


@_OIDC_CONFIGURED
async def test_key_management_requires_session(client):
    for method, path in [("GET", "/api/v1/api-keys"), ("POST", "/api/v1/api-keys")]:
        resp = await client.request(method, path, json={"name": "x"})
        assert resp.status_code == 401


@_OIDC_CONFIGURED
@pytest.mark.parametrize("prefix", ["/api/v1", "/api"])
async def test_bearer_works_on_gated_route_under_both_prefixes(app_and_client, idp_mock, prefix):
    app, client = app_and_client
    await _complete_login(client, idp_mock)
    key = (await _make_key(client))["key"]
    client.cookies.clear()
    assert (await client.get(f"{prefix}/tapes")).status_code == 401
    resp = await client.get(f"{prefix}/tapes", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200


@_OIDC_CONFIGURED
async def test_revoked_and_garbage_keys_get_401_without_echoing_key(client, idp_mock):
    await _complete_login(client, idp_mock)
    created = await _make_key(client)
    await client.delete(f"/api/v1/api-keys/{created['id']}")
    client.cookies.clear()
    for token in (created["key"], "lm_" + "x" * 43, "lm_", "notakey"):
        resp = await client.get("/api/v1/tapes", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "auth_required"
        assert token not in resp.text or token == "lm_"


@_OIDC_CONFIGURED
async def test_read_key_cannot_write(client, idp_mock):
    await _complete_login(client, idp_mock)
    key = (await _make_key(client, scope="read"))["key"]
    client.cookies.clear()
    h = {"Authorization": f"Bearer {key}"}
    assert (await client.get("/api/v1/tapes", headers=h)).status_code == 200
    resp = await client.post("/api/v1/print/preview", json={}, headers=h)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    # ...but may fetch a ws ticket to watch events.
    assert (await client.post("/api/v1/ws-ticket", headers=h)).status_code == 200


@_OIDC_CONFIGURED
async def test_bearer_cannot_manage_keys(client, idp_mock):
    await _complete_login(client, idp_mock)
    created = await _make_key(client)
    client.cookies.clear()
    h = {"Authorization": f"Bearer {created['key']}"}
    for method, path in [
        ("GET", "/api/v1/api-keys"),
        ("POST", "/api/v1/api-keys"),
        ("DELETE", f"/api/v1/api-keys/{created['id']}"),
    ]:
        resp = await client.request(method, path, headers=h, json={"name": "y"})
        assert resp.status_code == 403, (method, resp.text)
        assert resp.json()["error"]["code"] == "forbidden"


@_OIDC_CONFIGURED
async def test_last_used_at_updated(client, idp_mock):
    await _complete_login(client, idp_mock)
    created = await _make_key(client)
    listed = (await client.get("/api/v1/api-keys")).json()
    assert listed[0]["last_used_at"] is None
    client.cookies.clear()
    await client.get("/api/v1/tapes", headers={"Authorization": f"Bearer {created['key']}"})
    await _complete_login(client, idp_mock)
    assert (await client.get("/api/v1/api-keys")).json()[0]["last_used_at"] is not None


def test_ticket_store_single_use_and_expiry(monkeypatch):
    store = api_keys.WsTicketStore()
    t = store.issue()
    assert store.consume(t) is True
    assert store.consume(t) is False
    assert store.consume("nope") is False
    t2 = store.issue()
    real = api_keys.time.monotonic()
    monkeypatch.setattr(api_keys.time, "monotonic", lambda: real + api_keys.TICKET_TTL_S + 1)
    assert store.consume(t2) is False


def _oidc_app(tmp_path):
    cfg = AppConfig(
        printer_mode="mock",
        data_dir=tmp_path / "data",
        printer_init_strategy="classic",
        printer_bit_order="msb_first",
        printer_flip_pins=False,
        homebox_url=None,
        homebox_api_key=None,
        els_enabled=False,
        els_tape_mm=24.0,
        oidc_scopes="openid profile email",
        **_OIDC_APP_CONFIG_OVERRIDES,
    )
    return create_app(cfg)


def test_ws_ticket_flow_single_use_and_bearer_header(tmp_path):
    with TestClient(_oidc_app(tmp_path)) as c:
        # No credentials: refused.
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/v1/ws"):
            pass
        plaintext = "lm_" + "A" * 43

        async def seed():
            await c.app.state.db.create_api_key(
                "t", "read", api_keys.lookup_prefix(plaintext), api_keys.hash_key(plaintext)
            )

        c.portal.call(seed)
        ticket = c.post(
            "/api/v1/ws-ticket", headers={"Authorization": f"Bearer {plaintext}"}
        ).json()
        assert ticket["expires_in"] == 60
        with c.websocket_connect(f"/api/v1/ws?ticket={ticket['ticket']}"):
            pass
        with (
            pytest.raises(WebSocketDisconnect),
            c.websocket_connect(f"/api/v1/ws?ticket={ticket['ticket']}"),
        ):
            pass
        with c.websocket_connect("/api/v1/ws", headers={"Authorization": f"Bearer {plaintext}"}):
            pass
