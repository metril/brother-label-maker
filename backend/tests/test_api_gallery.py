"""GET /api/gallery (task 2.14): the curated visual-QA catalogue.

Not a golden suite -- nothing here byte-locks a render (the golden files
already do that for the underlying fixtures). These tests pin the gallery
CONTRACT: every entry renders through the real preview pipeline into a
decodable PNG of the right height, all eleven registered types are covered,
the response carries what the frontend needs (params for "Open in
designer", min_feed_mm for DeckStrip, short_label warning parity with
/api/render/preview), and the in-process cache actually short-circuits the
second request.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from labelmaker.api import router_gallery
from labelmaker.driver.geometry import MIN_FEED_MM
from labelmaker.render import list_types
from labelmaker.render.document import Tape
from labelmaker.render.gallery import gallery_entries


@pytest.fixture(autouse=True)
def _clear_gallery_cache():
    """The render cache is module-level (process-wide) by design -- clear it
    around every test so cards rendered by one test never satisfy another
    test's cache-behavior assertions."""
    router_gallery._cache.clear()
    yield
    router_gallery._cache.clear()


async def test_gallery_renders_every_entry_as_decodable_png(client):
    resp = await client.get("/api/gallery")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == len(gallery_entries())
    assert [item["id"] for item in items] == [entry.id for entry in gallery_entries()]

    for item in items:
        png = base64.b64decode(item["png_b64"])
        img = Image.open(io.BytesIO(png))
        tape = Tape(width_mm=item["tape"]["width_mm"], family=item["tape"]["family"]).resolve()
        # preview_png at scale 2 -- height is the tape's printable band, scaled.
        assert img.height == tape.print_dots * 2, item["id"]
        assert img.width > 0, item["id"]


async def test_gallery_covers_all_eleven_registered_types(client):
    resp = await client.get("/api/gallery")
    assert resp.status_code == 200
    covered = {item["type"] for item in resp.json()}
    registered = {info.type for info in list_types()}
    assert covered == registered
    assert len(registered) == 11


async def test_gallery_item_shape_supports_open_in_designer_and_deckstrip(client):
    resp = await client.get("/api/gallery")
    items = resp.json()
    for item in items:
        # "Open in designer" loads type+params+tape into the store; DeckStrip
        # needs length_mm + min_feed_mm. All must be present on every card.
        assert isinstance(item["params"], dict) and item["params"], item["id"]
        assert item["min_feed_mm"] == MIN_FEED_MM, item["id"]
        assert item["length_mm"] > 0, item["id"]
        assert isinstance(item["warnings"], list), item["id"]

    # short_label parity with /api/render/preview: any card under the feed
    # constant carries the same synthetic info warning the designer shows.
    for item in items:
        codes = {w["code"] for w in item["warnings"]}
        if item["length_mm"] < MIN_FEED_MM:
            assert "short_label" in codes, item["id"]


async def test_gallery_serialized_entry_pictures_first_instance(client):
    resp = await client.get("/api/gallery")
    by_id = {item["id"]: item for item in resp.json()}
    serialized = by_id["patch-panel-serialized"]
    # Sequence(kind=numeric, start=1, count=4) -> 4 labels, instance 0 = "1".
    assert serialized["total_labels"] == 4
    assert serialized["sequence_value"] == "1"
    # The response params stay the TEMPLATE (that's what Open-in-designer
    # loads), not the expanded instance.
    assert serialized["params"]["blocks"][0]["lines"] == ["{seq}-1"]
    # Every non-serialized card carries nulls.
    assert by_id["text-hello"]["total_labels"] is None
    assert by_id["text-hello"]["sequence_value"] is None


async def test_gallery_second_request_is_served_from_cache(client, monkeypatch):
    calls: list[str] = []
    real_render = router_gallery._render_entry

    def counting_render(entry, data_dir):
        calls.append(entry.id)
        return real_render(entry, data_dir)

    monkeypatch.setattr(router_gallery, "_render_entry", counting_render)

    first = await client.get("/api/gallery")
    second = await client.get("/api/gallery")
    assert first.status_code == second.status_code == 200
    # Rendered exactly once per entry across BOTH requests...
    assert sorted(calls) == sorted(entry.id for entry in gallery_entries())
    # ...and the second response is identical to the first.
    assert first.json() == second.json()
