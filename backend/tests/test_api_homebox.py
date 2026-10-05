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

import re

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
        "configured": False, "reachable": None, "healthy": None,
        "version": None, "error": None,
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
                    "id": "l1", "name": "Garage", "type": "location",
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
                "page": 1, "pageSize": 50, "total": 2,
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
    hb_mock.get(f"{API}/status").mock(
        return_value=httpx.Response(200, text="<html>Sign in</html>")
    )
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


# -- writes (homebox_writes_enabled) ---------------------------------------

_WRITES = pytest.mark.parametrize(
    "app_config",
    [{"homebox_url": BASE, "homebox_api_key": "hb_k", "homebox_writes_enabled": True}],
    indirect=True,
)
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32


def _created(name: str, asset_id: str = "000-001", **kw) -> dict:
    return {"id": f"id-{name}", "name": name, "assetId": asset_id, **kw}


@_CONFIGURED
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/homebox/entities/bulk", {"json": {"parent_id": "p", "names": ["a"]}}),
        ("post", "/api/homebox/entities/e1/attachments", {"files": {"file": ("a.jpg", _JPEG)}}),
        ("get", "/api/homebox/tags", {}),
        ("get", "/api/homebox/entity-types", {}),
    ],
)
async def test_write_routes_403_when_disabled(app_and_client, method, path, kwargs):
    _, client = app_and_client
    resp = await getattr(client, method)(path, **kwargs)
    assert resp.status_code == 403
    assert resp.json() == {"detail": "homebox writes disabled"}


@_WRITES
async def test_bulk_create_in_order_with_partial_failure(app_and_client, hb_mock):
    route = hb_mock.post(f"{API}/entities").mock(
        side_effect=[
            httpx.Response(201, json=_created("A", "000-001")),
            httpx.Response(422, text="name too long"),
            httpx.Response(201, json=_created("C", "000-002")),
        ]
    )
    _, client = app_and_client
    resp = await client.post(
        "/api/homebox/entities/bulk",
        json={"parent_id": "p", "tag_ids": ["t1"], "names": [" A ", "B", "C"], "quantity": 1},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["ok"] for r in results] == [True, False, True]
    assert results[0] == {
        "index": 0, "ok": True, "error": None,
        "entity": {"id": "id-A", "name": "A", "asset_id": "000-001"},
    }
    assert results[1]["entity"] is None
    assert "422" in results[1]["error"]
    assert route.call_count == 3
    import json

    sent = json.loads(route.calls[0].request.content)
    assert sent == {"name": "A", "parentId": "p", "tagIds": ["t1"], "quantity": 1}


@_WRITES
async def test_bulk_create_aborts_on_upstream_auth_error(app_and_client, hb_mock):
    route = hb_mock.post(f"{API}/entities").mock(return_value=httpx.Response(401))
    _, client = app_and_client
    resp = await client.post(
        "/api/homebox/entities/bulk", json={"parent_id": "p", "names": ["a", "b", "c"]}
    )
    assert resp.status_code == 502
    assert "rejected the API key" in resp.json()["detail"]
    assert route.call_count == 1


@_WRITES
@pytest.mark.parametrize(
    "names", [["x"] * 101, [], ["ok", "   "], ["y" * 256]], ids=["101", "none", "blank", "long"]
)
async def test_bulk_create_rejects_bad_names(app_and_client, names):
    _, client = app_and_client
    resp = await client.post("/api/homebox/entities/bulk", json={"parent_id": "p", "names": names})
    assert resp.status_code == 422


@_WRITES
async def test_upload_photo_ok_builds_filename_and_returns_attachment_id(app_and_client, hb_mock):
    hb_mock.get(f"{API}/entities/e1").mock(
        return_value=httpx.Response(200, json=_created("A", "000-042"))
    )
    route = hb_mock.post(f"{API}/entities/e1/attachments").mock(
        side_effect=lambda req: httpx.Response(
            201,
            json={
                **_created("A", "000-042"),
                "attachments": [{"id": "att9", "title": _filename_from(req)}],
            },
        )
    )
    _, client = app_and_client
    resp = await client.post(
        "/api/homebox/entities/e1/attachments",
        files={"file": ("whatever.bin", _PNG, "application/octet-stream")},
        data={"primary": "true"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"entity_id": "e1", "attachment_id": "att9", "primary": True}
    name = _filename_from(route.calls[0].request)
    assert re.fullmatch(r"000-042-\d{8}T\d{6}Z\.png", name)
    assert b"image/png" in route.calls[0].request.content
    assert b'name="primary"\r\n\r\ntrue' in route.calls[0].request.content


def _filename_from(req) -> str:
    return re.search(rb'filename="([^"]+)"', req.content).group(1).decode()


@_WRITES
async def test_upload_photo_heic_by_magic_even_with_wrong_header(app_and_client, hb_mock):
    hb_mock.get(f"{API}/entities/e1").mock(return_value=httpx.Response(200, json=_created("A", "")))
    route = hb_mock.post(f"{API}/entities/e1/attachments").mock(
        return_value=httpx.Response(201, json=_created("A", ""))
    )
    _, client = app_and_client
    resp = await client.post(
        "/api/homebox/entities/e1/attachments",
        files={"file": ("x.txt", _HEIC, "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["attachment_id"] is None
    assert re.fullmatch(r"id-A-\d{8}T\d{6}Z\.heic", _filename_from(route.calls[0].request))


@_WRITES
async def test_upload_photo_bad_magic_is_415_even_if_header_says_jpeg(app_and_client):
    _, client = app_and_client
    resp = await client.post(
        "/api/homebox/entities/e1/attachments",
        files={"file": ("a.jpg", b"GIF89a" + b"\x00" * 20, "image/jpeg")},
    )
    assert resp.status_code == 415


@_WRITES
async def test_upload_photo_over_cap_is_413(app_and_client, monkeypatch):
    monkeypatch.setattr("labelmaker.api.router_homebox.MAX_PHOTO_BYTES", 1024)
    _, client = app_and_client
    resp = await client.post(
        "/api/homebox/entities/e1/attachments",
        files={"file": ("a.jpg", _JPEG + b"\x00" * 2048, "image/jpeg")},
    )
    assert resp.status_code == 413


@_WRITES
async def test_tags_and_entity_types_and_upstream_422(app_and_client, hb_mock):
    hb_mock.get(f"{API}/tags").mock(
        return_value=httpx.Response(200, json=[{"id": "t1", "name": "x", "color": "#fff"}])
    )
    hb_mock.get(f"{API}/entity-types").mock(return_value=httpx.Response(422, text="bad"))
    _, client = app_and_client
    resp = await client.get("/api/homebox/tags")
    assert resp.json() == [{"id": "t1", "name": "x"}]
    assert (await client.get("/api/homebox/entity-types")).status_code == 422


_OIDC_WRITES = pytest.mark.parametrize(
    "app_config",
    [
        {
            "homebox_url": BASE,
            "homebox_api_key": "hb_k",
            "homebox_writes_enabled": True,
            "auth_mode": "oidc",
            "oidc_issuer": "https://idp.test",
            "oidc_client_id": "cid",
            "oidc_client_secret": "secret",
            "session_secret": "unit-test-session-secret-do-not-reuse",
        }
    ],
    indirect=True,
)


@_OIDC_WRITES
async def test_write_routes_require_auth_in_oidc_mode(client):
    resp = await client.post(
        "/api/homebox/entities/bulk", json={"parent_id": "p", "names": ["a"]}
    )
    assert resp.status_code == 401
    assert (await client.get("/api/homebox/tags")).status_code == 401
