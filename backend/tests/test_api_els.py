"""Tests for GET /api/els/label (task 3.5): HomeBox's External Label Service.

Pins the CONTRACT documented in router_els.py's own get_els_label: this
route is registered UNCONDITIONALLY (main.py) -- `els_enabled` is
DB-editable now (task 4.5 Track A, see settings_overlay.py), so it can no
longer be decided once, at startup, by whether the route exists at all.
Instead the route answers 404 -- never 503, there's no auth barrier to gate
behind -- on every request unless the settings overlay's EFFECTIVE
`els_enabled` is on. A configured deployment renders a real decodable PNG at
the `els_tape_mm` tape's native device-pixel height, the QR encodes the
`URL` param verbatim, missing/malformed query params 422 the same readable
way every other `render_definition` caller in this app does, and nothing
about the route depends on -- or is blocked by -- HomeBox's own
`User-Agent`.

Not a golden suite: nothing here byte-locks a render (homebox_location's own
golden fixtures already do that -- see test_homebox_types.py). These tests
exercise the HTTP contract layered on top of it.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from labelmaker.render.document import Tape

_ENABLED = pytest.mark.parametrize("app_config", [{"els_enabled": True}], indirect=True)
_ENABLED_9MM = pytest.mark.parametrize(
    "app_config", [{"els_enabled": True, "els_tape_mm": 9.0}], indirect=True
)

_HB_USER_AGENT = "Homebox-LabelMaker/1.0"

# A representative real request: HomeBox's own HandleGetAssetLabel shape --
# TitleText is the short asset id, DescriptionText carries the item name
# plus a "\nLocation: X" line (see router_els.py's module docstring), and
# AdditionalInformation is the optional admin-configured constant.
_ASSET_PARAMS = {
    "TitleText": "000-042",
    "DescriptionText": "APC Smart-UPS 1500\nLocation: Garage",
    "URL": "https://homebox.example.com/a/000-042",
    "AdditionalInformation": "inv.example.com",
    # HomeBox always sends these too (see labelmaker.go's fetchLabelFromURL)
    # -- included here so the "real request" fixture matches the wire
    # contract exactly, even though this endpoint ignores all of them.
    "Width": "320",
    "Height": "240",
    "QrSize": "140",
    "Margin": "8",
    "ComponentPadding": "6",
    "TitleFontSize": "32.000000",
    "DescriptionFontSize": "25.600000",
    "Dpi": "72.000000",
    "DynamicLength": "false",
}


async def test_disabled_by_default_returns_404(client):
    resp = await client.get("/api/els/label", params=_ASSET_PARAMS)
    assert resp.status_code == 404


async def test_enabled_via_settings_put_gates_the_route_same_as_app_config(client):
    """els_enabled (task 4.5 Track A) is DB-editable from the Settings page
    -- unlike every other test in this file, which flips it via the
    app_config-level `_ENABLED`/`_ENABLED_9MM` markers (the env tier), this
    one flips it through PUT /api/settings (the db tier) instead, and must
    gate/ungate this route identically either way."""
    resp = await client.put("/api/settings", json={"els_enabled": True})
    assert resp.status_code == 200

    resp = await client.get("/api/els/label", params=_ASSET_PARAMS)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"

    resp = await client.put("/api/settings", json={"els_enabled": False})
    assert resp.status_code == 200

    resp = await client.get("/api/els/label", params=_ASSET_PARAMS)
    assert resp.status_code == 404


@_ENABLED
async def test_enabled_renders_decodable_png_at_native_tape_height(app_and_client):
    app, client = app_and_client
    resp = await client.get("/api/els/label", params=_ASSET_PARAMS)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"

    img = Image.open(io.BytesIO(resp.content))
    assert img.format == "PNG"
    tape = Tape(width_mm=app.state.config.els_tape_mm, family="tze").resolve()
    assert img.height == tape.print_dots
    assert img.width > 0


@_ENABLED_9MM
async def test_els_tape_mm_config_changes_rendered_height(app_and_client):
    app, client = app_and_client
    resp = await client.get("/api/els/label", params=_ASSET_PARAMS)
    assert resp.status_code == 200
    img = Image.open(io.BytesIO(resp.content))
    tape = Tape(width_mm=9.0, family="tze").resolve()
    assert img.height == tape.print_dots
    assert tape.print_dots != Tape(width_mm=24.0, family="tze").resolve().print_dots


@_ENABLED
async def test_qr_decodes_to_url_param(app_and_client):
    zxingcpp = pytest.importorskip("zxingcpp")
    _, client = app_and_client
    resp = await client.get("/api/els/label", params=_ASSET_PARAMS)
    assert resp.status_code == 200

    img = Image.open(io.BytesIO(resp.content))
    barcode_read = zxingcpp.read_barcode(img.convert("L"))
    assert barcode_read is not None, "zxing-cpp could not decode the label's QR at all"
    assert barcode_read.text == _ASSET_PARAMS["URL"]
    assert barcode_read.format == zxingcpp.BarcodeFormat.QRCode


@_ENABLED
async def test_missing_required_param_is_422(app_and_client):
    _, client = app_and_client
    params = dict(_ASSET_PARAMS)
    del params["URL"]
    resp = await client.get("/api/els/label", params=params)
    assert resp.status_code == 422


@_ENABLED
async def test_invalid_param_type_is_422(app_and_client):
    _, client = app_and_client
    params = {**_ASSET_PARAMS, "Width": "not-a-number"}
    resp = await client.get("/api/els/label", params=params)
    assert resp.status_code == 422


@_ENABLED
async def test_overlong_title_text_is_422_not_silently_truncated(app_and_client):
    """`TitleText` maps onto homebox_location.Params.name (1-120 chars, see
    router_els.py's own mapping docstring) -- over that bound is a normal
    render_definition 422, the same as any other over-length field in this
    app, not a silent truncation."""
    _, client = app_and_client
    params = {**_ASSET_PARAMS, "TitleText": "A" * 121}
    resp = await client.get("/api/els/label", params=params)
    assert resp.status_code == 422


@_ENABLED
async def test_top_level_item_with_empty_description_still_renders(app_and_client):
    """HandleGetItemLabel's DescriptionText is genuinely "" for a top-level
    item (no parent) -- this must NOT 422 (see router_els.py's own
    rationale for mapping onto homebox_location, not homebox_asset)."""
    _, client = app_and_client
    params = {
        **_ASSET_PARAMS,
        "TitleText": "Cordless Drill",
        "DescriptionText": "",
    }
    del params["AdditionalInformation"]
    resp = await client.get("/api/els/label", params=params)
    assert resp.status_code == 200


@_ENABLED
async def test_homebox_user_agent_hits_no_auth_barrier(app_and_client):
    """The route is unauthenticated by design (see AppConfig.els_enabled's
    own docstring) -- a request carrying HomeBox's real User-Agent, with no
    credentials at all, must succeed exactly like any other client."""
    _, client = app_and_client
    resp = await client.get(
        "/api/els/label", params=_ASSET_PARAMS, headers={"User-Agent": _HB_USER_AGENT}
    )
    assert resp.status_code == 200
