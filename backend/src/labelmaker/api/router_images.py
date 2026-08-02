"""POST /api/images (upload), GET /api/images (list, task D2a), GET
/api/images/{id} (serve), DELETE /api/images/{id} (task 2.7).

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

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from labelmaker.api.deps import AppConfigDep, error_message
from labelmaker.render.images import IMAGE_ID_RE, image_path, uploads_dir

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
MAX_DECODED_PIXELS = 8_000_000  # 8MP
_READ_CHUNK_BYTES = 1024 * 1024
_ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})


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


@router.post("", status_code=201)
async def upload_image(
    request: Request, config: AppConfigDep, file: UploadFile
) -> ImageUploadResponse:
    data = await _read_capped(request, file)
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")

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
    target_dir = uploads_dir(config.data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    img.save(image_path(image_id, config.data_dir), format="PNG")

    return ImageUploadResponse(image_id=image_id, width=img.width, height=img.height)


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
    had a DB row (see this module's own docstring) -- and pairs each
    surviving `*.png` entry with its width/height (a cheap, header-only
    `Image.open()` -- no `.load()`/`.convert()`, so this never decodes a
    full pixel buffer just to answer a LIST request) and its `stat()`
    size/mtime.

    `page`/`page_size` validation mirrors router_history.py's `list_jobs`
    bounds exactly (page>=1, 1<=page_size<=100) -- raises `ValueError`,
    422-mappable by the route handler below, same convention.

    Directory-listing hardening: `target_dir.iterdir()` is only ever used
    to enumerate CANDIDATE filenames -- never trusted as a source of real
    paths. Every candidate's stem is re-validated against `IMAGE_ID_RE` and
    then re-resolved through `image_path()` (the same containment-checked
    choke point GET/DELETE /api/images/{id} already use), so a filename
    that doesn't fit the shape `POST /api/images` ever mints, OR a
    regex-valid name whose resolved path escapes `uploads_dir` (e.g. a
    symlink planted inside it), is silently dropped -- logged at DEBUG,
    never surfaced as a 500 and never included in the listing. A file that
    passes both checks but still fails to open as an image (corrupt/
    truncated) is dropped the same way.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")
    if not (1 <= page_size <= 100):
        raise ValueError(f"page_size must be between 1 and 100, got {page_size}")

    target_dir = uploads_dir(data_dir)
    records: list[tuple[float, dict]] = []
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
                with Image.open(path) as probe:  # header-only -- no .load()
                    width, height = probe.size
            except Exception as exc:  # noqa: BLE001 -- any per-file failure just drops that one entry
                _LOG.debug("GET /api/images: skipping unreadable upload %r: %s", entry.name, exc)
                continue
            records.append(
                (
                    file_stat.st_mtime,
                    {
                        "image_id": image_id,
                        "width": width,
                        "height": height,
                        "size_bytes": file_stat.st_size,
                        "mtime": _iso_mtime(file_stat.st_mtime),
                    },
                )
            )

    records.sort(key=lambda record: record[0], reverse=True)
    total = len(records)
    offset = (page - 1) * page_size
    page_items = [item for _, item in records[offset : offset + page_size]]
    return {"items": page_items, "page": page, "page_size": page_size, "total": total}


@router.get("")
async def list_images(config: AppConfigDep, page: int = 1, page_size: int = 20) -> dict:
    try:
        return _list_uploaded_images(config.data_dir, page, page_size)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc


@router.get("/{image_id}")
async def get_image(image_id: str, config: AppConfigDep) -> Response:
    path = _resolve_existing_image_path(image_id, config.data_dir)
    return Response(content=path.read_bytes(), media_type="image/png")


@router.delete("/{image_id}", status_code=204)
async def delete_image(image_id: str, config: AppConfigDep) -> Response:
    path = _resolve_existing_image_path(image_id, config.data_dir)
    path.unlink()
    return Response(status_code=204)
