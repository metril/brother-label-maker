"""Tests for /api/homebox/* (task 3.2): the HomeBox proxy routes and the
qr_base_url settings, exercised through the REAL app (the `client`/
`app_and_client` fixtures), not the HomeBoxClient directly (that's
test_homebox_client.py's job -- this file pins the HTTP layer built on top
of it: error-taxonomy-to-status-code mapping, param passthrough, and the
snake_case response shape this app's other routes all use).

Fixture note: the test client itself is httpx over `httpx.ASGITransport`
talking to host "test" (see conftest.py's `app_and_client`). respx's
default mocker patches httpcore's connection pools, which an explicit
ASGITransport never touches -- so `respx.mock` intercepts ONLY the app's
own outbound calls to https://hb.test, and the test client's requests
reach the ASGI app untouched with no pass_through route needed. (An
earlier draft carried a `route(host="test").pass_through()` -- it was a
no-op; review round removed it so nobody copies it as load-bearing.)

Only the tests that actually talk to upstream HomeBox use `hb_mock`; the
unconfigured-app and settings tests never reach it (settings are db-only,
and deps.get_homebox's 503 fires before any HomeBoxClient exists).
"""

from __future__ import annotations

import httpx
import pytest
import respx

BASE = "https://hb.test"
API = f"{BASE}/api/v1"

_CONFIGURED = pytest.mark.parametrize(
    "app_config",
    [{"homebox_url": BASE, "homebox_api_key": "hb_k"}],
    indirect=True,
)


@pytest.fixture
def hb_mock():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _entity_summary(**overrides) -> dict:
    row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Label printer",
        "assetId": "000-042",
        "archived": False,
        "entityType": {"id": "et-item", "name": "Item", "isLocation": False},
        "parent": {"id": "loc-1", "name": "Shelf B"},
    }
    row.update(overrides)
    return row


# -- status --------------------------------------------------------------


async def test_status_unconfigured_is_always_200(client):
    resp = await client.get("/api/homebox/status")
    assert resp.status_code == 200
    assert resp.json() == {
        "configured": False,
        "reachable": None,
        "healthy": None,
        "version": None,
        "error": None,
    }


