"""HomeBoxClient (task 3.1) against respx-mocked wire responses.

Every mocked payload below uses the field names from the LIVE v0.26.2
swagger (see client.py's module docstring) -- camelCase exactly as the
server sends them, so these tests pin the alias mapping, not just the
happy path. The optional live smoke against the real instance lives in
test_homebox_live.py.
"""

from __future__ import annotations

import contextlib

import httpx
import pytest
import respx

from labelmaker.homebox import (
    HomeBoxAuthError,
    HomeBoxClient,
    HomeBoxError,
    HomeBoxNotFoundError,
    HomeBoxUnavailableError,
    HomeBoxVersionError,
)

BASE = "https://hb.test"
API = f"{BASE}/api/v1"


@pytest.fixture
async def client():
    c = HomeBoxClient(BASE, "hb_testkey")
    yield c
    await c.close()


def _entity_summary(**overrides) -> dict:
    row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Label printer",
        "description": "Brother PT-E720BT",
        "assetId": "000-042",
        "archived": False,
        "quantity": 1,
        "entityType": {"id": "et-item", "name": "Item", "isLocation": False},
        "parent": {"id": "loc-1", "name": "Shelf B"},
        "tags": [{"id": "t1", "name": "electronics", "color": "#ff0000"}],
        "thumbnailId": None,
        "imageId": None,
        "createdAt": "2026-07-01T00:00:00Z",  # unmodeled -- must be ignored
    }
    row.update(overrides)
    return row


@respx.mock
async def test_bearer_header_and_api_prefix(client):
    route = respx.get(f"{API}/status").mock(
        return_value=httpx.Response(200, json={"health": True, "build": {"version": "v0.26.2"}})
    )
    status = await client.status()
    assert status.health is True
    assert status.build.version == "v0.26.2"
    assert route.calls.last.request.headers["Authorization"] == "Bearer hb_testkey"


@respx.mock
async def test_list_entities_sends_documented_params_and_parses(client):
    route = respx.get(f"{API}/entities").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [_entity_summary()],
                "page": 2,
                "pageSize": 10,
                "total": 11,
                "totalPrice": 0,  # unmodeled -- ignored
            },
        )
    )
    page = await client.list_entities(q="printer", page=2, page_size=10, parent_ids=["loc-1"])

    params = httpx.QueryParams(route.calls.last.request.url.query.decode())
    assert params["q"] == "printer"
    assert params["page"] == "2"
    assert params["pageSize"] == "10"
    assert params.get_list("parentIds") == ["loc-1"]

    assert page.total == 11 and page.page == 2 and page.page_size == 10
    item = page.items[0]
    assert item.asset_id == "000-042"
    assert item.entity_type is not None and item.entity_type.is_location is False
    assert item.parent is not None and item.parent.name == "Shelf B"
    assert item.tags[0].name == "electronics"


@respx.mock
async def test_get_entity_parses_full_shape_and_404s(client):
    respx.get(f"{API}/entities/abc").mock(
        return_value=httpx.Response(
            200,
            json=_entity_summary(
                serialNumber="SN-1", modelNumber="PT-E720BT", manufacturer="Brother", notes="n"
            ),
        )
    )
    entity = await client.get_entity("abc")
    assert entity.serial_number == "SN-1"
    assert entity.model_number == "PT-E720BT"
    assert entity.manufacturer == "Brother"

    respx.get(f"{API}/entities/missing").mock(return_value=httpx.Response(404))
    with pytest.raises(HomeBoxNotFoundError):
        await client.get_entity("missing")


@respx.mock
async def test_get_path_returns_root_first_chain(client):
    respx.get(f"{API}/entities/abc/path").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "l1", "name": "Garage", "type": "location"},
                {"id": "l2", "name": "Shelf B", "type": "location"},
                {"id": "abc", "name": "Label printer", "type": "item"},
            ],
        )
    )
    path = await client.get_path("abc")
    assert [seg.name for seg in path] == ["Garage", "Shelf B", "Label printer"]
    assert [seg.type for seg in path] == ["location", "location", "item"]


