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
import os
import re
import struct
import uuid
import zlib

import pytest
from PIL import Image

from labelmaker.api.router_images import MAX_DECODED_PIXELS, MAX_UPLOAD_BYTES, THUMBNAIL_MAX_EDGE


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


def _large_png_bytes(width: int = 800, height: int = 400, color=(90, 140, 210)) -> bytes:
    """Well over THUMBNAIL_MAX_EDGE on its longest edge -- unlike the
    module's default 20x10 `_png_bytes()`, a thumbnail generated from this
    one is actually SMALLER than the source, exercising the real shrink
    path rather than PIL's Image.thumbnail() no-op-on-already-small-source
    case."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
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


# --- 3c. Review L3: TOCTOU between the resolve-time is_file() check and ----
# the actual read/unlink -- a second app instance sharing data_dir, or an
# operator/cron pruning uploads/, can remove the file in that window.
# Simulated by monkeypatching _resolve_existing_image_path to delete the
# file the instant AFTER it passes the real resolve/existence check (so the
# route's own subsequent filesystem op is the one that races an empty
# path), rather than relying on real concurrency.


def _vanish_after_resolve(monkeypatch):
    import labelmaker.api.router_images as router_images_module

    original_resolve = router_images_module._resolve_existing_image_path

    def _resolve_then_delete(image_id, data_dir):
        path = original_resolve(image_id, data_dir)
        path.unlink()
        return path

    monkeypatch.setattr(router_images_module, "_resolve_existing_image_path", _resolve_then_delete)


async def test_get_image_404s_not_500s_when_file_vanishes_after_resolve(client, monkeypatch):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]

    _vanish_after_resolve(monkeypatch)
    resp = await client.get(f"/api/images/{image_id}")
    assert resp.status_code == 404


async def test_get_image_thumb_404s_not_500s_when_source_vanishes_after_resolve(
    client, monkeypatch
):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_large_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]

    _vanish_after_resolve(monkeypatch)
    # No thumb cached yet -- this must go through _generate_thumbnail,
    # which is what actually races the now-deleted source.
    resp = await client.get(f"/api/images/{image_id}/thumb")
    assert resp.status_code == 404


async def test_delete_image_404s_not_500s_when_file_vanishes_after_resolve(client, monkeypatch):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]

    _vanish_after_resolve(monkeypatch)
    resp = await client.delete(f"/api/images/{image_id}")
    assert resp.status_code == 404


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


# --- 8. GET /api/images (list, task D2a) -------------------------------------

_ISO_MTIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


async def test_list_images_empty_when_uploads_dir_missing(client):
    # A fresh data_dir has never had an upload -- uploads/ doesn't exist yet
    # at all. Must be an empty result, never a 500/404.
    resp = await client.get("/api/images")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


async def test_list_images_returns_uploaded_metadata(client):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes(30, 15)), "image/png")}
    )
    image_id = upload.json()["image_id"]

    resp = await client.get("/api/images")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["image_id"] == image_id
    assert item["width"] == 30
    assert item["height"] == 15
    assert item["size_bytes"] > 0
    assert _ISO_MTIME_RE.match(item["mtime"])


async def test_list_images_sorted_newest_first(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"

    first = await client.post(
        "/api/images", files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    second = await client.post(
        "/api/images", files={"file": ("b.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    first_id = first.json()["image_id"]
    second_id = second.json()["image_id"]

    # Force distinct, known mtimes -- some filesystems/CI runners don't have
    # fine enough timestamp resolution to trust upload ORDER alone to
    # produce distinct st_mtime values for two uploads microseconds apart.
    os.utime(uploads / f"{first_id}.png", (1_700_000_000, 1_700_000_000))
    os.utime(uploads / f"{second_id}.png", (1_700_000_100, 1_700_000_100))

    resp = await client.get("/api/images")
    assert resp.status_code == 200
    ids = [item["image_id"] for item in resp.json()["items"]]
    assert ids == [second_id, first_id]  # newest (later mtime) first


async def test_list_images_pagination_math(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"

    ids = []
    for i in range(3):
        resp = await client.post(
            "/api/images", files={"file": (f"{i}.png", io.BytesIO(_png_bytes()), "image/png")}
        )
        ids.append(resp.json()["image_id"])
    for i, image_id in enumerate(ids):
        os.utime(uploads / f"{image_id}.png", (1_700_000_000 + i, 1_700_000_000 + i))
    # ids[2] has the latest mtime, ids[0] the earliest -- newest-first order
    # is [ids[2], ids[1], ids[0]].

    page1 = await client.get("/api/images", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 3
    assert body1["page"] == 1
    assert body1["page_size"] == 2
    assert [item["image_id"] for item in body1["items"]] == [ids[2], ids[1]]

    page2 = await client.get("/api/images", params={"page": 2, "page_size": 2})
    assert page2.status_code == 200
    body2 = page2.json()
    assert body2["total"] == 3
    assert body2["page"] == 2
    assert [item["image_id"] for item in body2["items"]] == [ids[0]]

    page3 = await client.get("/api/images", params={"page": 3, "page_size": 2})
    assert page3.status_code == 200
    assert page3.json()["items"] == []
    assert page3.json()["total"] == 3


async def test_list_images_paged_items_carry_correct_per_item_metadata(app_and_client):
    # M7 (2026-08 review) rework: the scan is now a stat-first candidate
    # pass (sort/slice on mtime alone) followed by a PIL pass over ONLY the
    # survivors of that slice. This confirms the two-pass split still
    # attaches the RIGHT width/height/size_bytes/mtime to each image_id
    # after slicing -- on every page, not just page 1.
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"

    dims = [(30, 15), (12, 40), (60, 10)]
    ids = []
    for i, (w, h) in enumerate(dims):
        resp = await client.post(
            "/api/images",
            files={"file": (f"{i}.png", io.BytesIO(_png_bytes(w, h)), "image/png")},
        )
        ids.append(resp.json()["image_id"])
    for i, image_id in enumerate(ids):
        os.utime(uploads / f"{image_id}.png", (1_700_000_000 + i, 1_700_000_000 + i))
    expected_dims = {ids[0]: dims[0], ids[1]: dims[1], ids[2]: dims[2]}

    page1 = await client.get("/api/images", params={"page": 1, "page_size": 2})
    page2 = await client.get("/api/images", params={"page": 2, "page_size": 2})
    assert page1.status_code == 200
    assert page2.status_code == 200

    all_items = page1.json()["items"] + page2.json()["items"]
    assert {item["image_id"] for item in all_items} == set(ids)
    for item in all_items:
        width, height = expected_dims[item["image_id"]]
        assert (item["width"], item["height"]) == (width, height)
        assert item["size_bytes"] > 0
        assert _ISO_MTIME_RE.match(item["mtime"])


async def test_list_images_skips_corrupt_png_without_500_or_breaking_other_pages(app_and_client):
    # M7 (2026-08 review): the PIL header probe now runs AFTER stat-based
    # slicing, only on the (at most page_size) candidates that survive into
    # a given page. A candidate that passes the name/containment/stat
    # checks but fails to open as an image is dropped from THAT page
    # (silently, at DEBUG, per _list_uploaded_images' documented
    # page-shortfall behavior) -- it must never 500, and it must never
    # touch/affect a different page's candidates.
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    good_ids = []
    for i in range(2):
        resp = await client.post(
            "/api/images", files={"file": (f"{i}.png", io.BytesIO(_png_bytes()), "image/png")}
        )
        good_ids.append(resp.json()["image_id"])

    corrupt_id = uuid.uuid4().hex
    (uploads / f"{corrupt_id}.png").write_bytes(b"not a real png at all")

    base = 1_700_000_000
    os.utime(uploads / f"{good_ids[0]}.png", (base, base))
    os.utime(uploads / f"{corrupt_id}.png", (base + 1, base + 1))
    os.utime(uploads / f"{good_ids[1]}.png", (base + 2, base + 2))
    # Newest-first candidate order: good_ids[1], corrupt_id, good_ids[0].

    page1 = await client.get("/api/images", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200
    body1 = page1.json()
    ids1 = [item["image_id"] for item in body1["items"]]
    assert corrupt_id not in ids1
    assert ids1 == [good_ids[1]]  # the corrupt candidate's slot was dropped, not backfilled
    assert body1["total"] == 3  # candidate-pass total counts it; PIL pass doesn't back-patch it

    page2 = await client.get("/api/images", params={"page": 2, "page_size": 2})
    assert page2.status_code == 200
    ids2 = [item["image_id"] for item in page2.json()["items"]]
    assert ids2 == [good_ids[0]]  # unaffected by page 1's corrupt candidate


async def test_list_images_invalid_page_returns_422(client):
    resp = await client.get("/api/images", params={"page": 0})
    assert resp.status_code == 422


async def test_list_images_invalid_page_size_returns_422(client):
    resp = await client.get("/api/images", params={"page_size": 101})
    assert resp.status_code == 422

    resp = await client.get("/api/images", params={"page_size": 0})
    assert resp.status_code == 422


async def test_list_images_skips_hostile_filename_silently(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "not-a-valid-id.png").write_bytes(_png_bytes())  # fails IMAGE_ID_RE

    resp = await client.get("/api/images")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_list_images_ignores_non_png_files(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / f"{uuid.uuid4().hex}.txt").write_text("not a png")

    resp = await client.get("/api/images")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_images_skips_symlinked_but_well_formed_id_not_500(app_and_client):
    # Same containment-escape shape as the GET/DELETE 3b tests above, but
    # for the LIST endpoint: a regex-valid filename whose resolved path
    # escapes uploads_dir/ (a symlink) must be silently dropped, never a 500
    # and never included in the listing.
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    outside = data_dir.parent / "outside-uploads-list"
    outside.mkdir(parents=True, exist_ok=True)
    secret = outside / "secret.png"
    secret.write_bytes(_png_bytes())

    image_id = uuid.uuid4().hex
    (uploads / f"{image_id}.png").symlink_to(secret)

    resp = await client.get("/api/images")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


# --- 9. GET /api/images/{id}/thumb (task H6) ---------------------------------


async def test_get_image_thumb_returns_smaller_png_with_correct_headers(client):
    upload = await client.post(
        "/api/images",
        files={"file": ("photo.png", io.BytesIO(_large_png_bytes(800, 400)), "image/png")},
    )
    image_id = upload.json()["image_id"]

    resp = await client.get(f"/api/images/{image_id}/thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=86400"
    assert "etag" in resp.headers
    assert "last-modified" in resp.headers

    decoded = Image.open(io.BytesIO(resp.content))
    assert decoded.format == "PNG"
    # 800x400 (2:1) downscaled to fit within THUMBNAIL_MAX_EDGE on its
    # longest edge, aspect ratio preserved.
    assert decoded.size == (THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE // 2)
    assert max(decoded.size) <= THUMBNAIL_MAX_EDGE
    assert len(resp.content) < len(_large_png_bytes(800, 400))


async def test_get_image_thumb_does_not_upscale_a_small_source(client):
    # _png_bytes()'s default 20x10 is already well under THUMBNAIL_MAX_EDGE
    # -- PIL's Image.thumbnail() only ever shrinks, so the thumb route must
    # return the SAME dimensions, not an upscaled 256-edge image.
    upload = await client.post(
        "/api/images", files={"file": ("small.png", io.BytesIO(_png_bytes(20, 10)), "image/png")}
    )
    image_id = upload.json()["image_id"]

    resp = await client.get(f"/api/images/{image_id}/thumb")
    assert resp.status_code == 200
    decoded = Image.open(io.BytesIO(resp.content))
    assert decoded.size == (20, 10)


async def test_get_image_thumb_is_cached_to_disk_beside_original(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir

    upload = await client.post(
        "/api/images",
        files={"file": ("photo.png", io.BytesIO(_large_png_bytes(800, 400)), "image/png")},
    )
    image_id = upload.json()["image_id"]

    thumb_file = data_dir / "uploads" / "thumbs" / f"{image_id}.png"
    assert not thumb_file.is_file()  # not generated until first request

    resp = await client.get(f"/api/images/{image_id}/thumb")
    assert resp.status_code == 200
    assert thumb_file.is_file()

    # Second request serves the cached file straight from disk -- same
    # bytes, no re-render.
    resp2 = await client.get(f"/api/images/{image_id}/thumb")
    assert resp2.content == resp.content


async def test_get_image_thumb_unknown_id_returns_404(client):
    resp = await client.get("/api/images/deadbeefdeadbeefdeadbeefdeadbeef/thumb")
    assert resp.status_code == 404


async def test_get_image_thumb_malformed_id_returns_404(client):
    resp = await client.get("/api/images/not-a-valid-id/thumb")
    assert resp.status_code == 404


async def test_get_image_thumb_symlinked_but_well_formed_id_returns_404_not_500(app_and_client):
    # Same containment-escape shape as the full-image 3b tests above: a
    # regex-valid id whose resolved ORIGINAL path escapes uploads_dir/ must
    # 404 before the thumb route ever calls thumb_path() or touches PIL.
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    outside = data_dir.parent / "outside-uploads-thumb"
    outside.mkdir(parents=True, exist_ok=True)
    secret = outside / "secret.png"
    secret.write_bytes(_png_bytes())

    image_id = uuid.uuid4().hex
    (uploads / f"{image_id}.png").symlink_to(secret)

    resp = await client.get(f"/api/images/{image_id}/thumb")
    assert resp.status_code == 404


async def test_delete_image_removes_cached_thumb(app_and_client):
    app, client = app_and_client
    data_dir = app.state.config.data_dir

    upload = await client.post(
        "/api/images",
        files={"file": ("photo.png", io.BytesIO(_large_png_bytes()), "image/png")},
    )
    image_id = upload.json()["image_id"]
    thumb_file = data_dir / "uploads" / "thumbs" / f"{image_id}.png"

    thumb_resp = await client.get(f"/api/images/{image_id}/thumb")
    assert thumb_resp.status_code == 200
    assert thumb_file.is_file()

    delete_resp = await client.delete(f"/api/images/{image_id}")
    assert delete_resp.status_code == 204
    assert not thumb_file.is_file()

    # And the route 404s afterward rather than re-generating from a
    # (deleted) original.
    resp = await client.get(f"/api/images/{image_id}/thumb")
    assert resp.status_code == 404


async def test_delete_image_without_a_thumb_ever_requested_still_succeeds(client):
    # DELETE must not fail just because no one ever hit the /thumb route
    # for this image -- thumb_path().unlink(missing_ok=True) is the whole
    # point.
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]

    resp = await client.delete(f"/api/images/{image_id}")
    assert resp.status_code == 204


async def test_thumb_regenerated_after_delete_and_reupload(app_and_client):
    # Delete + reupload the SAME bytes always mints a fresh uuid4().hex id
    # (see upload_image), so this isn't really "the same thumb file
    # changing contents" -- it's confirming that cycle behaves cleanly
    # end-to-end: the old id's thumb is gone, the new id has none cached
    # yet, and requesting it generates a correct thumb for the NEW id
    # without any cross-contamination from the old one.
    app, client = app_and_client
    data_dir = app.state.config.data_dir
    payload = _large_png_bytes(800, 400)

    first = await client.post(
        "/api/images", files={"file": ("photo.png", io.BytesIO(payload), "image/png")}
    )
    first_id = first.json()["image_id"]
    first_thumb_resp = await client.get(f"/api/images/{first_id}/thumb")
    assert first_thumb_resp.status_code == 200
    first_thumb_file = data_dir / "uploads" / "thumbs" / f"{first_id}.png"
    assert first_thumb_file.is_file()

    delete_resp = await client.delete(f"/api/images/{first_id}")
    assert delete_resp.status_code == 204
    assert not first_thumb_file.is_file()

    second = await client.post(
        "/api/images", files={"file": ("photo.png", io.BytesIO(payload), "image/png")}
    )
    second_id = second.json()["image_id"]
    assert second_id != first_id
    second_thumb_file = data_dir / "uploads" / "thumbs" / f"{second_id}.png"
    assert not second_thumb_file.is_file()  # not generated until requested

    second_thumb_resp = await client.get(f"/api/images/{second_id}/thumb")
    assert second_thumb_resp.status_code == 200
    assert second_thumb_file.is_file()
    decoded = Image.open(io.BytesIO(second_thumb_resp.content))
    assert decoded.size == (THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE // 2)


# --- 10. FileResponse headers on GET /api/images/{id} (task H6) -------------


async def test_get_image_full_route_carries_cache_and_conditional_headers(client):
    upload = await client.post(
        "/api/images", files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")}
    )
    image_id = upload.json()["image_id"]

    resp = await client.get(f"/api/images/{image_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=86400"
    assert "etag" in resp.headers
    assert "last-modified" in resp.headers
