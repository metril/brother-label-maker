"""POST /api/print, POST /api/print/estimate, POST /api/print/preview,
GET /api/print/jobs/{id}, POST /api/print/jobs/{id}/cancel,
GET /api/print/jobs/{id}/stream.

The actual render/build/print work happens in jobs/worker.py, off a queue --
this router only does cheap validation, persistence, and job-record I/O.
POST /api/print/preview is the one exception that does real render work
inline (synchronously, off the event-loop thread) rather than queuing a job
-- see jobs/chained_preview.py.
"""

from __future__ import annotations

import base64
import dataclasses
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from labelmaker.api.deps import AppConfigDep, BusDep, DbDep, QueueDep, error_message
from labelmaker.driver.geometry import MARGIN_MAX_MM, MARGIN_MIN_MM, dots_to_mm
from labelmaker.driver.protocol import ChainMode
from labelmaker.jobs.chained_preview import (
    build_chained_preview_from_rendered,
    composite_dimensions,
)
from labelmaker.render import preview_png, render_definition
from labelmaker.render.document import LabelDefinition, RenderedLabel
from labelmaker.render.estimate import estimate
from labelmaker.render.serialize import Sequence, expand_definition, ordered_values

router = APIRouter(prefix="/print", tags=["print"])

# H1 (docs/code-review-2026-08.md): POST /print/preview composites every
# label into one PIL strip and then upscales it by `scale` (1..8) -- nothing
# previously bounded the product, and the request's own legal caps multiply
# out to tens of gigabytes (100 labels x 1000mm each x scale=8) or, even at
# the shipped UI's own hardcoded scale=2, hundreds of megapixels for a
# maximum-size 1000-label serialized run. MAX_PREVIEW_PIXELS bounds the
# FINAL (post-scale) composite pixel count -- width_dots*scale *
# height_dots*scale -- the same quantity `preview_png` would actually
# allocate a PIL buffer for.
#
# 40,000,000 (40 MP) is chosen from the geometry, not the legal maximum: a
# full-width (24mm/128-dot) 1000-label cut_each run at typical few-cm label
# lengths, or a few hundred labels at the UI's own scale=2, both clear it
# comfortably (a realistic single preview is at most tens of megapixels
# pre-scale); the reproduced abuse cases (100 labels x 1000mm, or 1000
# labels through the UI's default scale=2 alone) do not. It also sits well
# inside both known hard ceilings so a request that DOES clear this cap can
# never hit either of them: Pillow's own decompression-bomb default
# (`Image.MAX_IMAGE_PIXELS`, ~178.9 MP) and the point real Chrome stops
# decoding the resulting PNG at all (reproduced in the review between
# ~23.7 MP, which decodes, and ~259 MP, which shows the broken-image glyph).
MAX_PREVIEW_PIXELS = 40_000_000


class PrintOptions(BaseModel):
    chain_mode: ChainMode = ChainMode.CUT_EACH
    # L6 (2026-08 review): bounded to match driver/geometry.clamp_margin_mm,
    # which the wire path (strategies.py) already clamps `margin_mm`
    # through before it ever reaches the printer -- previously this field
    # had no ge/le at all, so render.estimate.estimate() (called from this
    # same PrintOptions on POST /print/estimate, the preview stats row, and
    # the tape_used_mm persisted onto every job record) could report a
    # figure the driver would silently clamp away from at print time.
    # Reusing the SAME constants (not re-typed bounds) is what
    # test_router_print_margin_bounds_match_geometry_clamp guards against
    # drifting apart.
    margin_mm: float = Field(default=2.0, ge=MARGIN_MIN_MM, le=MARGIN_MAX_MM)
    auto_cut: bool = True


class PrintRequest(BaseModel):
    labels: list[LabelDefinition] = Field(min_length=1, max_length=100)
    options: PrintOptions = Field(default_factory=PrintOptions)
    # task 2.4: when set, `labels` must be exactly ONE template definition
    # (checked in create_print_job below) -- the job snapshot stores that
    # template + this spec UNEXPANDED (see create_print_job's db.
    # create_print_job call), and jobs/worker.py expands via
    # expand_definition() at render time. Reprint therefore re-derives the
    # same N labels from the same (template, serialization) pair rather
    # than replaying a persisted, already-expanded list.
    serialization: Sequence | None = None