@_CONFIGURED
async def test_status_configured_and_reachable_reports_version(app_and_client, hb_mock):
    hb_mock.get(f"{API}/status").mock(
        return_value=httpx.Response(200, json={"health": True, "build": {"version": "v0.26.2"}})
    )
    # /status also runs the generation probe (review finding #2), so a
    # healthy report requires /entities to answer as well.
    hb_mock.get(f"{API}/entities").mock(
        return_value=httpx.Response(200, json={"items": [], "page": 1, "pageSize": 1, "total": 0})
    )
    _, client = app_and_client
    resp = await client.get("/api/homebox/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["reachable"] is True
    assert body["healthy"] is True
    assert body["version"] == "v0.26.2"
    assert body["error"] is None


@_CONFIGURED
async def test_status_configured_upstream_down_is_still_200(app_and_client, hb_mock):
    hb_mock.get(f"{API}/status").mock(side_effect=httpx.ConnectError("refused"))
    _, client = app_and_client
    resp = await client.get("/api/homebox/status")
    assert resp.status_code == 200  # never a 5xx -- this is the frontend's show/hide probe
    body = resp.json()
    assert body["configured"] is True
    assert body["reachable"] is False
    assert body["healthy"] is None
    assert body["version"] is None
    assert body["error"] is not None


# -- unconfigured guard ----------------------------------------------------


async def test_entities_unconfigured_returns_503_with_setup_hint(client):
    resp = await client.get("/api/homebox/entities")
    assert resp.status_code == 503
    assert "HOMEBOX_URL" in resp.json()["detail"]


# -- entities list ----------------------------------------------------------


@_CONFIGURED
async def test_list_entities_passthrough_params_and_snake_case_response(app_and_client, hb_mock):
    route = hb_mock.get(f"{API}/entities").mock(
        return_value=httpx.Response(
            200,
            json={"items": [_entity_summary()], "page": 2, "pageSize": 10, "total": 11},
        )
    )
    _, client = app_and_client
    resp = await client.get(
        "/api/homebox/entities",
        params={"q": "printer", "page": 2, "page_size": 10, "parent_id": "loc-1"},
    )
    assert resp.status_code == 200

    # our query params -> upstream's documented names (q/page/pageSize/parentIds)
    upstream_params = httpx.QueryParams(route.calls.last.request.url.query.decode())
    assert upstream_params["q"] == "printer"
    assert upstream_params["page"] == "2"
    assert upstream_params["pageSize"] == "10"
    assert upstream_params.get_list("parentIds") == ["loc-1"]

    # our response -> OUR snake_case, not HomeBox's own wire casing
    body = resp.json()
    assert body["page_size"] == 10
    assert "pageSize" not in body
    item = body["items"][0]
    assert item["asset_id"] == "000-042"
    assert "assetId" not in item
    assert item["entity_type"]["is_location"] is False
    assert "isLocation" not in item["entity_type"]


@_CONFIGURED
async def test_upstream_401_maps_to_502_with_actionable_detail(app_and_client, hb_mock):
    hb_mock.get(f"{API}/entities").mock(return_value=httpx.Response(401))
    _, client = app_and_client
    resp = await client.get("/api/homebox/entities")
    assert resp.status_code == 502
    assert "HOMEBOX_API_KEY" in resp.json()["detail"]


# -- single entity ------------------------------------------------------


@_CONFIGURED
async def test_get_entity_ok(app_and_client, hb_mock):
    hb_mock.get(f"{API}/entities/abc").mock(
        return_value=httpx.Response(
            200,
            json=_entity_summary(
                serialNumber="SN-1", modelNumber="PT-E720BT", manufacturer="Brother"
            ),
        )
    )
    _, client = app_and_client
    resp = await client.get("/api/homebox/entities/abc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["serial_number"] == "SN-1"
    assert body["model_number"] == "PT-E720BT"
    assert "serialNumber" not in body


@_CONFIGURED
async def test_get_entity_upstream_404_is_our_404(app_and_client, hb_mock):
    hb_mock.get(f"{API}/entities/missing").mock(return_value=httpx.Response(404))
    _, client = app_and_client
    resp = await client.get("/api/homebox/entities/missing")
    assert resp.status_code == 404


# -- tree / path passthrough ----------------------------------------------


@_CONFIGURED
async def test_entities_tree_passthrough(app_and_client, hb_mock):
    route = hb_mock.get(f"{API}/entities/tree").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "l1",
                    "name": "Garage",
                    "type": "location",
                    "children": [
                        {"id": "l2", "name": "Shelf B", "type": "location", "children": []}
                    ],
                }
            ],
        )
    )
    _, client = app_and_client
    resp = await client.get("/api/homebox/entities/tree", params={"with_items": "true"})
    assert resp.status_code == 200
    upstream_params = httpx.QueryParams(route.calls.last.request.url.query.decode())
    assert upstream_params["withItems"] == "true"
    assert resp.json()[0]["children"][0]["name"] == "Shelf B"


@_CONFIGURED
async def test_entity_path_is_root_first(app_and_client, hb_mock):
    hb_mock.get(f"{API}/entities/abc/path").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "l1", "name": "Garage", "type": "location"},
                {"id": "l2", "name": "Shelf B", "type": "location"},
                {"id": "abc", "name": "Label printer", "type": "item"},
            ],
        )
    )
    _, client = app_and_client
    resp = await client.get("/api/homebox/entities/abc/path")
    assert resp.status_code == 200
    assert [seg["name"] for seg in resp.json()] == ["Garage", "Shelf B", "Label printer"]


# -- asset lookup ---------------------------------------------------------


@_CONFIGURED
async def test_find_by_asset_id_many_matches(app_and_client, hb_mock):
    hb_mock.get(f"{API}/assets/000-042").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [_entity_summary(), _entity_summary(id="dup", name="Duplicate")],
                "page": 1,
                "pageSize": 50,
                "total": 2,
            },
        )
    )
    _, client = app_and_client
    resp = await client.get("/api/homebox/assets/000-042")
    assert resp.status_code == 200
    assert [e["name"] for e in resp.json()] == ["Label printer", "Duplicate"]


