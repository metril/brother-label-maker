"""POST /api/images (upload), GET /api/images (list, task D2a), GET
/api/images/{id} (serve), GET /api/images/{id}/thumb (bounded thumbnail,
task H6), DELETE /api/images/{id} (task 2.7).

Uploaded images (logos, photos for a text label's `icon.kind="image"`
threshold/dither art -- see render/types/text_label.py and render/images.py)
are normalized to PNG (RGBA/palette-with-transparency flattened onto white,
everything else converted to plain RGB) and stored at
`data_dir/uploads/{image_id}.png`.

Two independent caps guard against a malicious/oversized upload doing
expensive work before it's even validated -- the 2.4 review's lesson
(`POST /api/serialize/csv`'s row cap was originally enforced only AFTER the
whole file had already been parsed into memory; see that router's own
history) applies here just as much, to two DIFFERENT expensive operations:

1. Byte cap (`MAX_UPLOAD_BYTES`, 10MB): checked via the `Content-Length`
   header first (a dishonest/absent header just means this first check is a
   no-op, not a correctness issue -- it's a fast path for the common
   honest-client case, not the real guarantee), THEN via a chunked read loop
   (`_read_capped`) that bails as soon as the accumulated body exceeds the
   cap -- never an unconditional `await file.read()` (the CSV endpoint's
   original mistake). This bounds how large a Python `bytes` object this
   endpoint ever builds, regardless of what Starlette's own multipart
   parser may have already spooled to disk beneath it (an underlying
   FastAPI/Starlette implementation detail this endpoint's own code doesn't
   control, same as it was for the CSV endpoint).
2. Decoded-pixel cap (`MAX_DECODED_PIXELS`, 8MP): checked via
   `Image.open(...).size` -- which for a well-formed PNG/JPEG/WEBP only
   parses the header, NOT the compressed pixel data -- BEFORE `.load()` (or
   any implicit-load operation like `.convert()`) is ever called. Either of
   those decodes every pixel: a 10000x10000 "decompression bomb" image can
   be a few KB on disk yet decode to 400MB of raw pixels. (Pillow has its
   own, much higher, built-in `Image.MAX_IMAGE_PIXELS` bomb guard --
   ~89.5MP -- which can itself raise `DecompressionBombError` from inside
   `Image.open()` for a sufficiently extreme header, before our own 8MP
   check even runs; both are caught the same way here.)

422 (not 413) for every rejection in this router -- consistent with every
other upload-validation endpoint in this API (router_labels.py's CSV upload
uses 422 throughout for size/shape rejections; nothing else in this
codebase uses 413).
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel

from labelmaker.api.deps import AppConfigDep, error_message
from labelmaker.render.images import IMAGE_ID_RE, image_path, thumb_path, uploads_dir

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
MAX_DECODED_PIXELS = 8_000_000  # 8MP
_READ_CHUNK_BYTES = 1024 * 1024
_ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

# H6 (2026-08 review): the grid tiles in UploadsGallery.tsx are ~100-150px
# `aspect-square` cells, but were pulling the full-resolution stored
# original -- up to 16MB for a photo-like upload re-encoded as PNG -- to
# paint each one. 256px longest edge is comfortably >2x any tile's CSS
# size (retina-safe) while keeping the cached thumbnail itself trivially
# small (tens of KB, not MB).
THUMBNAIL_MAX_EDGE = 256

# Uploads are immutable per image_id (delete+reupload always mints a fresh
# uuid4().hex -- see upload_image below -- so no id is ever rewritten in
# place); a long max-age is therefore safe even without any invalidation
# story. The ETag/Last-Modified FileResponse adds automatically (from the
# file's own stat()) still lets a conditional GET short-circuit to a 304
# before this max-age is even consulted.
_CACHE_CONTROL = "public, max-age=86400"


class ImageUploadResponse(BaseModel):
    image_id: str
    width: int
    height: int


async def _read_capped(request: Request, file: UploadFile) -> bytes:
    """Read `file` into memory, bailing with a 422 as soon as either the
    declared `Content-Length` or the actually-read byte count exceeds
    `MAX_UPLOAD_BYTES` -- see module docstring, cap (1)."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = None
        if declared is not None and declared > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"upload declares {declared} bytes, exceeding the "
                    f"{MAX_UPLOAD_BYTES}-byte cap"
                ),
            )

    chunks = bytearray()
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"upload exceeds the {MAX_UPLOAD_BYTES}-byte cap",
            )
    return bytes(chunks)