def _validate_render_side(labels: list[LabelDefinition], data_dir: Path) -> list[RenderedLabel]:
    """Cheap per-label validation: resolve each label's tape and validate its
    params against the target type's own Params model (render_definition
    does both, plus building the SVG -- still no resvg call). The expensive
    step, rasterize(), is deliberately deferred to the worker (or, for POST
    /print/preview, to build_chained_preview_from_rendered) so a batch of
    100 labels doesn't rasterize before the client even gets a job id back.
    `data_dir` (task 2.7) is threaded through so a "text" label's
    `icon.kind="image"` param resolves against the same uploads/ directory
    the worker will use -- an unknown image_id fails HERE, at POST time,
    not after the job is already queued.

    Returns each label's RenderedLabel (task 2.9 reuses this SAME render
    pass -- no second render_definition call -- to feed
    render.estimate.estimate() via dots_to_mm(width_px); review fix-up M2
    reuses it a second time, to feed POST /print/preview's own composite
    build without re-running render_definition yet again -- see
    _validate_and_render below).
    """
    return [render_definition(defn, data_dir=data_dir) for defn in labels]


def _validate_serialized_print(
    template: LabelDefinition, serialization: Sequence, data_dir: Path
) -> tuple[list[dict], list[RenderedLabel]]:
    """task 2.4's serialized-print pre-flight: expand `template` now (still
    no resvg call) so an ALPHA run stepping below 'A'/beyond 'ZZZ' or an
    unknown {csv.<col>} in the template comes back as an immediate 422,
    the same "fail before the job is even queued" guarantee
    _validate_render_side gives the non-serialized path -- rather than a
    job that gets queued, dequeued, and only THEN fails. Also
    render_definition()-validates every expanded label (same per-label
    check _validate_render_side does), and returns the expanded bound
    definitions so the caller (create_print_job) gets an accurate
    label_count without a second expansion pass.

    Review fix-up: a run can carry up to 1000 labels, so a bare
    render_definition() failure ("each line must be <= 200 chars, got
    214") is useless without saying WHICH of the 1000 it came from --
    each per-label failure is re-raised prefixed with its 0-based index
    and the sequence value that produced it (ordered_values(serialization)
    is in the exact same order expand_definition's `bound` is), so the
    caller can go straight to the offending row/value instead of
    bisecting a 1000-label run by hand.

    Returns (bound, rendered) -- rendered mirrors _validate_render_side's
    own return (task 2.9's addition, extended by M2): one RenderedLabel per
    expanded label, in the same order as `bound`, for
    render.estimate.estimate() AND (for POST /print/preview specifically)
    build_chained_preview_from_rendered to both consume without a second
    render pass.
    """
    bound = expand_definition(template.model_dump(mode="json"), serialization)
    values = ordered_values(serialization)
    rendered: list[RenderedLabel] = []
    for i, (raw, value) in enumerate(zip(bound, values, strict=True)):
        try:
            r = render_definition(LabelDefinition.model_validate(raw), data_dir=data_dir)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"label {i} (sequence value {value!r}): {error_message(exc)}") from exc
        rendered.append(r)
    return bound, rendered


async def _validate_and_render(
    body: PrintRequest, data_dir: Path
) -> tuple[int, list[RenderedLabel]]:
    """Shared pre-flight: the SAME cheap validation (serialization shape,
    per-label render/params validation, single-shared-tape check) POST
    /api/print has always done at 202-time, now also returning each label's
    RenderedLabel -- the render_definition() output, still no resvg call.
    Returns (label_count, rendered), `rendered` index-aligned with whatever
    build_chained_preview_from_rendered would eventually rasterize (the
    expanded per-label list for a serialized job, `body.labels` itself
    otherwise) -- in the same order build_job will eventually receive the
    images in.

    Review fix-up (M2, docs/code-review-2026-08.md): split out of
    _validate_and_measure (below, now a thin wrapper over this) so POST
    /api/print/preview -- the one caller that goes on to actually
    rasterize+composite -- can reuse these SAME RenderedLabel objects
    instead of paying for a second render_definition pass per label.
    create_print_job/estimate_print_job/router_history.py's reprint
    preflight only ever need the lengths in mm, via _validate_and_measure,
    and never see `rendered` at all.
    """
    if body.serialization is not None:
        if len(body.labels) != 1:
            raise HTTPException(
                status_code=422,
                detail=(
                    "print requests with `serialization` must contain exactly one "
                    f"template label, got {len(body.labels)}"
                ),
            )
        try:
            bound, rendered = await anyio.to_thread.run_sync(
                _validate_serialized_print, body.labels[0], body.serialization, data_dir
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=error_message(exc)) from exc
        label_count = len(bound)
    else:
        try:
            rendered = await anyio.to_thread.run_sync(_validate_render_side, body.labels, data_dir)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=error_message(exc)) from exc
        label_count = len(body.labels)

    tapes = {(label.tape.width_mm, label.tape.family) for label in body.labels}
    if len(tapes) > 1:
        raise HTTPException(
            status_code=422, detail="all labels in a print job must share the same tape"
        )

    return label_count, rendered