@_CONFIGURED
async def test_find_by_asset_id_upstream_404_is_empty_list_not_an_error(app_and_client, hb_mock):
    hb_mock.get(f"{API}/assets/000-404").mock(return_value=httpx.Response(404))
    _, client = app_and_client
    resp = await client.get("/api/homebox/assets/000-404")
    assert resp.status_code == 200  # zero matches -- HomeBox's own disambiguation, not an error
    assert resp.json() == []


# -- settings (db-backed, no HomeBoxDep -- work with or without upstream) --


@_CONFIGURED
async def test_settings_roundtrip_when_configured(app_and_client):
    _, client = app_and_client

    resp = await client.get("/api/homebox/settings")
    assert resp.json() == {"qr_base_url": None, "effective_qr_base_url": BASE}

    resp = await client.put(
        "/api/homebox/settings", json={"qr_base_url": "https://public.example.com/"}
    )
    assert resp.status_code == 200
    # trailing slash stripped on the way in
    assert resp.json() == {
        "qr_base_url": "https://public.example.com",
        "effective_qr_base_url": "https://public.example.com",
    }

    resp = await client.get("/api/homebox/settings")
    assert resp.json()["qr_base_url"] == "https://public.example.com"

    resp = await client.put("/api/homebox/settings", json={"qr_base_url": None})
    assert resp.status_code == 200
    # None clears the override -- back to config.homebox_url
    assert resp.json() == {"qr_base_url": None, "effective_qr_base_url": BASE}


async def test_settings_unconfigured_effective_is_null_and_rejects_bad_scheme(client):
    resp = await client.get("/api/homebox/settings")
    assert resp.status_code == 200
    # no stored override AND no config.homebox_url to fall back to
    assert resp.json() == {"qr_base_url": None, "effective_qr_base_url": None}

    resp = await client.put("/api/homebox/settings", json={"qr_base_url": "ftp://x"})
    assert resp.status_code == 422


# --- review-round regressions: non-HomeBox upstreams and the version probe --


@_CONFIGURED
async def test_status_stays_200_when_upstream_answers_html(client, hb_mock):
    """An SSO login page / default vhost at HOMEBOX_URL: /v1/status answers
    200 but with HTML. The contract is ALWAYS 200 -- this must report
    reachable=False with a diagnostic, never a 500 (review finding #1)."""
    hb_mock.get(f"{API}/status").mock(return_value=httpx.Response(200, text="<html>Sign in</html>"))
    resp = await client.get("/api/homebox/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["reachable"] is False
    assert "not with a HomeBox API response" in body["error"]


@_CONFIGURED
async def test_status_reports_pre_merge_server_as_unhealthy_with_upgrade_hint(client, hb_mock):
    """A HomeBox v0.25: /v1/status is fine but /v1/entities 404s while
    /v1/items answers. The probe now runs inside /status (review finding
    #2), so the frontend sees reachable-but-unhealthy plus the upgrade
    instructions instead of healthy-then-502-everywhere."""
    hb_mock.get(f"{API}/status").mock(
        return_value=httpx.Response(200, json={"health": True, "build": {"version": "v0.25.1"}})
    )
    hb_mock.get(f"{API}/entities").mock(return_value=httpx.Response(404))
    hb_mock.get(f"{API}/items").mock(
        return_value=httpx.Response(200, json={"items": [], "page": 1, "pageSize": 1, "total": 0})
    )
    resp = await client.get("/api/homebox/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["healthy"] is False
    assert body["version"] == "v0.25.1"
    assert "v0.26" in body["error"]


@_CONFIGURED
async def test_proxy_routes_502_not_500_on_unparseable_upstream(client, hb_mock):
    """Same misconfigured-upstream class on a data route: non-JSON must map
    to the documented 502-with-detail, not an unhandled 500."""
    hb_mock.get(f"{API}/entities").mock(return_value=httpx.Response(200, text="<html></html>"))
    resp = await client.get("/api/homebox/entities")
    assert resp.status_code == 502
    assert "could not parse" in resp.json()["detail"]
