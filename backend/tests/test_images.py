"""Tests for labelmaker.render.images: threshold/dither placement of an
already-uploaded image (task 2.7). Uploads themselves (POST/GET/DELETE
/api/images) are covered by test_api_images.py -- this file drives
image_object() directly against a hand-placed file under a tmp data_dir's
uploads/ directory, the same shape router_images.py would have produced.

Section 7 covers a coordinator-review-caught CRITICAL bug: `image_id` is
untrusted input on the RENDER path (POST /api/render/preview and POST
/api/print both accept a bare `icon.image_id` string in the request body,
not necessarily one this project's own upload endpoint ever minted) --
before the fix, `image_path()` built a filesystem path from it with no
validation, and pathlib's `/` operator silently DISCARDS the left operand
when the right one is an absolute path string, while a `..`-containing id
resolves as an ordinary relative-path escape. Both were confirmed live
(an absolute path and a `../`-escaping one both got rendered straight into
a response) before this was hardened. See render/images.py's module
docstring for the fix itself (IMAGE_ID_RE + a resolve()-containment
assertion, both in image_path(), the one choke point every image_id ->
path resolution in this codebase goes through).
"""

from __future__ import annotations

import base64
import io
import re
import uuid

import pytest
from PIL import Image

from labelmaker.render.document import RenderedLabel, _svg_document
from labelmaker.render.images import IMAGE_ID_RE, image_object, image_path, uploads_dir
from labelmaker.render.rasterize import rasterize

_HREF_RE = re.compile(r'href="data:image/png;base64,([^"]+)"')


def _put_upload(data_dir, img: Image.Image) -> str:
    """Writes `img` under a FRESH, validly-shaped image_id (the same shape
    POST /api/images mints -- uuid4().hex) and returns that id. Tests that
    need a specific/malformed id use image_path()/direct file writes
    instead -- see section 7."""
    image_id = uuid.uuid4().hex
    uploads_dir(data_dir).mkdir(parents=True, exist_ok=True)
    img.save(image_path(image_id, data_dir), format="PNG")
    return image_id


def _decode_embedded_png(svg_fragment: str) -> Image.Image:
    match = _HREF_RE.search(svg_fragment)
    assert match is not None, f"no embedded <image href=...> in {svg_fragment!r}"
    raw = base64.b64decode(match.group(1))
    return Image.open(io.BytesIO(raw))


def _gradient(width: int, height: int) -> Image.Image:
    img = Image.new("L", (width, height))
    for x in range(width):
        value = round(255 * x / max(1, width - 1))
        for y in range(height):
            img.putpixel((x, y), value)
    return img.convert("RGB")


# --- 1. Unknown (but validly-shaped) image_id -------------------------------


def test_image_object_unknown_id_raises(tmp_path):
    unknown_id = uuid.uuid4().hex  # well-formed, but never uploaded
    with pytest.raises(ValueError, match="unknown image_id"):
        image_object(unknown_id, target_h_px=20, data_dir=tmp_path)


# --- 2. Parameter validation --------------------------------------------------


def test_image_object_rejects_bad_mode(tmp_path):
    image_id = _put_upload(tmp_path, Image.new("RGB", (10, 10), "white"))
    with pytest.raises(ValueError, match="mode"):
        image_object(image_id, target_h_px=10, mode="blur", data_dir=tmp_path)  # type: ignore[arg-type]


def test_image_object_rejects_non_positive_target_h(tmp_path):
    image_id = _put_upload(tmp_path, Image.new("RGB", (10, 10), "white"))
    with pytest.raises(ValueError, match="target_h_px"):
        image_object(image_id, target_h_px=0, data_dir=tmp_path)


def test_image_object_rejects_non_positive_target_w(tmp_path):
    image_id = _put_upload(tmp_path, Image.new("RGB", (10, 10), "white"))
    with pytest.raises(ValueError, match="target_w_px"):
        image_object(image_id, target_h_px=10, target_w_px=0, data_dir=tmp_path)


def test_image_object_rejects_out_of_range_threshold(tmp_path):
    image_id = _put_upload(tmp_path, Image.new("RGB", (10, 10), "white"))
    with pytest.raises(ValueError, match="threshold"):
        image_object(image_id, target_h_px=10, threshold=256, data_dir=tmp_path)


# --- 3. Sizing: aspect-preserving vs forced square --------------------------


