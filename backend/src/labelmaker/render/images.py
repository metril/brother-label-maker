"""Uploaded-image "objects" (task 2.7): threshold/dither placement of a
previously-uploaded image onto a label's canvas, parallel to
render/objects.py's barcode groups and render/symbols.py's icon groups.

Uploads themselves (POST/GET/DELETE /api/images) live in
api/router_images.py -- this module only reads an already-uploaded,
already-normalized file back off disk (`data_dir/uploads/{image_id}.png`,
always a plain RGB PNG with no alpha channel -- see router_images.py's
`upload_image` for the normalization step) and turns it into an embeddable
SVG fragment plus (dither mode only) an `ObjectRegion` for rasterize.py's
existing per-region Floyd-Steinberg mechanism (see rasterize.py's module
docstring and `ObjectRegion`'s own docstring in document.py). This is the
first REAL caller of that mechanism -- task 1.2 only exercised it with
synthetic gradients built directly in test code.

-- Two modes --

`mode="threshold"`: binarized HERE, at this layer, with the caller's own
`threshold` (0-255) -- the embedded PNG is already a true 1-bit-depth image
(PIL mode "1"), so rasterize.py's later whole-label threshold pass is a
no-op over these pixels (every one is already exactly 0 or 255, verified
via resvg_py directly: it decodes a 1-bit-depth PNG correctly, no special
casing needed on the embedding side). No `ObjectRegion` needed -- nothing
here for the dither mechanism to do.

`mode="dither"`: embedded as an 8-bit grayscale PNG, UNMODIFIED -- rasterize.
py's per-`ObjectRegion` Floyd-Steinberg pass (triggered by the returned
region) does the actual binarization, later, over the composited whole-label
bitmap. This is what makes a photo/gradient look like a real halftone
instead of a hard-edged threshold silhouette.

-- Sizing --

`target_h_px` is required; `target_w_px` is optional. Omitted: width is
derived preserving the source image's own aspect ratio (rounded to the
nearest integer pixel, floored at 1). Given explicitly (e.g. text_label.
py's icon wiring, which always wants a square regardless of the source
image's own proportions): the image is resized to EXACTLY
`target_w_px` x `target_h_px`, aspect ratio be damned -- that is the
caller's explicit choice, not this function's to second-guess.

-- No x/y parameters --

Unlike render/objects.py's barcode `*_object()` functions and render/
symbols.py's `symbol_object()` (both take x/y directly and bake a
`translate(x,y)` into their own returned `<g>`), `image_object()` does not.
The returned `ObjectRegion` (dither mode only) is therefore in this
function's OWN local coordinate space (x=0, y=0 -- i.e. relative to wherever
the caller ultimately places the returned `<image>` fragment), never the
label's absolute canvas space. A caller that wraps the returned fragment in
its own `<g transform="translate(px,py)">` (as text_label.py's icon wiring
does) MUST offset the region's x/y by that same (px, py) before adding it to
`RenderedLabel.object_map` -- rasterize.py crops `object_map` regions
directly against the final composited (untransformed) bitmap, so an
un-offset region would dither the wrong rectangle of the label.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Literal

from PIL import Image

from labelmaker.render.document import ObjectRegion

ImageMode = Literal["threshold", "dither"]


def uploads_dir(data_dir: Path) -> Path:
    """`data_dir/uploads` -- the one place uploaded images live, shared by
    router_images.py (writes/serves/deletes) and this module (reads)."""
    return data_dir / "uploads"


def image_path(image_id: str, data_dir: Path) -> Path:
    return uploads_dir(data_dir) / f"{image_id}.png"


def image_object(
    image_id: str,
    *,
    target_h_px: int,
    target_w_px: int | None = None,
    mode: ImageMode = "threshold",
    threshold: int = 128,
    data_dir: Path,
) -> tuple[str, int, int, ObjectRegion | None]:
    """Load a previously-uploaded image, scale it to (target_w_px or
    aspect-derived) x target_h_px with LANCZOS resampling, convert to
    grayscale, then either binarize (`mode="threshold"`) or leave it for
    rasterize.py's per-region dither (`mode="dither"`) -- see module
    docstring. Returns `(svg_fragment, width_px, height_px, object_region)`.

    Raises `ValueError` for an unknown `image_id` (no
    `data_dir/uploads/{image_id}.png` on disk) or an out-of-range
    `mode`/`target_h_px`/`target_w_px`/`threshold` -- 422-mappable by any
    caller that funnels ValueError through the usual error_message() path.
    """
    if mode not in ("threshold", "dither"):
        raise ValueError(f"mode must be 'threshold' or 'dither', got {mode!r}")
    if target_h_px <= 0:
        raise ValueError(f"target_h_px must be positive, got {target_h_px}")
    if target_w_px is not None and target_w_px <= 0:
        raise ValueError(f"target_w_px must be positive, got {target_w_px}")
    if not (0 <= threshold <= 255):
        raise ValueError(f"threshold must be in [0, 255], got {threshold}")

    path = image_path(image_id, data_dir)
    if not path.is_file():
        raise ValueError(f"unknown image_id {image_id!r}")

    img = Image.open(path)
    img.load()

    if target_w_px is not None:
        w = target_w_px
    else:
        w = max(1, round(img.width * (target_h_px / img.height)))
    h = target_h_px

    resized = img.resize((w, h), resample=Image.Resampling.LANCZOS)
    gray = resized.convert("L")

    region: ObjectRegion | None = None
    if mode == "threshold":
        binarized = gray.point(lambda p, t=threshold: 255 if p >= t else 0)
        out_img = binarized.convert("1", dither=Image.Dither.NONE)
    else:
        out_img = gray
        region = ObjectRegion(x=0, y=0, width=w, height=h, mode="dither")

    buf = io.BytesIO()
    out_img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    svg = f'<image x="0" y="0" width="{w}" height="{h}" href="data:image/png;base64,{b64}"/>'
    return svg, w, h, region
