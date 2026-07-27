"""POST /api/images (upload), GET /api/images/{id} (serve), DELETE
/api/images/{id} (task 2.7).

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
import re
import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from labelmaker.api.deps import AppConfigDep
from labelmaker.render.images import image_path, uploads_dir

router = APIRouter(prefix="/images", tags=["images"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
MAX_DECODED_PIXELS = 8_000_000  # 8MP
_READ_CHUNK_BYTES = 1024 * 1024
_ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

# image_id is always a fresh uuid4().hex (see upload_image) -- validated on
# every GET/DELETE lookup too, so a path-parameter value we did NOT
# generate (a client can send anything as {image_id}) never gets treated as
# anything other than "not found". FastAPI's default str path-param
# matcher already can't contain '/' (so classic ../ traversal can't even
# reach this handler as a single segment), but this is a second, explicit
# belt-and-suspenders check independent of that routing behavior.
_IMAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


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
    if not _IMAGE_ID_RE.match(image_id):
        raise HTTPException(status_code=404, detail="image not found")


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


@router.get("/{image_id}")
async def get_image(image_id: str, config: AppConfigDep) -> Response:
    _validate_image_id(image_id)
    path = image_path(image_id, config.data_dir)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return Response(content=path.read_bytes(), media_type="image/png")


@router.delete("/{image_id}", status_code=204)
async def delete_image(image_id: str, config: AppConfigDep) -> Response:
    _validate_image_id(image_id)
    path = image_path(image_id, config.data_dir)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    path.unlink()
    return Response(status_code=204)