def test_image_object_preserves_aspect_ratio_when_width_omitted(tmp_path):
    image_id = _put_upload(tmp_path, Image.new("RGB", (200, 100), "black"))  # 2:1
    _svg, w, h, _region = image_object(image_id, target_h_px=50, data_dir=tmp_path)
    assert h == 50
    assert w == 100  # 200/100 * 50


def test_image_object_forces_exact_size_when_width_given(tmp_path):
    image_id = _put_upload(tmp_path, Image.new("RGB", (200, 100), "black"))  # 2:1
    _svg, w, h, _region = image_object(
        image_id, target_h_px=40, target_w_px=40, data_dir=tmp_path
    )
    assert (w, h) == (40, 40)


# --- 4. mode="threshold": embedded image is already binary -----------------


def test_threshold_mode_embedded_image_is_pure_black_and_white(tmp_path):
    image_id = _put_upload(tmp_path, _gradient(64, 8))
    svg, w, h, region = image_object(
        image_id,
        target_h_px=8,
        target_w_px=64,
        mode="threshold",
        threshold=128,
        data_dir=tmp_path,
    )
    assert region is None
    decoded = _decode_embedded_png(svg).convert("L")
    assert decoded.size == (w, h)
    values = {decoded.getpixel((x, y)) for x in range(w) for y in range(h)}
    assert values <= {0, 255}
    assert values == {0, 255}  # a gradient at threshold=128 produces both


def test_threshold_mode_respects_custom_threshold(tmp_path):
    # A flat mid-gray image: threshold just above/below its value flips the
    # entire result from all-black to all-white.
    image_id = _put_upload(tmp_path, Image.new("RGB", (10, 10), (100, 100, 100)))
    svg_low, *_rest_low = image_object(
        image_id, target_h_px=10, mode="threshold", threshold=90, data_dir=tmp_path
    )
    svg_high, *_rest_high = image_object(
        image_id, target_h_px=10, mode="threshold", threshold=110, data_dir=tmp_path
    )
    low = _decode_embedded_png(svg_low).convert("L")
    high = _decode_embedded_png(svg_high).convert("L")
    assert low.getpixel((0, 0)) == 255  # 100 >= 90 -> white
    assert high.getpixel((0, 0)) == 0  # 100 < 110 -> black


# --- 5. mode="dither": returns an ObjectRegion, embeds grayscale unmodified -


def test_dither_mode_returns_object_region_covering_whole_image(tmp_path):
    image_id = _put_upload(tmp_path, _gradient(64, 8))
    svg, w, h, region = image_object(
        image_id, target_h_px=8, target_w_px=64, mode="dither", data_dir=tmp_path
    )
    assert region is not None
    assert region.mode == "dither"
    assert (region.x, region.y) == (0, 0)
    assert (region.width, region.height) == (w, h) == (64, 8)
    decoded = _decode_embedded_png(svg)
    assert decoded.convert("L").getextrema() != (0, 0)  # not flattened to black
    assert decoded.mode in ("L", "RGB")  # grayscale payload, not pre-binarized


def test_dither_mode_end_to_end_through_rasterize_has_scattered_pixels(tmp_path):
    # The real path (not the synthetic-SVG test task 1.2 used): an actual
    # uploaded gradient image, run through image_object() -> a full SVG
    # document -> rasterize()'s per-region Floyd-Steinberg pass.
    width, height = 100, 64
    image_id = _put_upload(tmp_path, _gradient(width, height))
    svg_fragment, w, h, region = image_object(
        image_id, target_h_px=height, target_w_px=width, mode="dither", data_dir=tmp_path
    )
    assert (w, h) == (width, height)
    label = RenderedLabel(
        svg=_svg_document(width, height, svg_fragment),
        width_px=width,
        height_px=height,
        object_map=[region],
    )
    img = rasterize(label)
    assert img.size == (width, height)

    black = sum(1 for x in range(width) for y in range(height) if img.getpixel((x, y)) == 0)
    total = width * height
    fraction_black = black / total
    # A real mix of black/white -- not solid, not a hard vertical threshold
    # edge (which would also produce SOME black -- the scattered-noise
    # signature is what test_rasterize.py's synthetic version checks via
    # per-row uniformity; here we additionally confirm at least one row is
    # NOT uniform, proving the dither actually ran on real image data).
    assert 0.05 < fraction_black < 0.95
    non_uniform_rows = sum(
        1 for y in range(height) if len({img.getpixel((x, y)) for x in range(width)}) > 1
    )
    assert non_uniform_rows > 0