async def _validate_and_measure(body: PrintRequest, data_dir: Path) -> tuple[int, list[float]]:
    """Thin wrapper over _validate_and_render for the callers that only ever
    needed each label's rendered length in mm, not the RenderedLabel objects
    themselves -- create_print_job (which goes on to create+enqueue the
    job), estimate_print_job (task 2.9's POST /api/print/estimate, which
    does neither), and router_history.py's reprint preflight. Returns
    (label_count, label_lengths_mm), unchanged from before the M2 split.
    """
    label_count, rendered = await _validate_and_render(body, data_dir)
    lengths_mm = [dots_to_mm(r.width_px) for r in rendered]
    return label_count, lengths_mm


@router.post("", status_code=202)
async def create_print_job(
    body: PrintRequest, db: DbDep, queue: QueueDep, bus: BusDep, config: AppConfigDep
) -> dict:
    label_count, lengths_mm = await _validate_and_measure(body, config.data_dir)
    tape_estimate = estimate(
        lengths_mm, chain_mode=body.options.chain_mode.value, margin_mm=body.options.margin_mm
    )

    # `body.model_dump` snapshots `labels`/`serialization` exactly as
    # posted -- for a serialized job that's [template] + the Sequence spec,
    # UNEXPANDED (the brief's DECIDED contract: reprint re-expands from
    # this snapshot via jobs/worker.py, rather than replaying an already-
    # expanded list persisted at POST time).
    #
    # tape_used_mm is stored from THIS estimate at creation time (task 2.9)
    # -- so a job's history entry shows an estimated tape figure even if it
    # later fails before ever printing -- and jobs/worker.py refines it to
    # the actual post-render figure once the job completes successfully
    # (see that module: same value unless the render genuinely changed).
    job = await db.create_print_job(
        definition=body.model_dump(mode="json"),
        label_count=label_count,
        chain_mode=body.options.chain_mode.value,
        tape_used_mm=tape_estimate.total_mm,
    )
    job_id = job["id"]

    # Broadcast before enqueueing: guarantees job.queued reaches any
    # connected client before the worker could possibly emit job.started for
    # the same id (see test_api_ws.py's ordering assertion).
    await bus.broadcast({"event": "job.queued", "job_id": job_id})
    await queue.put(job_id)

    return {"job_id": job_id}


@router.post("/estimate")
async def estimate_print_job(body: PrintRequest, config: AppConfigDep) -> dict:
    """Task 2.9: the SAME request body POST /api/print accepts (labels/
    options/serialization), returning a TapeEstimate + `label_count`
    WITHOUT creating a job -- no db.create_print_job call, no enqueue, no
    broadcast. This is what a "how much tape will this use?" UI (the
    JobTray) calls before committing to an actual print.
    """
    label_count, lengths_mm = await _validate_and_measure(body, config.data_dir)
    tape_estimate = estimate(
        lengths_mm, chain_mode=body.options.chain_mode.value, margin_mm=body.options.margin_mm
    )
    return {"label_count": label_count, **dataclasses.asdict(tape_estimate)}


class PrintPreviewRequest(PrintRequest):
    """POST /api/print/preview's body: identical to PrintRequest (labels/
    options/serialization) plus `scale` -- the same nearest-neighbor PNG
    upscale factor POST /api/render/preview already exposes for a single
    label (router_labels.py's PreviewRequest), applied here to the whole
    composited chain strip."""

    scale: int = Field(default=2, ge=1, le=8)


