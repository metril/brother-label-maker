"""App side of the printer bridge: identity endpoint, remote-mode settings
validation, and status over a real localhost bridge."""

from __future__ import annotations

import pytest

from labelmaker.driver.bridge import BridgeServer, server_context
from labelmaker.driver.bridge_identity import cert_fingerprint, ensure_identity
from labelmaker.driver.transport import MockPrinterTransport


@pytest.fixture
def bridge(tmp_path):
    """A running bridge (mock printer behind it) plus its public cert. Not yet
    paired: tests call `pair(app_pem)` once they know the app's certificate."""
    key, cert = ensure_identity(tmp_path / "bridge", "bridge")
    started: list[BridgeServer] = []

    class Handle:
        pem = cert.read_text()
        port = 0

        def pair(self, app_pem: str) -> None:
            server = BridgeServer(
                server_context(cert, key, app_pem),
                cert_fingerprint(app_pem),
                host="127.0.0.1",
                port=0,
                opener=MockPrinterTransport,
            )
            server.start()
            started.append(server)
            self.port = server.port

    yield Handle()
    for server in started:
        server.stop()


async def test_bridge_identity_returns_only_public_material(app_and_client):
    app, client = app_and_client
    resp = await client.get("/api/printer/bridge-identity")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"cert_pem", "fingerprint"}
    assert body["cert_pem"].startswith("-----BEGIN CERTIFICATE-----")
    assert "PRIVATE KEY" not in resp.text
    assert body["fingerprint"] == cert_fingerprint(body["cert_pem"])
    # stable across requests, key stays under data_dir/bridge
    again = (await client.get("/api/printer/bridge-identity")).json()
    assert again == body
    assert (app.state.config.data_dir / "bridge" / "client.key").is_file()


async def test_settings_never_expose_a_private_key(app_and_client, bridge):
    _app, client = app_and_client
    ident = (await client.get("/api/printer/bridge-identity")).json()
    resp = await client.put(
        "/api/settings",
        json={
            "printer_mode": "remote",
            "printer_bridge_address": "pi.local",
            "printer_bridge_cert": bridge.pem,
        },
    )
    assert resp.status_code == 200
    assert "PRIVATE KEY" not in resp.text
    assert ident["fingerprint"] not in resp.text  # the app's own cert isn't a setting


@pytest.mark.parametrize(
    "body",
    [
        {"printer_bridge_cert": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"},
        {"printer_bridge_cert": "not a cert"},
        {"printer_bridge_address": "host:99999"},
        {"printer_bridge_address": "has space"},
        {"printer_mode": "remote"},  # incomplete
    ],
)
async def test_settings_reject_bad_remote_config(client, body):
    resp = await client.put("/api/settings", json=body)
    assert resp.status_code == 422
    assert "PRIVATE KEY" not in resp.text


async def test_settings_reject_two_certs_and_clearing_a_required_field(client, bridge):
    resp = await client.put("/api/settings", json={"printer_bridge_cert": bridge.pem * 2})
    assert resp.status_code == 422
    ok = {
        "printer_mode": "remote",
        "printer_bridge_address": "[fe80::1]:9177",
        "printer_bridge_cert": bridge.pem,
    }
    assert (await client.put("/api/settings", json=ok)).status_code == 200
    resp = await client.put("/api/settings", json={"printer_bridge_address": None})
    assert resp.status_code == 422  # would leave remote mode half-configured
    resp = await client.put(
        "/api/settings", json={"printer_mode": "mock", "printer_bridge_address": None}
    )
    assert resp.status_code == 200


async def test_status_in_remote_mode_with_incomplete_config_reports_not_connected(
    app_and_client,
):
    app, client = app_and_client
    # Bypass save-time validation (e.g. a stale env/DB combination).
    app.state.settings._overrides["printer_mode"] = "remote"
    body = (await client.get("/api/printer/status")).json()
    assert body["connected"] is False
    assert body["printer_mode"] == "remote"
    assert "bridge address" in body["error"]


async def test_status_in_remote_mode_over_a_real_bridge(app_and_client, bridge):
    _app, client = app_and_client
    ident = (await client.get("/api/printer/bridge-identity")).json()
    bridge.pair(ident["cert_pem"])
    resp = await client.put(
        "/api/settings",
        json={
            "printer_mode": "remote",
            "printer_bridge_address": f"127.0.0.1:{bridge.port}",
            "printer_bridge_cert": bridge.pem,
        },
    )
    assert resp.status_code == 200
    body = (await client.get("/api/printer/status")).json()
    assert body["connected"] is True, body
    assert body["printer_mode"] == "remote"
    assert body["status"]["is_e720bt"] is True


async def test_status_in_remote_mode_unreachable_bridge_is_not_connected(app_and_client, bridge):
    _app, client = app_and_client
    await client.put(
        "/api/settings",
        json={
            "printer_mode": "remote",
            "printer_bridge_address": "127.0.0.1:1",
            "printer_bridge_cert": bridge.pem,
        },
    )
    body = (await client.get("/api/printer/status")).json()
    assert body["connected"] is False
    assert "cannot reach" in body["error"]