def test_dither_mode_offset_region_must_be_translated_by_caller(tmp_path):
    # Documents/exercises the "no x/y" contract directly: the returned
    # region is always (0,0)-relative regardless of where a caller intends
    # to place the fragment -- callers are responsible for offsetting it
    # (see text_label.py's icon wiring for a real caller that does this).
    image_id = _put_upload(tmp_path, _gradient(20, 20))
    _svg, _w, _h, region = image_object(
        image_id, target_h_px=20, target_w_px=20, mode="dither", data_dir=tmp_path
    )
    assert (region.x, region.y) == (0, 0)


# --- 6. Barcode/QR groups are never inside a dither region ------------------
# Structurally true (separate objects -- see objects.py's own module
# docstring), but pinned by an explicit test per the task brief: a rendered
# barcode label's object_map is always empty.


def test_barcode_label_object_map_stays_empty():
    from labelmaker.render.document import Tape
    from labelmaker.render.types import get_renderer
    from labelmaker.render.types.barcode_label import BarcodeLabelParams

    tape = Tape(width_mm=24).resolve()
    rendered = get_renderer("barcode").render(
        BarcodeLabelParams(symbology="qr", data="https://example.com"), tape
    )
    assert rendered.object_map == []


# --- 7. SECURITY: image_id must never escape data_dir/uploads/ -------------
# (coordinator-review-caught CRITICAL bug -- see module + file docstrings)


def test_image_id_regex_only_accepts_32_lowercase_hex_chars():
    assert IMAGE_ID_RE.match(uuid.uuid4().hex)
    for bad in ["not-hex", "A" * 32, "0" * 31, "0" * 33, "", "../etc/passwd", "/etc/passwd"]:
        assert not IMAGE_ID_RE.match(bad), f"{bad!r} should not match IMAGE_ID_RE"


def test_image_path_rejects_absolute_path_image_id(tmp_path):
    # Regression: Path("/a/uploads") / "/etc/passwd.png" DISCARDS the left
    # operand entirely (a pathlib gotcha) -- image_path() used to return
    # "/etc/passwd.png" unmodified for this input.
    secret = tmp_path / "outside" / "secret.png"
    secret.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(secret, format="PNG")

    data_dir = tmp_path / "data"
    with pytest.raises(ValueError, match="invalid image_id"):
        image_path(str(secret)[: -len(".png")], data_dir)


def test_image_object_rejects_absolute_path_image_id(tmp_path):
    secret = tmp_path / "outside" / "secret.png"
    secret.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(secret, format="PNG")

    data_dir = tmp_path / "data"
    malicious_id = str(secret)[: -len(".png")]  # e.g. "/tmp/.../outside/secret"
    with pytest.raises(ValueError, match="invalid image_id"):
        image_object(malicious_id, target_h_px=20, data_dir=data_dir)


def test_image_object_rejects_dotdot_traversal_image_id(tmp_path):
    # A sibling-of-uploads file the traversal id targets.
    secret = tmp_path / "secret.png"
    Image.new("RGB", (5, 5), "red").save(secret, format="PNG")
    (tmp_path / "uploads").mkdir()

    with pytest.raises(ValueError, match="invalid image_id"):
        image_object("../secret", target_h_px=20, data_dir=tmp_path)


def test_image_object_rejects_multi_level_dotdot_traversal_image_id(tmp_path):
    secret = tmp_path.parent / f"secret-{uuid.uuid4().hex}.png"
    Image.new("RGB", (5, 5), "red").save(secret, format="PNG")
    try:
        data_dir = tmp_path / "data"
        (data_dir / "uploads").mkdir(parents=True)
        traversal_id = f"../../{secret.stem}"
        with pytest.raises(ValueError, match="invalid image_id"):
            image_object(traversal_id, target_h_px=20, data_dir=data_dir)
    finally:
        secret.unlink(missing_ok=True)


def test_image_path_rejects_dot_or_slash_containing_ids(tmp_path):
    for bad_id in ["a.b", "a/b", "..", ".", "a\\b", "a b"]:
        with pytest.raises(ValueError, match="invalid image_id"):
            image_path(bad_id, tmp_path)


def test_image_path_valid_id_resolves_strictly_inside_uploads_dir(tmp_path):
    image_id = uuid.uuid4().hex
    path = image_path(image_id, tmp_path)
    assert path.resolve().is_relative_to((tmp_path / "uploads").resolve())
    assert path.name == f"{image_id}.png"