class ChainedPreviewSegment(BaseModel):
    """One label's position along the composited preview strip.

    UNIT TRAP: start_mm/end_mm/length_mm are tape-length millimetres
    (render.geometry.dots_to_mm of the composite's pixel x-offsets), never
    pixels -- see ChainedPreviewResponse's own UNIT TRAP note for the
    pixel side of this same contract.

    L7 (2026-08 review): in CUT_EACH mode specifically, these mm values are
    positions along the COMPOSITED PREVIEW IMAGE, not along any single
    physical tape strip -- cut_each really means n physically SEPARATE
    strips, each starting at 0 mm on its own piece of tape (see
    jobs/chained_preview.py's `_composite`, "UNIT TRAP: this gap is a
    SCREEN-ONLY convention, not a physical one"). The composite inserts a
    synthetic `MIN_FEED_MM` blank separator between labels purely so the
    preview image shows n visually distinct pieces, and start_mm/end_mm
    are derived from THAT padded image -- so e.g. segments[2] in a 3-label
    cut_each job is offset by ~2 synthetic gaps' worth of mm that exist on
    no physical strip. chain_ff and strip_marks have no such fiction:
    chain_ff really is one continuous strip (zero gap), and strip_marks'
    gap is real cut-mark tape width, not a synthetic screen-only pad.
    """

    index: int
    start_mm: float
    end_mm: float
    length_mm: float


class ChainedPreviewResponse(BaseModel):
    """POST /api/print/preview's response: a single composited PNG showing
    the whole chained job as it will physically lay out on tape (butted for
    chain_ff, blank gaps for cut_each, cut-mark dashes for strip_marks --
    see jobs/chained_preview.build_chained_preview_from_rendered), plus the SAME
    TapeEstimate fields POST /api/print/estimate returns (never re-derived
    here -- render.estimate.estimate() is the one authoritative source for
    all of total_mm/content_mm/feed_overhead_mm/per_label_mm/notes).

    UNIT TRAP: `png_b64` decodes to an image scaled by `scale`
    (nearest-neighbor -- see render/rasterize.py's preview_png) -- never
    derive a millimetre figure from its pixel dimensions; use total_mm /
    segments' start_mm/end_mm/length_mm instead, which are always UNSCALED
    tape-length millimetres regardless of `scale`.
    """

    png_b64: str
    chain_mode: ChainMode
    total_mm: float
    content_mm: float
    feed_overhead_mm: float
    per_label_mm: float
    notes: list[str]
    segments: list[ChainedPreviewSegment]
    # Per-label RenderWarning.message strings, each prefixed "label {i}: "
    # (0-based, same index space as `segments`) -- the same "label {i}: ..."
    # convention _validate_serialized_print's own 422 messages use above,
    # applied here to non-fatal warnings instead of a raised error.
    warnings: list[str]


