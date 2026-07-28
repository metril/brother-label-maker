"""GET /api/gallery (task 2.14): render render.gallery's curated catalogue.

Every entry goes through router_labels._render_and_encode -- the exact
helper POST /api/render/preview uses -- so a gallery card is pixel-for-
pixel what the designer preview (and therefore the print) would show for
the same definition, including the synthetic short_label warning and the
serialization/{seq} expansion semantics. This router adds nothing to the
render path; it only adapts the helper's dict into GalleryItem cards and
memoizes them.

The cache is a plain module-level dict keyed by entry id -- every entry is
a fixed, deterministic definition (the same guarantee golden_fixtures.py's
own byte-lock tests rely on), so the first GET renders everything and every
call after is served from cache. A plain dict (not functools.lru_cache) so
tests can clear/inspect it directly and _render_entry stays a normal,
individually-patchable function (test_api_gallery.py's cache-hit test).
"""

from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import APIRouter

from labelmaker.api.deps import AppConfigDep
from labelmaker.api.router_labels import _render_and_encode
from labelmaker.render.document import LabelDefinition, Tape
from labelmaker.render.gallery import GALLERY_SCALE, GalleryEntry, GalleryItem, gallery_entries

router = APIRouter(tags=["gallery"])

_cache: dict[str, GalleryItem] = {}


def _render_entry(entry: GalleryEntry, data_dir: Path) -> GalleryItem:
    tape = Tape(width_mm=entry.tape_mm, family=entry.tape_family)
    definition = LabelDefinition(type=entry.type, tape=tape, params=entry.params)
    encoded = _render_and_encode(
        definition,
        GALLERY_SCALE,
        entry.serialization,
        0,  # a serialized entry always pictures instance 0 of its run
        entry.data_dir or data_dir,
    )
    return GalleryItem(
        id=entry.id,
        title=entry.title,
        blurb=entry.blurb,
        type=entry.type,
        tape=tape,
        params=entry.params,
        length_mm=encoded["length_mm"],
        png_b64=encoded["png_b64"],
        min_feed_mm=encoded["min_feed_mm"],
        warnings=encoded["warnings"],
        total_labels=encoded["total_labels"],
        sequence_value=encoded["sequence_value"],
    )


def _render_gallery(data_dir: Path) -> list[GalleryItem]:
    """Synchronous/CPU-bound (resvg) -- the route runs this in a worker
    thread, the same convention render_preview uses."""
    items = []
    for entry in gallery_entries():
        cached = _cache.get(entry.id)
        if cached is None:
            cached = _render_entry(entry, data_dir)
            _cache[entry.id] = cached
        items.append(cached)
    return items


@router.get("/gallery")
async def get_gallery(config: AppConfigDep) -> list[GalleryItem]:
    return await anyio.to_thread.run_sync(_render_gallery, config.data_dir)
