"""Tests for POST /api/render/preview.

Byte-parity against calling render_definition + rasterize + preview_png
directly is the core guarantee this endpoint must uphold (see
labelmaker.render's module docstring: preview and print are the same
bitmap) -- these tests assert that byte-for-byte, not just "looks similar".
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from labelmaker.driver.geometry import dots_to_mm
from labelmaker.render import preview_png, rasterize, render_definition
from labelmaker.render.document import LabelDefinition

_HELLO_DEFINITION = {
    "type": "text",
    "tape": {"width_mm": 24, "family": "tze"},
    "params": {"lines": ["HELLO"]},
}


async def test_preview_returns_expected_scaled_png_byte_equal_to_direct_pipeline(client):
    resp = await client.post(
        "/api/render/preview", json={"definition": _HELLO_DEFINITION, "scale": 3}
    )
    assert resp.status_code == 200
    body = resp.json()

    png_bytes = base64.b64decode(body["png_b64"])
    img = Image.open(io.BytesIO(png_bytes))
    assert img.size == (body["width_px"], body["height_px"])

    defn = LabelDefinition.model_validate(_HELLO_DEFINITION)
    rendered = render_definition(defn)
    expected_png = preview_png(rasterize(rendered), scale=3)
    assert png_bytes == expected_png

    assert img.size == (rendered.width_px * 3, rendered.height_px * 3)
    assert body["length_mm"] == round(dots_to_mm(rendered.width_px), 1)
    assert body["warnings"] == []


async def test_preview_default_scale_is_2(client):
    resp = await client.post("/api/render/preview", json={"definition": _HELLO_DEFINITION})
    assert resp.status_code == 200
    body = resp.json()
    png_bytes = base64.b64decode(body["png_b64"])
    img = Image.open(io.BytesIO(png_bytes))
    assert img.size == (body["width_px"], body["height_px"])

    defn = LabelDefinition.model_validate(_HELLO_DEFINITION)
    expected_png = preview_png(rasterize(render_definition(defn)), scale=2)
    assert png_bytes == expected_png


async def test_preview_warnings_pass_through_on_cramped_text(client):
    cramped_definition = {
        "type": "text",
        "tape": {"width_mm": 3.5, "family": "tze"},
        "params": {"lines": ["A", "B", "C", "D"]},
    }
    resp = await client.post(
        "/api/render/preview", json={"definition": cramped_definition, "scale": 1}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any("cramped" in w or "minimum" in w for w in body["warnings"])


async def test_preview_unknown_type_returns_422_listing_valid_types(client):
    bad_definition = {**_HELLO_DEFINITION, "type": "does-not-exist"}
    resp = await client.post("/api/render/preview", json={"definition": bad_definition, "scale": 1})
    assert resp.status_code == 422
    assert "text" in resp.json()["detail"]


async def test_preview_bad_tape_width_returns_422(client):
    bad_definition = {**_HELLO_DEFINITION, "tape": {"width_mm": 999, "family": "tze"}}
    resp = await client.post("/api/render/preview", json={"definition": bad_definition, "scale": 1})
    assert resp.status_code == 422
    assert "999" in resp.json()["detail"]


async def test_preview_scale_out_of_range_returns_422(client):
    resp = await client.post(
        "/api/render/preview", json={"definition": _HELLO_DEFINITION, "scale": 9}
    )
    assert resp.status_code == 422
