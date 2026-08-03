"""Track C1: a single composited preview of a whole chained print job.

Renders every label in a print request exactly once (mirroring jobs/
worker.py's own _expand_and_render/_render_all -- render_definition ->
rasterize, the SAME "one render path" every render/print call site in this
codebase goes through: see render/__init__.py's module docstring), then
stitches the resulting per-label PIL mode "1" images into ONE composite
strip that shows what the physical tape will actually look like under the
request's chain_mode -- gaps, cut marks, and all. api/router_print.py's
POST /print/preview is the only caller, via build_chained_preview_from_rendered
(see the M2 fix-up note below for why it's that entry point, not
build_chained_preview itself).

jobs/ legally imports both labelmaker.render and labelmaker.driver (see
jobs/worker.py's own module docstring) -- this module does too, but ONLY
labelmaker.driver.geometry/protocol (pure constants/enums, no I/O), never
labelmaker.driver.job/raster/... -- see the "hand-duplicated constants" note
on _CUT_MARK_GAP_DOTS/_CUT_MARK_WIDTH_DOTS below for why.

Tape-usage totals (total_mm/content_mm/feed_overhead_mm/per_label_mm/notes)
come from render.estimate.estimate() -- the ONE authoritative model for "how
much tape does this job use" (task 2.9). This module NEVER re-derives them;
it only turns the SAME numbers into pixels for the composite image.

Review fix-up (M2, docs/code-review-2026-08.md): api/router_print.py's
preview_print_job used to call this module's build_chained_preview() AFTER
already running an equivalent render_definition() pass of its own (for
pre-flight validation + tape-usage estimation, api/router_print.py's
_validate_and_render) -- rendering every label twice. build_chained_preview
still exists and still does its own render_definition/expand_definition
pass, for direct callers (tests, or any future non-API caller) that don't
already have RenderedLabel objects lying around. But the API's own path now
calls build_chained_preview_from_rendered() with the RenderedLabel list
_validate_and_render already produced -- rasterize+composite only, no
second render_definition call. Both entry points share the same
rasterize->estimate->composite tail (_finish below) so there is exactly one
copy of that logic either way. composite_dimensions() computes the
composite's pre-rasterize pixel footprint from that SAME RenderedLabel list
alone (no PIL object involved) so router_print.py's pixel-budget guard (H1)
can reject an oversized composite before this module ever calls Image.new().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from labelmaker.driver.geometry import MIN_FEED_MM, dots_to_mm, mm_to_dots
from labelmaker.driver.protocol import ChainMode
from labelmaker.render import rasterize, render_definition
from labelmaker.render.document import LabelDefinition, RenderedLabel, RenderWarning
from labelmaker.render.estimate import TapeEstimate, estimate
from labelmaker.render.serialize import Sequence, expand_definition

# Must stay in lockstep with driver.job.JobOptions' own cut_mark_gap/
# cut_mark_width defaults (both 4 raster lines) -- driver.job._cut_mark_line
# operates on raster BYTES/pins, one full 16-byte line at a time, so there is
# no image-space function of its to call here; this is a hand-duplicated
# copy, same as render/estimate.py's own copy of the exact same two
# constants (see that module's docstring) -- test_api_print_preview.py's
# drift-guard test is this copy's equivalent of test_estimate.py's.
_CUT_MARK_GAP_DOTS = 4
_CUT_MARK_WIDTH_DOTS = 4

# PIL mode "1": 1 == white, 0 == black (matches driver/raster.py's own "pixel
# value 0 = black" convention -- the SAME bit semantics the real print path
# uses, kept consistent here purely for a human reading this file, not
# because this module ever talks to raster.py).
_WHITE = 1
_BLACK = 0


@dataclass(frozen=True)
class LabelSegment:
    """One label's position along the composite strip, in mm -- derived from
    the SAME pixel x-offsets the composite image itself was pasted at
    (dots_to_mm of those offsets), so the image and these numbers can never
    disagree with each other.

    L7 (2026-08 review): in CUT_EACH mode, these mm values are positions
    along the COMPOSITED PREVIEW IMAGE _composite() builds below, not along
    any single physical tape strip -- see that function's own "UNIT TRAP"
    note. cut_each produces n physically separate strips, each starting at
    0 mm on its own piece of tape; the synthetic MIN_FEED_MM gap this class'
    start_mm/end_mm are offset by exists only in the preview image, never
    on real tape. Surfaced verbatim as api/router_print.py's
    ChainedPreviewSegment -- see that model's own docstring, which is the
    one an external API consumer actually reads.
    """

    index: int
    start_mm: float
    end_mm: float
    length_mm: float


@dataclass(frozen=True)
class ChainedPreview:
    image: Image.Image  # mode "1", height == tape.print_dots
    estimate: TapeEstimate
    segments: list[LabelSegment]
    label_warnings: list[list[RenderWarning]]  # index-aligned with segments


def _expand_and_render(
    labels: list[LabelDefinition], serialization: Sequence | None, data_dir: Path
) -> tuple[list[Image.Image], list[LabelDefinition], list[list[RenderWarning]]]:
    """Mirrors jobs/worker.py's _expand_and_render/_render_all: re-expand a
    task 2.4 serialization template (if present), then render_definition ->
    rasterize every resulting label, exactly once each. Kept as its own copy
    here rather than importing worker.py's private helpers -- preview and
    print are deliberately independent call sites onto the same shared
    render path, not a shared call chain (worker.py's version also threads a
    JobStream build afterward that preview has no use for).
    """
    if serialization is not None:
        # task 2.4-style re-expansion: `labels` holds exactly ONE template
        # (router_print.py's _validate_and_measure/_validate_and_render both
        # enforce that before either ever calls into this module) -- expand
        # it into the real per-label definitions.
        bound = expand_definition(labels[0].model_dump(mode="json"), serialization)
        definitions = [LabelDefinition.model_validate(raw) for raw in bound]
    else:
        definitions = list(labels)

    images: list[Image.Image] = []
    label_warnings: list[list[RenderWarning]] = []
    for defn in definitions:
        rendered = render_definition(defn, data_dir=data_dir)
        images.append(rasterize(rendered))
        label_warnings.append(list(rendered.warnings))

    return images, definitions, label_warnings


def _dash_mark_image(width: int, height: int) -> Image.Image:
    """One cut-mark dash block, `width` px wide and `height` px tall -- the
    image-space translation of driver.job._cut_mark_line's dash pattern: a
    pixel is black where `(y // 4) % 2 == 0`, `y` counted from the top of
    the print area (the same axis _cut_mark_line's `offset` counts from
    tape.left_pin along). _cut_mark_line deliberately does NOT track
    RasterConfig.flip_pins (cut marks are synthetic, not image-derived --
    see that function's own docstring), so this needs no flip_pins branch
    either."""
    img = Image.new("1", (width, height), _WHITE)
    for y in range(height):
        if (y // 4) % 2 == 0:
            for x in range(width):
                img.putpixel((x, y), _BLACK)
    return img


def _composite(
    images: list[Image.Image], chain_mode: ChainMode
) -> tuple[Image.Image, list[LabelSegment]]:
    """Stitch already-rasterized `images` (all the same height) into one
    composite strip per `chain_mode`:

      - chain_ff: butted together, zero gap -- job.py's CHAIN_FF branch
        emits every page back to back on one continuous chain with no gap,
        a single cut at the very end.
      - cut_each: a blank `mm_to_dots(MIN_FEED_MM)`-px gap between labels.
        UNIT TRAP: this gap is a SCREEN-ONLY convention, not a physical one
        -- cut_each really means n physically SEPARATE tape strips, each its
        own independent job (see job.py's _build_chained CUT_EACH branch);
        there is no such gap on real tape. It exists here purely so the
        preview shows n visually distinct pieces instead of drawing them
        edge-to-edge as if they were one continuous strip.
      - strip_marks: a gap(4)+dashes(4)+gap(4) dot block between labels,
        mirroring driver.job._build_strip_marks's own `combined = gap +
        dashes + gap` assembly exactly (see _dash_mark_image above for the
        dash pattern itself).

    Returns the composite (mode "1") plus each label's LabelSegment, built
    from the SAME x pixel offsets the image was pasted at.
    """
    n = len(images)
    height = images[0].height

    if chain_mode is ChainMode.CUT_EACH:
        block_dots = mm_to_dots(MIN_FEED_MM)
    elif chain_mode is ChainMode.STRIP_MARKS:
        block_dots = 2 * _CUT_MARK_GAP_DOTS + _CUT_MARK_WIDTH_DOTS
    else:  # CHAIN_FF
        block_dots = 0

    total_width = sum(img.width for img in images) + block_dots * max(n - 1, 0)
    composite = Image.new("1", (total_width, height), _WHITE)
    dash_img = (
        _dash_mark_image(_CUT_MARK_WIDTH_DOTS, height)
        if chain_mode is ChainMode.STRIP_MARKS and n > 1
        else None
    )

    segments: list[LabelSegment] = []
    x = 0
    for i, img in enumerate(images):
        if i > 0:
            if chain_mode is ChainMode.STRIP_MARKS:
                x += _CUT_MARK_GAP_DOTS
                composite.paste(dash_img, (x, 0))
                x += _CUT_MARK_WIDTH_DOTS
                x += _CUT_MARK_GAP_DOTS
            elif chain_mode is ChainMode.CUT_EACH:
                x += block_dots
            # CHAIN_FF: no gap at all.

        start_mm = dots_to_mm(x)
        composite.paste(img, (x, 0))
        x += img.width
        end_mm = dots_to_mm(x)
        segments.append(
            LabelSegment(index=i, start_mm=start_mm, end_mm=end_mm, length_mm=end_mm - start_mm)
        )

    return composite, segments


def _finish(
    images: list[Image.Image],
    label_warnings: list[list[RenderWarning]],
    chain_mode: ChainMode,
    margin_mm: float,
) -> ChainedPreview:
    """Shared tail of build_chained_preview and
    build_chained_preview_from_rendered, once every label is already a
    rasterized mode "1" image: derive lengths from those SAME images (never
    re-measured a different way), get the ONE authoritative tape-usage
    estimate, then composite. The one place this logic exists, regardless of
    which entry point produced `images`."""
    lengths_mm = [dots_to_mm(img.width) for img in images]
    tape_estimate = estimate(lengths_mm, chain_mode=chain_mode.value, margin_mm=margin_mm)

    composite, segments = _composite(images, chain_mode)

    return ChainedPreview(
        image=composite,
        estimate=tape_estimate,
        segments=segments,
        label_warnings=label_warnings,
    )


def composite_dimensions(rendered: list[RenderedLabel], chain_mode: ChainMode) -> tuple[int, int]:
    """(width_dots, height_dots) the composite _composite() would build for
    `rendered` + `chain_mode`, computed WITHOUT building it -- pure
    arithmetic over already-known RenderedLabel.width_px/height_px, using
    the exact same block_dots-per-chain_mode rule _composite itself uses
    (kept in lockstep because both read the same
    _CUT_MARK_GAP_DOTS/_CUT_MARK_WIDTH_DOTS/MIN_FEED_MM constants -- there is
    no third copy of this arithmetic to drift).

    Exists so router_print.py's pixel-budget guard (H1, docs/
    code-review-2026-08.md) can reject an oversized composite BEFORE any
    Image.new()/paste()/rasterize() call ever runs -- `rendered` here comes
    from a cheap render_definition() pass (no resvg call yet), so this
    function's own cost is negligible even for a large `rendered` list.
    """
    n = len(rendered)
    height = rendered[0].height_px
    if chain_mode is ChainMode.CUT_EACH:
        block_dots = mm_to_dots(MIN_FEED_MM)
    elif chain_mode is ChainMode.STRIP_MARKS:
        block_dots = 2 * _CUT_MARK_GAP_DOTS + _CUT_MARK_WIDTH_DOTS
    else:  # CHAIN_FF
        block_dots = 0
    width = sum(r.width_px for r in rendered) + block_dots * max(n - 1, 0)
    return width, height


def build_chained_preview_from_rendered(
    rendered: list[RenderedLabel], chain_mode: ChainMode, margin_mm: float
) -> ChainedPreview:
    """Same result as build_chained_preview, given `rendered` -- a list of
    already-produced RenderedLabel objects (e.g. router_print.py's
    _validate_and_render pre-flight) -- instead of raw LabelDefinitions plus
    a Sequence to expand. Skips render_definition/expand_definition
    entirely: only rasterizes (once each, exactly like
    build_chained_preview) and composites. Positional-only args for the same
    `anyio.to_thread.run_sync(build_chained_preview_from_rendered, ...)`
    reason build_chained_preview documents.

    Does NOT repeat build_chained_preview's own single-shared-tape check:
    RenderedLabel carries no Tape (that's the whole point -- it's already
    past the point where tape mattered), and the router's own
    _validate_and_render already enforces one-tape-per-job over the same
    labels before rendering them. A caller with pre-rendered labels that
    skipped that check is responsible for having made the same guarantee
    itself.
    """
    images = [rasterize(r) for r in rendered]
    label_warnings = [list(r.warnings) for r in rendered]
    return _finish(images, label_warnings, chain_mode, margin_mm)


def build_chained_preview(
    labels: list[LabelDefinition],
    serialization: Sequence | None,
    data_dir: Path,
    chain_mode: ChainMode,
    margin_mm: float,
) -> ChainedPreview:
    """Render every label in `labels` (re-expanding `serialization` first,
    task 2.4-style, if present) exactly once, then composite the result into
    one preview strip for `chain_mode`. Positional-only args (no
    keyword-only params) so this drops straight into
    `anyio.to_thread.run_sync(build_chained_preview, ...)` the same way
    every other blocking render/build call in this codebase does (see
    jobs/worker.py).

    Raises ValueError/KeyError on the same conditions render_definition/
    Tape.resolve() do (unknown type, invalid params, unknown tape width) --
    callers should catch these the same way router_print.py's other
    validation helpers do (KeyError/ValueError -> 422). Also raises
    ValueError if `labels` resolve to more than one distinct tape --
    belt-and-suspenders: api/router_print.py's _validate_and_render already
    rejects this (same message) BEFORE this function is ever called from the
    API (which in fact now calls build_chained_preview_from_rendered
    instead, precisely to avoid re-running this function's render pass --
    see M2, docs/code-review-2026-08.md), so this branch should be
    unreachable via POST /print/preview, but keeps this function safe to
    call directly (e.g. from tests) too.
    """
    images, definitions, label_warnings = _expand_and_render(labels, serialization, data_dir)

    tapes = {(defn.tape.width_mm, defn.tape.family) for defn in definitions}
    if len(tapes) > 1:
        raise ValueError("all labels in a print job must share the same tape")

    return _finish(images, label_warnings, chain_mode, margin_mm)