@router.post("/preview")
async def preview_print_job(
    body: PrintPreviewRequest, config: AppConfigDep
) -> ChainedPreviewResponse:
    """A single composited preview of the whole chained job. Validated
    exactly like POST /api/print and POST /api/print/estimate --
    _validate_and_render (below) does the SAME checks _validate_and_measure
    does for parity (serialization expansion, serialization-vs-multi-label
    shape, per-label param/tape validation, single-shared-tape check) --
    before jobs/chained_preview.build_chained_preview_from_rendered does the
    actual per-label rasterize + composite, off the event-loop thread like
    every other render/rasterize call in this codebase. No job is created;
    nothing is enqueued or persisted (same as POST /api/print/estimate).

    Review fix-up M2 (docs/code-review-2026-08.md): this used to call
    _validate_and_measure for validation ALONE, discarding its render pass,
    then have build_chained_preview render every label again from scratch --
    every label rendered twice. _validate_and_render instead hands the SAME
    RenderedLabel objects straight to build_chained_preview_from_rendered,
    so each label is rendered exactly once total.

    Review fix-up H1 (docs/code-review-2026-08.md): the composite's pixel
    footprint (post-`scale`) is computed from those SAME RenderedLabel
    objects -- via composite_dimensions(), pure arithmetic, no PIL object
    involved -- and checked against MAX_PREVIEW_PIXELS BEFORE any
    rasterize()/Image.new() call, so an oversized request 422s instead of
    exhausting memory or producing a PNG neither Pillow nor a browser can
    decode. A MemoryError from the render/composite/encode calls themselves
    (a backstop for whatever the budget check doesn't catch) maps to 507,
    never a raw 500.
    """
    _, rendered = await _validate_and_render(body, config.data_dir)

    width_dots, height_dots = composite_dimensions(rendered, body.options.chain_mode)
    scaled_width = width_dots * body.scale
    scaled_height = height_dots * body.scale
    composite_pixels = scaled_width * scaled_height
    if composite_pixels > MAX_PREVIEW_PIXELS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"chained preview would be {scaled_width}x{scaled_height} px "
                f"({composite_pixels:,} px total) at scale={body.scale}, exceeding the "
                f"{MAX_PREVIEW_PIXELS:,}px cap -- reduce the number of labels, their "
                "length, or `scale`"
            ),
        )

    try:
        preview = await anyio.to_thread.run_sync(
            build_chained_preview_from_rendered,
            rendered,
            body.options.chain_mode,
            body.options.margin_mm,
        )
        png_bytes = await anyio.to_thread.run_sync(preview_png, preview.image, body.scale)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc
    except MemoryError as exc:
        raise HTTPException(
            status_code=507,
            detail=(
                "ran out of memory building the chained preview composite "
                f"(requested {scaled_width}x{scaled_height} px) -- try a smaller "
                "`scale` or fewer/shorter labels"
            ),
        ) from exc

    warnings = [
        f"label {i}: {warning.message}"
        for i, label_warnings in enumerate(preview.label_warnings)
        for warning in label_warnings
    ]

    return ChainedPreviewResponse(
        png_b64=base64.b64encode(png_bytes).decode("ascii"),
        chain_mode=body.options.chain_mode,
        total_mm=preview.estimate.total_mm,
        content_mm=preview.estimate.content_mm,
        feed_overhead_mm=preview.estimate.feed_overhead_mm,
        per_label_mm=preview.estimate.per_label_mm,
        notes=preview.estimate.notes,
        segments=[
            ChainedPreviewSegment(
                index=s.index, start_mm=s.start_mm, end_mm=s.end_mm, length_mm=s.length_mm
            )
            for s in preview.segments
        ],
        warnings=warnings,
    )


def _job_to_response(job: dict) -> dict:
    """Renames the DB's `preview_png` column to `thumbnail_png_b64` in the
    JSON response (the DB column name itself is unchanged -- see
    db/database.py) and base64-encodes it. The old name read as a raw PNG
    field when it was actually a base64 string; the new name says both what
    it is (a thumbnail) and its encoding, in the field name itself."""
    body = dict(job)
    png = body.pop("preview_png", None)
    body["thumbnail_png_b64"] = base64.b64encode(png).decode("ascii") if png else None
    return body


@router.get("/jobs/{job_id}")
async def get_print_job(job_id: str, db: DbDep) -> dict:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_to_response(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_print_job(job_id: str, db: DbDep, bus: BusDep) -> dict:
    """Task 2.9 carry-forward: cancel via db.cancel_job_if_queued's atomic
    CAS (single `UPDATE ... WHERE status = 'queued'`) instead of a
    get-then-update pair -- closes the race where the worker dequeues and
    marks the job "printing" between this route's read and its write (see
    that method's own docstring). The CAS itself is the source of truth:
    True -> 200 (and a job.canceled broadcast); False -> a follow-up
    get_job() only to CLASSIFY the failure for the client (404 unknown vs.
    409 naming the real current status) -- that second read is informational
    only, never re-checked against the CAS result, so a status change
    between the two reads (already "canceled" itself, say) just changes
    which status the 409 names, not whether one fires.

    jobs/worker.py's own `status != "queued"` dequeue check (see
    _process_job) stays as a second line of defense -- belt-and-suspenders,
    not load-bearing now that the CAS closes the race here.
    """
    canceled = await db.cancel_job_if_queued(job_id)
    if canceled:
        await bus.broadcast({"event": "job.canceled", "job_id": job_id})
        return {"status": "canceled"}

    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    raise HTTPException(status_code=409, detail=f"cannot cancel job in status {job['status']!r}")


@router.get("/jobs/{job_id}/stream")
async def stream_print_job(job_id: str, config: AppConfigDep) -> Response:
    path = config.data_dir / "jobs" / f"{job_id}.bin"
    if not await anyio.to_thread.run_sync(path.is_file):
        raise HTTPException(status_code=404, detail="stream not found")
    data = await anyio.to_thread.run_sync(path.read_bytes)
    return Response(content=data, media_type="application/octet-stream")