@respx.mock
async def test_get_tree_parses_recursively_and_passes_with_items(client):
    route = respx.get(f"{API}/entities/tree").mock(
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
    tree = await client.get_tree(with_items=True)
    params = httpx.QueryParams(route.calls.last.request.url.query.decode())
    assert params["withItems"] == "true"
    assert tree[0].children[0].name == "Shelf B"


@respx.mock
async def test_find_by_asset_id_zero_one_many(client):
    respx.get(f"{API}/assets/000-042").mock(
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
    many = await client.find_by_asset_id("000-042")
    assert [e.name for e in many] == ["Label printer", "Duplicate"]

    respx.get(f"{API}/assets/000-099").mock(
        return_value=httpx.Response(200, json={"items": [], "page": 1, "pageSize": 50, "total": 0})
    )
    assert await client.find_by_asset_id("000-099") == []

    # A 404 variant (route absent / no match on some builds) is zero, not an error.
    respx.get(f"{API}/assets/000-404").mock(return_value=httpx.Response(404))
    assert await client.find_by_asset_id("000-404") == []


@respx.mock
async def test_probe_passes_on_entities_generation(client):
    respx.get(f"{API}/entities").mock(
        return_value=httpx.Response(200, json={"items": [], "page": 1, "pageSize": 1, "total": 0})
    )
    await client.probe()  # no raise


@respx.mock
async def test_probe_names_the_version_problem_on_pre_merge_servers(client):
    respx.get(f"{API}/entities").mock(return_value=httpx.Response(404))
    respx.get(f"{API}/items").mock(
        return_value=httpx.Response(200, json={"items": [], "page": 1, "pageSize": 1, "total": 0})
    )
    with pytest.raises(HomeBoxVersionError, match="v0.26"):
        await client.probe()


@respx.mock
async def test_probe_distinguishes_not_homebox_from_old_homebox(client):
    respx.get(f"{API}/entities").mock(return_value=httpx.Response(404))
    respx.get(f"{API}/items").mock(return_value=httpx.Response(404))
    with pytest.raises(HomeBoxUnavailableError, match="HOMEBOX_URL"):
        await client.probe()


@respx.mock
async def test_auth_errors_are_named(client):
    respx.get(f"{API}/entities").mock(return_value=httpx.Response(401))
    with pytest.raises(HomeBoxAuthError, match="HOMEBOX_API_KEY"):
        await client.list_entities()


@respx.mock
async def test_transport_and_5xx_map_to_unavailable(client):
    respx.get(f"{API}/entities").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(HomeBoxUnavailableError, match="unreachable"):
        await client.list_entities()

    respx.get(f"{API}/status").mock(return_value=httpx.Response(500))
    with pytest.raises(HomeBoxUnavailableError, match="500"):
        await client.status()


async def test_base_url_trailing_slash_is_normalized():
    c = HomeBoxClient("https://hb.test/", "hb_k")
    try:
        # httpx canonicalizes base_url with a trailing slash; the double-"/"
        # the naive concat would produce ("hb.test//api/v1") must be absent.
        assert str(c._client.base_url) == "https://hb.test/api/v1/"
    finally:
        await c.close()


@respx.mock
async def test_ids_are_percent_encoded_into_one_path_segment(client):
    route = respx.get(url__regex=rf"{API}/(entities|assets)/.*").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    with contextlib.suppress(Exception):  # only the requested URL matters here
        await client.get_path("a/../../status?x=1#f")
    assert route.calls.last.request.url.raw_path == (
        b"/api/v1/entities/a%2F..%2F..%2Fstatus%3Fx%3D1%23f/path"
    )
    await client.find_by_asset_id("..")
    assert route.calls.last.request.url.raw_path.endswith(b"/assets/%2E%2E")


@respx.mock
async def test_4xx_error_body_is_truncated(client):
    respx.get(f"{API}/entities").mock(return_value=httpx.Response(400, text="x" * 5000))
    with pytest.raises(HomeBoxError) as excinfo:
        await client.list_entities()
    assert len(str(excinfo.value)) < 400
