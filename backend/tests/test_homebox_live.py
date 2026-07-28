"""Optional read-only smoke test against a REAL HomeBox instance.

Skipped unless all three env vars are set:

    HOMEBOX_LIVE=1 HOMEBOX_URL=... HOMEBOX_API_KEY=... uv run pytest tests/test_homebox_live.py -v

(The repo-root .env holds working values for the user's instance.) Every
call here is a GET -- nothing is created, mutated, or deleted. This is the
plan's "live smoke" for task 3.1: it proves the pinned swagger shapes hold
against the running server, not just the mocks.
"""

from __future__ import annotations

import os

import pytest

from labelmaker.homebox import HomeBoxClient

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("HOMEBOX_LIVE")
        and os.environ.get("HOMEBOX_URL")
        and os.environ.get("HOMEBOX_API_KEY")
    ),
    reason="live smoke needs HOMEBOX_LIVE=1 + HOMEBOX_URL + HOMEBOX_API_KEY",
)


@pytest.fixture
async def live():
    c = HomeBoxClient(os.environ["HOMEBOX_URL"], os.environ["HOMEBOX_API_KEY"])
    yield c
    await c.close()


async def test_status_healthy_and_v026(live):
    status = await live.status()
    assert status.health is True
    assert status.build.version >= "v0.26"


async def test_probe_accepts_this_instance(live):
    await live.probe()


async def test_list_parses_real_rows(live):
    page = await live.list_entities(page_size=5)
    assert page.total >= 0
    for item in page.items:
        assert item.id and item.name


async def test_tree_and_path_and_asset_lookup_round_trip(live):
    tree = await live.get_tree()
    assert isinstance(tree, list)

    page = await live.list_entities(page_size=50)
    if not page.items:
        pytest.skip("instance has no entities to exercise path/asset lookups")

    first = page.items[0]
    path = await live.get_path(first.id)
    assert path and path[-1].id == first.id

    tagged = next((e for e in page.items if e.asset_id and e.asset_id != "000-000"), None)
    if tagged is not None:
        matches = await live.find_by_asset_id(tagged.asset_id)
        assert any(e.id == tagged.id for e in matches)

    assert await live.find_by_asset_id("999-999999") == []
