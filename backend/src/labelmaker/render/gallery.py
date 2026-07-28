"""Curated gallery data for GET /api/gallery (task 2.14): example label
definitions spanning all nine registered types, for a single page a human
can scan to visually QA the whole catalogue at once (the review artifact
for Phase 2, and the fastest way to spot a rendering regression).

This module is DATA ONLY -- the entry catalogue and the response model.
Rendering lives in api/router_gallery.py, which routes every entry through
POST /api/render/preview's own _render_and_encode helper, so the gallery is
a third view onto the exact same render_definition -> rasterize ->
preview_png pipeline ("preview and print are the same bitmap" -- this
package's module docstring), with the same short_label warning and
serialization semantics. No entry here is hand-rendered or faked.

Most entries are sourced from tests/golden_fixtures.py rather than
re-typed here -- that module is already the curated, byte-locked example of
every label type (see its own docstring: "the single source of truth"),
so duplicating its param values here would just be a second copy to keep in
sync (the task brief's own instruction: "EXPOSE them rather than
duplicating"). tests/ has no __init__.py and is meant to be sibling-
imported by file path exactly like this -- scripts/regen_goldens.py already
does the identical sys.path trick for the identical reason. tests/ also
ships alongside src/ in every real deployment of this app (see
docker/Dockerfile: "tests/ -- harmless extra weight, kept ... so this COPY
stays a single line"). The import happens LAZILY inside gallery_entries()
rather than at module import time, so an environment that stripped tests/
(a slimmed image, a wheel-only install) degrades to a failing /api/gallery
endpoint instead of an app that can't boot at all.

A few entries below are genuinely new, not sourced from golden_fixtures.py
at all -- extra variety for types the golden set only shows one example of
(patch_panel's OTHER separator/orientation combination; a QR code short
enough to actually keep its caption, unlike the golden QR fixture, whose
caption is deliberately DROPPED as an interesting edge case -- see
BARCODE_TYPE_FIXTURES' own comment -- but isn't representative of the
common case on its own; and a serialized {seq} template, the brief's own
suggested extra, rendered through the preview path's serialization
machinery). These have no golden PNG and don't need one: nothing here is
byte-locked, only rendered live on request.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from labelmaker.render.document import RenderWarning, Tape
from labelmaker.render.serialize import Sequence
from labelmaker.render.types.barcode_label import BarcodeLabelParams
from labelmaker.render.types.divided_blocks import Orientation, Separator
from labelmaker.render.types.patch_panel import BlockText as PatchPanelBlockText
from labelmaker.render.types.patch_panel import PatchPanelParams

# Scaled down from POST /api/render/preview's own PreviewRequest default of
# the same value -- a gallery card is small, scale 2 is plenty of detail
# without inflating every cached PNG needlessly.
GALLERY_SCALE = 2


class GalleryItem(BaseModel):
    """One rendered gallery card -- the GET /api/gallery response element.

    `params` (+ type/tape) is what "Open in designer" loads into the
    designer store client-side; `min_feed_mm` is what DeckStrip needs to
    draw the feed-waste shadow (the same field PreviewResponse carries);
    `total_labels`/`sequence_value` are only non-null for a serialized
    entry (which of the expanded run's instances is pictured).
    """

    id: str
    title: str
    blurb: str
    type: str
    tape: Tape
    params: dict
    length_mm: float
    png_b64: str
    min_feed_mm: float
    warnings: list[RenderWarning]
    total_labels: int | None = None
    sequence_value: str | None = None


@dataclass(frozen=True)
class GalleryEntry:
    id: str
    title: str
    blurb: str
    type: str
    tape_mm: float
    tape_family: str
    params: dict  # a plain JSON-shaped dict -- LabelDefinition.params' own shape
    data_dir: Path | None = None
    # When set, `params` is a template containing {seq} tokens and the card
    # pictures instance 0 of the expanded run -- rendered through the same
    # expand_definition path POST /api/render/preview's serialization
    # support uses (router_labels._render_and_encode).
    serialization: Sequence | None = None


def _from_golden(fixture, *, id: str, title: str, blurb: str, type: str) -> GalleryEntry:  # noqa: A002
    """Adapts one of tests/golden_fixtures.py's own fixture dataclasses
    (GoldenFixture/TypeConfigFixture/ElectricalTypeFixture/BarcodeTypeFixture/
    CableTypeFixture -- they don't share a base class, but all carry
    `params`/`tape_mm`/`tape_family`, and the type-config-shaped ones also
    carry `type` themselves) into a GalleryEntry. `type` is always passed
    explicitly here rather than read off the fixture (FIXTURES/
    BARCODE_TYPE_FIXTURES carry no `type` field at all -- "text"/"barcode"
    are implicit in which tuple they live in) so this one function covers
    every fixture shape uniformly.
    """
    return GalleryEntry(
        id=id,
        title=title,
        blurb=blurb,
        type=type,
        tape_mm=fixture.tape_mm,
        tape_family=fixture.tape_family,
        params=fixture.params.model_dump(mode="json"),
        data_dir=getattr(fixture, "data_dir", None),
    )


@lru_cache(maxsize=1)
def gallery_entries() -> tuple[GalleryEntry, ...]:
    """The curated catalogue, built on first use. Lazy so the
    tests/golden_fixtures.py sibling-import (module docstring) can't take
    app startup down with it."""
    import sys

    backend_dir = Path(__file__).resolve().parents[3]
    tests_dir = backend_dir / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    import golden_fixtures

    return (
        # -- general / text (4) --
        _from_golden(
            golden_fixtures.FIXTURES[0],
            id="text-hello",
            title="Simple text",
            blurb="A single line of text — the baseline label.",
            type="text",
        ),
        _from_golden(
            golden_fixtures.FIXTURES[1],
            id="text-two-line-bold",
            title="Two-line bold heading",
            blurb="Stacked bold Roboto Condensed text on narrow 12mm tape.",
            type="text",
        ),
        _from_golden(
            golden_fixtures.FIXTURES[3],
            id="text-symbol-icon",
            title="Text with a symbol icon",
            blurb="A bundled Material Symbol leading the text, text shifted right to make room.",
            type="text",
        ),
        _from_golden(
            golden_fixtures.FIXTURES[4],
            id="text-image-icon",
            title="Text with a dithered photo icon",
            blurb="An uploaded photo, Floyd–Steinberg dithered to 1-bit alongside the text.",
            type="text",
        ),
        # -- general / barcode (4) --
        _from_golden(
            golden_fixtures.BARCODE_TYPE_FIXTURES[0],
            id="barcode-qr-url",
            title="QR code, URL (caption dropped)",
            blurb="A URL QR code whose caption is too wide to keep — watch for the warning chip.",
            type="barcode",
        ),
        GalleryEntry(
            id="barcode-qr-asset",
            title="QR code, asset tag",
            blurb="A short asset-tag QR code whose caption comfortably fits underneath.",
            type="barcode",
            tape_mm=24,
            tape_family="tze",
            params=BarcodeLabelParams(symbology="qr", data="ASSET-0118").model_dump(mode="json"),
        ),
        _from_golden(
            golden_fixtures.BARCODE_TYPE_FIXTURES[1],
            id="barcode-code128-asset",
            title="Code128, asset tag",
            blurb="A classic 1D barcode with the asset id printed as its own caption.",
            type="barcode",
        ),
        _from_golden(
            golden_fixtures.BARCODE_TYPE_FIXTURES[2],
            id="barcode-datamatrix-short",
            title="DataMatrix, no caption",
            blurb="A compact 2D DataMatrix code on 12mm tape with the caption turned off.",
            type="barcode",
        ),
        # -- network / patch_panel (3) --
        _from_golden(
            golden_fixtures.TYPE_CONFIG_FIXTURES[0],
            id="patch-panel-6block",
            title="Patch panel, 6 ports",
            blurb="Six equal blocks with a LINE separator — Brother's classic patch-panel layout.",
            type="patch_panel",
        ),
        GalleryEntry(
            id="patch-panel-vertical-frame",
            title="Patch panel, vertical + framed",
            blurb="The same patch-panel engine with a FRAME separator and vertical orientation.",
            type="patch_panel",
            tape_mm=24,
            tape_family="tze",
            params=PatchPanelParams(
                blocks=[PatchPanelBlockText(lines=[f"CH{i}"]) for i in range(1, 4)],
                block_length_mm=20.0,
                separator=Separator.FRAME,
                orientation=Orientation.VERTICAL,
            ).model_dump(mode="json"),
        ),
        GalleryEntry(
            id="patch-panel-serialized",
            title="Patch panel, serialized run",
            blurb=(
                "A {seq} template expanded into four panel strips — "
                "pictured: panel 1 of the run."
            ),
            type="patch_panel",
            tape_mm=24,
            tape_family="tze",
            params=PatchPanelParams(
                blocks=[PatchPanelBlockText(lines=[f"{{seq}}-{port}"]) for port in range(1, 5)],
                block_length_mm=20.0,
                separator=Separator.LINE,
            ).model_dump(mode="json"),
            serialization=Sequence(kind="numeric", start=1, count=4),
        ),
        # -- network / punch_down (1) --
        _from_golden(
            golden_fixtures.TYPE_CONFIG_FIXTURES[1],
            id="punch-down-4pair",
            title="Punch-down block, 4-pair",
            blurb="Numbered pairs for a 110-style punch-down block, 12mm tape.",
            type="punch_down",
        ),
        # -- network / faceplate (1) --
        _from_golden(
            golden_fixtures.TYPE_CONFIG_FIXTURES[2],
            id="faceplate-2block",
            title="Wall-plate faceplate",
            blurb="Two labeled ports for a keystone wall plate.",
            type="faceplate",
        ),
        # -- network / cable_wrap (1) --
        _from_golden(
            golden_fixtures.CABLE_TYPE_FIXTURES[0],
            id="cable-wrap-switch-port",
            title="Cable wrap, switch port",
            blurb="A repeating wrap label around a 6mm cable, readable from any angle.",
            type="cable_wrap",
        ),
        # -- network / cable_flag (1) --
        _from_golden(
            golden_fixtures.CABLE_TYPE_FIXTURES[1],
            id="cable-flag-fiber",
            title="Cable flag, fiber run",
            blurb="A flag label folded around a thin fiber cable for a protruding read tab.",
            type="cable_flag",
        ),
        # -- electrical / terminal_block (1) --
        _from_golden(
            golden_fixtures.ELECTRICAL_TYPE_FIXTURES[0],
            id="terminal-block-12",
            title="DIN-rail terminal block",
            blurb="Twelve numbered terminals for a DIN-rail block, on 9mm tape.",
            type="terminal_block",
        ),
        # -- electrical / breaker_box (1) --
        _from_golden(
            golden_fixtures.ELECTRICAL_TYPE_FIXTURES[1],
            id="breaker-box-panel",
            title="Breaker panel column",
            blurb="A panel schedule column with odd-numbered slots for 1- and 2-pole breakers.",
            type="breaker_box",
        ),
    )
