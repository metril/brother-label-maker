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
from labelmaker.render.serialize import Sequence, expand_definition

_HELLO_DEFINITION = {
    "type": "text",
    "tape": {"width_mm": 24, "family": "tze"},
    "params": {"lines": ["HELLO"]},
}

_SERIAL_TEMPLATE = {
    "type": "text",
    "tape": {"width_mm": 24, "family": "tze"},
    "params": {"lines": ["Port {seq}"]},
}

_NUMERIC_1_TO_3 = {"kind": "numeric", "start": 1, "step": 1, "count": 3}


async def test_preview_returns_expected_scaled_png_byte_equal_to_direct_pipeline(client):
    resp = await client.post(
        "/api/render/preview", json={"definition": _HELLO_DEFINITION, "scale": 3}
    )
    assert resp.status_code == 200
    body = resp.json()

    png_bytes = base64.b64decode(body["png_b64"])
    img = Image.open(io.BytesIO(png_bytes))
    assert img.size == (body["png_width_px"], body["png_height_px"])

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
    assert img.size == (body["png_width_px"], body["png_height_px"])

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
    assert any(w["code"] == "text_cramped" for w in body["warnings"])
    assert all(w["severity"] == "warning" for w in body["warnings"])


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


async def test_preview_divided_blocks_engine_value_error_returns_422_with_message_intact(client):
    # Task 2.2 infra item 3: a ValueError raised by the divided-blocks
    # ENGINE itself (layout_blocks, called from inside patch_panel's
    # render()) -- not a pydantic ValidationError from Params, not
    # Tape.resolve()'s ValueError -- must surface as 422 with its message
    # unmangled. 4 blocks x 300mm (patch_panel's own max block_length_mm)
    # = 1200mm, which clears PatchPanelParams' own [5, 300] range but
    # exceeds this tze tape's 1000mm max_length_mm, so the ValueError comes
    # from layout_blocks (same message shape as
    # test_divided_blocks.py's test_total_above_tape_max_length_mm_raises).
    bad_definition = {
        "type": "patch_panel",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {
            "blocks": [{"lines": ["A"]} for _ in range(4)],
            "block_length_mm": 300.0,
        },
    }
    resp = await client.post(
        "/api/render/preview", json={"definition": bad_definition, "scale": 1}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "1200.0mm" in detail
    assert "1000.0" in detail


# --- task 2.4: `serialization` + `index` -----------------------------------


async def test_preview_without_serialization_has_null_total_labels_and_sequence_value(client):
    resp = await client.post(
        "/api/render/preview", json={"definition": _HELLO_DEFINITION, "scale": 1}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_labels"] is None
    assert body["sequence_value"] is None


async def test_preview_serialization_index_0_byte_parity(client):
    resp = await client.post(
        "/api/render/preview",
        json={"definition": _SERIAL_TEMPLATE, "scale": 1, "serialization": _NUMERIC_1_TO_3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_labels"] == 3
    assert body["sequence_value"] == "1"

    seq = Sequence.model_validate(_NUMERIC_1_TO_3)
    bound = expand_definition(_SERIAL_TEMPLATE, seq)
    expected_rendered = render_definition(LabelDefinition.model_validate(bound[0]))
    expected_png = preview_png(rasterize(expected_rendered), scale=1)
    assert base64.b64decode(body["png_b64"]) == expected_png


async def test_preview_serialization_index_mid_matches_that_labels_value(client):
    resp = await client.post(
        "/api/render/preview",
        json={
            "definition": _SERIAL_TEMPLATE,
            "scale": 1,
            "serialization": _NUMERIC_1_TO_3,
            "index": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sequence_value"] == "2"

    seq = Sequence.model_validate(_NUMERIC_1_TO_3)
    bound = expand_definition(_SERIAL_TEMPLATE, seq)
    expected_rendered = render_definition(LabelDefinition.model_validate(bound[1]))
    expected_png = preview_png(rasterize(expected_rendered), scale=1)
    assert base64.b64decode(body["png_b64"]) == expected_png


async def test_preview_serialization_index_out_of_range_returns_422(client):
    resp = await client.post(
        "/api/render/preview",
        json={
            "definition": _SERIAL_TEMPLATE,
            "scale": 1,
            "serialization": _NUMERIC_1_TO_3,
            "index": 3,
        },
    )
    assert resp.status_code == 422
    assert "3" in resp.json()["detail"]


async def test_preview_serialization_default_index_is_0(client):
    resp = await client.post(
        "/api/render/preview",
        json={"definition": _SERIAL_TEMPLATE, "scale": 1, "serialization": _NUMERIC_1_TO_3},
    )
    assert resp.status_code == 200
    assert resp.json()["sequence_value"] == "1"


async def test_preview_serialization_with_csv_binds_row_columns(client):
    template = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["{csv.name}"]},
    }
    serialization = {
        "kind": "csv",
        "rows": [{"name": "Alice"}, {"name": "Bob"}],
    }
    resp = await client.post(
        "/api/render/preview",
        json={"definition": template, "scale": 1, "serialization": serialization, "index": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_labels"] == 2

    seq = Sequence.model_validate(serialization)
    bound = expand_definition(template, seq)
    assert bound[1]["params"]["lines"] == ["Bob"]
    expected_png = preview_png(
        rasterize(render_definition(LabelDefinition.model_validate(bound[1]))), scale=1
    )
    assert base64.b64decode(body["png_b64"]) == expected_png


# --- task 2.7: preview of a "text" label with an `icon` --------------------
# End-to-end proof that the app's real data_dir (not a hand-built one, as
# test_text_label.py uses) is threaded from AppConfigDep through
# render_preview -> render_definition -> TextLabelRenderer.render -- an
# uploaded image's icon must resolve here, through the actual app + real
# tmp data_dir the `client` fixture wires up (see conftest.py's app_config).


async def test_preview_text_with_symbol_icon(client):
    definition = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["SERVER"], "icon": {"kind": "symbol", "id": "bolt"}},
    }
    resp = await client.post("/api/render/preview", json={"definition": definition, "scale": 1})
    assert resp.status_code == 200
    assert resp.json()["warnings"] == []


async def test_preview_text_with_image_icon_resolves_via_app_data_dir(client):
    upload = await client.post(
        "/api/images",
        files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert upload.status_code == 201
    image_id = upload.json()["image_id"]

    definition = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["CAM-3"], "icon": {"kind": "image", "image_id": image_id}},
    }
    resp = await client.post("/api/render/preview", json={"definition": definition, "scale": 1})
    assert resp.status_code == 200


async def test_preview_text_with_unknown_image_icon_returns_422(client):
    definition = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["CAM-3"], "icon": {"kind": "image", "image_id": "no-such-id"}},
    }
    resp = await client.post("/api/render/preview", json={"definition": definition, "scale": 1})
    assert resp.status_code == 422
    assert "unknown image_id" in resp.json()["detail"]


async def test_preview_text_with_unknown_symbol_icon_returns_422(client):
    definition = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["X"], "icon": {"kind": "symbol", "id": "not-a-real-icon"}},
    }
    resp = await client.post("/api/render/preview", json={"definition": definition, "scale": 1})
    assert resp.status_code == 422
    assert "unknown symbol id" in resp.json()["detail"]


def _png_bytes(width: int = 20, height: int = 10) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()