def _validate_image_id(image_id: str) -> None:
    """A path-parameter value we did NOT generate (a client can send
    anything as {image_id}) is treated as "not found" here (404), not the
    422 render/images.py's image_path() raises for the same shape mismatch
    -- GET/DELETE lookups follow REST "the resource doesn't exist"
    semantics, not "your request was malformed" ones. `IMAGE_ID_RE` itself
    is imported from render.images (not redefined here) so this check and
    image_path()'s own -- the actual filesystem-access guard, see that
    module's docstring -- can never drift apart."""
    if not IMAGE_ID_RE.match(image_id):
        raise HTTPException(status_code=404, detail="image not found")


def _resolve_existing_image_path(image_id: str, data_dir: Path) -> Path:
    """Shared by GET/DELETE: resolve `image_id` to an existing file's path,
    or 404 -- never a raw 500.

    Coordinator review fix-up: `_validate_image_id`'s regex pre-check
    catches most shape mismatches before `image_path()` is ever called,
    but `image_path()`'s OWN second check -- the resolve()-containment
    assertion (see that function's docstring) -- can still raise
    `ValueError` for a REGEX-VALID id whose resolved path nonetheless
    escapes `uploads_dir` (e.g. a symlink inside `data_dir/uploads/`
    pointing outside it, confirmed live). Both handlers used to call
    `image_path()` unguarded, so that `ValueError` escaped straight to
    Starlette as a 500 -- contradicting this module's own "malformed/
    unreachable id -> 404" contract. Catching it here (not just trusting
    the regex pre-check) is what actually closes that gap.
    """
    _validate_image_id(image_id)
    try:
        path = image_path(image_id, data_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="image not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return path


def _process_upload(data: bytes, data_dir: Path) -> tuple[str, int, int]:
    """The blocking half of `POST /api/images` (M7, 2026-08 review): every
    step below decodes/re-encodes real pixel data (two `Image.open()`
    probes, a `.load()`, an alpha-composite `.convert()`, and a PNG
    `.save()`) and used to run inline on the event loop -- the same class
    of bug the module docstring's cap discussion is about, just for CPU
    time instead of memory. The caller runs this via
    `anyio.to_thread.run_sync` so it never blocks the loop that also
    carries `/api/ws` and the print worker (see `list_images` below for
    the read-side counterpart).

    Raises the exact same `HTTPException`s this used to raise inline --
    raising them from a worker thread is fine, `anyio.to_thread.run_sync`
    propagates them back into the awaiting coroutine unchanged, and
    FastAPI's normal exception handling takes it from there -- so response
    codes/bodies are byte-for-byte identical to before this was moved off
    the loop.
    """
    try:
        probe = Image.open(io.BytesIO(data))
        probe_format = probe.format
        width, height = probe.size
    except Image.DecompressionBombError as exc:
        raise HTTPException(status_code=422, detail=f"image is too large to decode: {exc}") from exc
    except Exception as exc:
        # PIL raises different exceptions per codec for "this isn't a
        # decodable image" (UnidentifiedImageError being the common one,
        # but a truncated/corrupt file of a recognized format can raise
        # other PIL/codec errors too) -- all of them mean the same thing to
        # this endpoint's caller: reject with a 422, not a 500.
        raise HTTPException(status_code=422, detail=f"not a decodable image: {exc}") from exc

    if probe_format not in _ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported image format {probe_format!r}; allowed: png, jpeg, webp",
        )

    if width * height > MAX_DECODED_PIXELS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"image is {width}x{height} ({width * height} px), exceeding the "
                f"{MAX_DECODED_PIXELS}px cap"
            ),
        )

    # Only now -- both caps cleared -- does this actually decode every pixel.
    # A file whose HEADER parsed fine (enough for the probe above) can still
    # fail here -- e.g. truncated mid-scan JPEG data -- caught the same way
    # as a header-level decode failure, not left to surface as a raw 500.
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"not a decodable image: {exc}") from exc
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img).convert("RGB")
    else:
        img = img.convert("RGB")

    image_id = uuid.uuid4().hex
    target_dir = uploads_dir(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    img.save(image_path(image_id, data_dir), format="PNG")

    return image_id, img.width, img.height


@router.post("", status_code=201)
async def upload_image(
    request: Request, config: AppConfigDep, file: UploadFile
) -> ImageUploadResponse:
    data = await _read_capped(request, file)
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")

    image_id, width, height = await anyio.to_thread.run_sync(
        _process_upload, data, config.data_dir
    )
    return ImageUploadResponse(image_id=image_id, width=width, height=height)


def _iso_mtime(epoch_seconds: float) -> str:
    """Same textual shape as db/database.py's `_utcnow()` -- ISO-8601 UTC
    with a literal 'Z' suffix and fixed-width (six-digit) microseconds --
    so GET /api/images' `mtime` field reads the same way every OTHER
    timestamp in this API (`created_at`, etc.) already does, even though
    this one comes from a filesystem `st_mtime` rather than a DB row."""
    return datetime.fromtimestamp(epoch_seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _list_uploaded_images(data_dir: Path, page: int, page_size: int) -> dict:
    """Backing implementation for `GET /api/images` (task D2a): scans
    `uploads_dir` directly rather than any DB table -- uploads have never
    had a DB row (see this module's own docstring).

    `page`/`page_size` validation mirrors router_history.py's `list_jobs`
    bounds exactly (page>=1, 1<=page_size<=100) -- raises `ValueError`,
    422-mappable by the route handler below, same convention.

    M7 (2026-08 review): this used to pair EVERY surviving entry with a
    full `Image.open()` header probe before sorting/slicing, making the
    whole scan O(total uploads) instead of O(page_size) -- page 5 cost
    exactly what page 1 cost. Now split into two passes:

    1. Candidate pass, over every entry: name-validated (`IMAGE_ID_RE`) and
       containment-checked (`image_path()`, same choke point GET/DELETE
       /api/images/{id} already use) exactly as before, plus a `stat()` --
       cheap syscalls only, no PIL. Sorted and sliced to the requested page
       on `st_mtime` alone.
    2. PIL pass, over only the (at most `page_size`) survivors of the
       slice: the header-only `Image.open()` probe (no `.load()`/
       `.convert()`, so this never decodes a full pixel buffer just to
       answer a LIST request) that actually needs each candidate's
       width/height.

    Directory-listing hardening (candidate pass): `target_dir.iterdir()`
    is only ever used to enumerate CANDIDATE filenames -- never trusted as
    a source of real paths. A filename that doesn't fit the shape
    `POST /api/images` ever mints, OR a regex-valid name whose resolved
    path escapes `uploads_dir` (e.g. a symlink planted inside it), is
    silently dropped -- logged at DEBUG, never surfaced as a 500 and never
    included in the listing.

    Page-shortfall note (PIL pass): a candidate that passes the name/
    containment/stat checks but still fails to open as an image (corrupt/
    truncated) is ALSO dropped the same way, but only after it has already
    been counted in `total` and consumed a slot in this page's slice --
    deliberately NOT backfilled from the next candidate, which would put
    the PIL probe back on the O(total) path this fix exists to avoid. The
    user-visible cost is a page that is up to N items short, where N is
    the number of corrupt files that landed in that page's slice --
    accepted per the review's suggested fix (stat-first slicing, PIL probe
    only on survivors) as strictly better than paying O(total) PIL work on
    every single request just to keep every page exactly `page_size` long.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")
    if not (1 <= page_size <= 100):
        raise ValueError(f"page_size must be between 1 and 100, got {page_size}")

    target_dir = uploads_dir(data_dir)
    # (mtime, image_id, path, size_bytes) -- everything the PIL pass and
    # the final item shape need, without re-`stat()`ing.
    candidates: list[tuple[float, str, Path, int]] = []
    if target_dir.is_dir():
        for entry in target_dir.iterdir():
            if entry.suffix != ".png":
                continue
            image_id = entry.stem
            if not IMAGE_ID_RE.match(image_id):
                _LOG.debug(
                    "GET /api/images: skipping non-conforming upload filename %r", entry.name
                )
                continue
            try:
                # Re-resolves + re-asserts containment -- see docstring;
                # never trust the iterdir() entry's own path directly.
                path = image_path(image_id, data_dir)
            except ValueError:
                _LOG.debug(
                    "GET /api/images: skipping upload %r that fails path containment", entry.name
                )
                continue
            try:
                file_stat = path.stat()
            except OSError as exc:
                _LOG.debug(
                    "GET /api/images: skipping upload %r that vanished mid-scan: %s",
                    entry.name,
                    exc,
                )
                continue
            candidates.append((file_stat.st_mtime, image_id, path, file_stat.st_size))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    total = len(candidates)
    offset = (page - 1) * page_size
    page_candidates = candidates[offset : offset + page_size]

    page_items = []
    for mtime, image_id, path, size_bytes in page_candidates:
        try:
            with Image.open(path) as probe:  # header-only -- no .load()
                width, height = probe.size
        except Exception as exc:  # noqa: BLE001 -- any per-file failure just drops that one entry
            _LOG.debug("GET /api/images: skipping unreadable upload %r: %s", path.name, exc)
            continue
        page_items.append(
            {
                "image_id": image_id,
                "width": width,
                "height": height,
                "size_bytes": size_bytes,
                "mtime": _iso_mtime(mtime),
            }
        )

    return {"items": page_items, "page": page, "page_size": page_size, "total": total}


@router.get("")
async def list_images(config: AppConfigDep, page: int = 1, page_size: int = 20) -> dict:
    try:
        # M7 (2026-08 review): the only filesystem/PIL route in this API
        # that didn't hop off the event loop -- see _list_uploaded_images'
        # own docstring for the O(page_size) rework alongside this.
        return await anyio.to_thread.run_sync(
            _list_uploaded_images, config.data_dir, page, page_size
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc


def _generate_thumbnail(source_path: Path, dest_path: Path) -> None:
    """Render `source_path` (an already-normalized plain-RGB upload, see
    `upload_image`'s docstring) down to at most `THUMBNAIL_MAX_EDGE` px on
    its longest edge -- aspect ratio preserved, LANCZOS resampling (same
    resample filter render/images.py's own `image_object()` resize uses),
    written to `dest_path` as PNG. `Image.thumbnail()` only ever shrinks
    (never upscales) in place, so a source already at/under the cap is
    copied through unchanged rather than distorted -- that's what makes
    caching the *dest_path* bytes byte-for-byte safe to serve regardless
    of the source's own dimensions.

    Caller's responsibility: `dest_path`'s parent directory need not exist
    yet -- created here -- but `source_path` must already exist (this
    function does not itself resolve/validate an `image_id`; both routes
    below call `image_path()`/`thumb_path()` for that first).
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as img:
        img.load()
        thumb = img.copy()
        thumb.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
        thumb.save(dest_path, format="PNG")


@router.get("/{image_id}")
async def get_image(image_id: str, config: AppConfigDep) -> FileResponse:
    path = _resolve_existing_image_path(image_id, config.data_dir)
    # FileResponse (not Response(path.read_bytes())): streams the file off
    # the event loop via the threadpool instead of buffering the whole
    # multi-MB original into memory per request, and computes etag/
    # last-modified from the file's own stat() for free -- see H6.
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": _CACHE_CONTROL})


@router.get("/{image_id}/thumb")
async def get_image_thumb(image_id: str, config: AppConfigDep) -> FileResponse:
    """H6 fix: a bounded (`THUMBNAIL_MAX_EDGE`-px-longest-edge) counterpart
    to `GET /api/images/{id}` for grid-tile-sized UI (UploadsGallery.tsx).
    Generated once with PIL on first request and cached to disk at
    `thumb_path()` (`data_dir/uploads/thumbs/{id}.png`) beside the
    original; every request after that is a disk read, not a re-render.
    Same 404-not-500 containment discipline as the full-image route --
    `_resolve_existing_image_path` gates on the ORIGINAL existing first,
    so a hostile/unknown/path-escaping `image_id` never reaches
    `thumb_path()` at all.
    """
    path = _resolve_existing_image_path(image_id, config.data_dir)
    thumb = thumb_path(image_id, config.data_dir)
    if not thumb.is_file():
        # First request for this id pays the PIL resize -- off-loop, same
        # M7 discipline as upload/list (an 8 MP source takes long enough
        # to stall /api/ws and the status poll otherwise).
        await anyio.to_thread.run_sync(_generate_thumbnail, path, thumb)
    return FileResponse(thumb, media_type="image/png", headers={"Cache-Control": _CACHE_CONTROL})


@router.delete("/{image_id}", status_code=204)
async def delete_image(image_id: str, config: AppConfigDep) -> Response:
    path = _resolve_existing_image_path(image_id, config.data_dir)
    path.unlink()
    # Best-effort: the thumb may not exist yet (never requested) -- that's
    # not an error, just nothing to clean up. thumb_path() itself can't
    # raise here (image_id already passed IMAGE_ID_RE + containment via
    # _resolve_existing_image_path above).
    thumb_path(image_id, config.data_dir).unlink(missing_ok=True)
    return Response(status_code=204)
