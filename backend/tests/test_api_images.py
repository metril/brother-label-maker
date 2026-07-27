"""Tests for POST/GET/DELETE /api/images (task 2.7): upload, serve, delete.

Byte-cap and megapixel-cap rejections are the load-bearing cases here (the
2.4 review's "enforce caps before materializing the payload" lesson,
applied to two different expensive operations -- see router_images.py's
module docstring for exactly which). Everything else in render/images.py
itself (threshold/dither embedding math) is covered by test_images.py --
this file only exercises the upload/serve/delete HTTP surface.
"""

from __future__ import annotations

import io
import struct
import uuid
import zlib

import pytest
from PIL import Image

from labelmaker.api.router_images import MAX_DECODED_PIXELS, MAX_UPLOAD_BYTES


def _png_bytes(width: int = 20, height: int = 10, color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(width: int = 20, height: int = 10, color=(50, 200, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()


def _webp_bytes(width: int = 20, height: int = 10, color=(50, 50, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="WEBP")
    return buf.getvalue()


def _rgba_png_bytes(width: int = 10, height: int = 10) -> bytes:
    img = Image.new("RGBA", (width, height), (10, 20, 30, 0))  # fully transparent
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def _fake_huge_png_header(width: int, height: int) -> bytes:
    """A structurally-valid PNG whose IHDR alone declares `width`x`height` --
    Image.open() parses this fine (and reports .size correctly) without
    ever decoding the (deliberately garbage) IDAT payload, exactly the
    "reject before .load()" case router_images.py guards against. Real
    pixel data was never generated -- this file is a few dozen bytes on
    disk regardless of how large `width`/`height` claim to be.
    """
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    idat = _png_chunk(b"IDAT", b"\x00" * 8)  # garbage -- never decoded
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


# --- 1. Happy path: PNG / JPEG / WEBP ---------------------------------------


async def test_upload_png_happy_path(client):
    resp = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes(30, 15)), "image/png")}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["width"] == 30
    assert body["height"] == 15
    assert len(body["image_id"]) == 32  # uuid4().hex


async def test_upload_jpeg_happy_path(client):
    resp = await client.post(
        "/api/images",
        files={"file": ("photo.jpg", io.BytesIO(_jpeg_bytes(24, 12)), "image/jpeg")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["width"] == 24
    assert body["height"] == 12


async def test_upload_webp_happy_path(client):
    resp = await client.post(
        "/api/images",
        files={"file": ("pic.webp", io.BytesIO(_webp_bytes(16, 8)), "image/webp")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["width"] == 16
    assert body["height"] == 8


# --- 2. GET /api/images/{id} -------------------------------------------------


async def test_get_uploaded_image_returns_png_bytes(client):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]
    resp = await client.get(f"/api/images/{image_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    decoded = Image.open(io.BytesIO(resp.content))
    assert decoded.format == "PNG"
    assert decoded.size == (20, 10)


async def test_get_unknown_image_id_returns_404(client):
    resp = await client.get("/api/images/deadbeefdeadbeefdeadbeefdeadbeef")
    assert resp.status_code == 404


async def test_get_malformed_image_id_returns_404(client):
    resp = await client.get("/api/images/not-a-valid-id")
    assert resp.status_code == 404


# --- 3. DELETE /api/images/{id} ---------------------------------------------


async def test_delete_uploaded_image_then_get_404s(client):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]
    delete_resp = await client.delete(f"/api/images/{image_id}")
    assert delete_resp.status_code == 204
    get_resp = await client.get(f"/api/images/{image_id}")
    assert get_resp.status_code == 404


async def test_delete_unknown_image_id_returns_404(client):
    resp = await client.delete("/api/images/deadbeefdeadbeefdeadbeefdeadbeef")
    assert resp.status_code == 404


# --- 3b. SECURITY (coordinator review fix-up): a REGEX-VALID id whose ------
# resolved path escapes uploads_dir/ (e.g. a symlink planted inside it)
# must still 404, never a raw 500. image_path()'s containment check
# raises ValueError for exactly this case even though the id itself
# passes _validate_image_id's shape pre-check -- GET/DELETE must catch
# that, not just trust the regex.


async def test_get_symlinked_but_well_formed_image_id_returns_404_not_500(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    outside = data_dir.parent / "outside-uploads"
    outside.mkdir(parents=True, exist_ok=True)
    secret = outside / "secret.png"
    secret.write_bytes(_png_bytes())

    image_id = uuid.uuid4().hex  # well-formed -- passes IMAGE_ID_RE
    (uploads / f"{image_id}.png").symlink_to(secret)

    resp = await client.get(f"/api/images/{image_id}")
    assert resp.status_code == 404


async def test_delete_symlinked_but_well_formed_image_id_returns_404_not_500(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    outside = data_dir.parent / "outside-uploads"
    outside.mkdir(parents=True, exist_ok=True)
    secret = outside / "secret.png"
    secret.write_bytes(_png_bytes())

    image_id = uuid.uuid4().hex
    symlink = uploads / f"{image_id}.png"
    symlink.symlink_to(secret)

    resp = await client.delete(f"/api/images/{image_id}")
    assert resp.status_code == 404
    # The symlink itself (and definitely the real secret file it points
    # at) must survive an ostensibly-rejected delete.
    assert secret.is_file()


# --- 4. PNG normalization: RGBA flattened onto white ------------------------


async def test_rgba_upload_is_flattened_onto_white(client):
    upload = await client.post(
        "/api/images",
        files={"file": ("transparent.png", io.BytesIO(_rgba_png_bytes()), "image/png")},
    )
    assert upload.status_code == 201
    image_id = upload.json()["image_id"]
    resp = await client.get(f"/api/images/{image_id}")
    decoded = Image.open(io.BytesIO(resp.content))
    assert decoded.mode == "RGB"  # no alpha channel survives
    assert decoded.getpixel((0, 0)) == (255, 255, 255)  # fully-transparent -> white


# --- 5. Byte cap (10MB) ------------------------------------------------------


async def test_upload_over_byte_cap_rejected(client):
    oversized = b"\x00" * (MAX_UPLOAD_BYTES + 1)
    resp = await client.post(
        "/api/images", files={"file": ("big.png", io.BytesIO(oversized), "image/png")}
    )
    assert resp.status_code == 422
    assert str(MAX_UPLOAD_BYTES) in resp.json()["detail"]


async def test_upload_content_length_precheck_rejects_before_reading_body():
    # Exercises the Content-Length fast-path directly (see router_images.
    # _read_capped): a request that DECLARES an over-cap size is rejected
    # from its header alone, without needing this test to actually
    # construct/send an oversized body end-to-end (already covered by
    # test_upload_over_byte_cap_rejected above).
    from fastapi import HTTPException

    from labelmaker.api.router_images import _read_capped

    class _FakeRequest:
        headers = {"content-length": str(MAX_UPLOAD_BYTES + 1)}

    class _FakeUploadFile:
        async def read(self, _n):  # pragma: no cover -- must never be called
            raise AssertionError("body must not be read once Content-Length exceeds the cap")

    with pytest.raises(HTTPException) as exc_info:
        await _read_capped(_FakeRequest(), _FakeUploadFile())
    assert exc_info.value.status_code == 422
    assert str(MAX_UPLOAD_BYTES + 1) in exc_info.value.detail


# --- 6. Megapixel cap (8MP), rejected BEFORE decode -------------------------


async def test_upload_over_megapixel_cap_rejected_via_fake_header(client):
    # 4000x3000 = 12,000,000 px: over our 8MP cap, but well under Pillow's
    # OWN much-higher built-in decompression-bomb guard (~89.5MP) -- this
    # specifically exercises router_images.py's own MAX_DECODED_PIXELS
    # check, not Pillow's. The file is a few dozen bytes; no 12MP raw
    # buffer is ever allocated (this is the whole point of the guard).
    data = _fake_huge_png_header(4000, 3000)
    resp = await client.post(
        "/api/images", files={"file": ("huge.png", io.BytesIO(data), "image/png")}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "12000000" in detail
    assert str(MAX_DECODED_PIXELS) in detail


async def test_upload_extreme_dimensions_hitting_pillows_own_bomb_guard_still_422s(client):
    # Large enough to trip Pillow's OWN DecompressionBombError from inside
    # Image.open() itself (~89.5MP default) -- still surfaced as a clean
    # 422, not a 500, by router_images.py's dedicated except clause.
    data = _fake_huge_png_header(20000, 20000)
    resp = await client.post(
        "/api/images", files={"file": ("bomb.png", io.BytesIO(data), "image/png")}
    )
    assert resp.status_code == 422


async def test_upload_at_exactly_the_megapixel_cap_is_accepted(client):
    width, height = 2000, 4000  # exactly 8,000,000 == MAX_DECODED_PIXELS
    assert width * height == MAX_DECODED_PIXELS
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (1, 2, 3)).save(buf, format="PNG")
    resp = await client.post(
        "/api/images", files={"file": ("edge.png", io.BytesIO(buf.getvalue()), "image/png")}
    )
    assert resp.status_code == 201
    assert resp.json()["width"] * resp.json()["height"] == MAX_DECODED_PIXELS


# --- 7. Format / decode rejections ------------------------------------------


async def test_upload_empty_file_rejected(client):
    resp = await client.post(
        "/api/images", files={"file": ("empty.png", io.BytesIO(b""), "image/png")}
    )
    assert resp.status_code == 422


async def test_upload_undecodable_garbage_rejected(client):
    resp = await client.post(
        "/api/images",
        files={"file": ("junk.png", io.BytesIO(b"not an image at all, just text"), "image/png")},
    )
    assert resp.status_code == 422


async def test_upload_truncated_png_with_valid_header_rejected_not_500(client):
    # Header (IHDR) parses fine -- Image.open() and .size both succeed, so
    # this sails past the initial probe -- but the truncated IDAT stream
    # fails during the SECOND, full-decode Image.open()+.load() call. Must
    # still come back as a clean 422, not an unhandled 500.
    full = _png_bytes(50, 50)
    truncated = full[:60]  # cuts partway into IDAT; IHDR (with real size) survives intact
    resp = await client.post(
        "/api/images", files={"file": ("truncated.png", io.BytesIO(truncated), "image/png")}
    )
    assert resp.status_code == 422


async def test_upload_unsupported_format_bmp_rejected(client):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "green").save(buf, format="BMP")
    resp = await client.post(
        "/api/images", files={"file": ("pic.bmp", io.BytesIO(buf.getvalue()), "image/bmp")}
    )
    assert resp.status_code == 422
    assert "BMP" in resp.json()["detail"]
