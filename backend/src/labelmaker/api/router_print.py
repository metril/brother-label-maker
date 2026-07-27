"""POST /api/print, POST /api/print/estimate, GET /api/print/jobs/{id},
POST /api/print/jobs/{id}/cancel, GET /api/print/jobs/{id}/stream.

The actual render/build/print work happens in jobs/worker.py, off a queue --
this router only does cheap validation, persistence, and job-record I/O.
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
from labelmaker.driver.geometry import dots_to_mm
from labelmaker.driver.protocol import ChainMode
from labelmaker.render import render_definition
from labelmaker.render.document import LabelDefinition
from labelmaker.render.estimate import estimate
from labelmaker.render.serialize import Sequence, expand_definition, ordered_values

router = APIRouter(prefix="/print", tags=["print"])


class PrintOptions(BaseModel):
    chain_mode: ChainMode = ChainMode.CUT_EACH
    margin_mm: float = 2.0
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


def _validate_render_side(labels: list[LabelDefinition], data_dir: Path) -> list[float]:
    """Cheap per-label validation: resolve each label's tape and validate its
    params against the target type's own Params model (render_definition
    does both, plus building the SVG -- still no resvg call). The expensive
    step, rasterize(), is deliberately deferred to the worker so a batch of
    100 labels doesn't rasterize before the client even gets a job id back.
    `data_dir` (task 2.7) is threaded through so a "text" label's
    `icon.kind="image"` param resolves against the same uploads/ directory
    the worker will use -- an unknown image_id fails HERE, at POST time,
    not after the job is already queued.

    Returns each label's rendered length in mm (dots_to_mm of its
    RenderedLabel.width_px) -- task 2.9 reuses this SAME render pass (no
    second render_definition call) to feed render.estimate.estimate(), so
    computing a tape-usage estimate at POST time costs nothing beyond the
    validation this function was already doing.
    """
    return [dots_to_mm(render_definition(defn, data_dir=data_dir).width_px) for defn in labels]


def _validate_serialized_print(
    template: LabelDefinition, serialization: Sequence, data_dir: Path
) -> tuple[list[dict], list[float]]:
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

    Returns (bound, lengths_mm) -- lengths_mm mirrors _validate_render_side's
    own addition (task 2.9): one rendered length per expanded label, in the
    same order as `bound`, for render.estimate.estimate() to consume without
    a second render pass.
    """
    bound = expand_definition(template.model_dump(mode="json"), serialization)
    values = ordered_values(serialization)
    lengths_mm: list[float] = []
    for i, (raw, value) in enumerate(zip(bound, values, strict=True)):
        try:
            rendered = render_definition(LabelDefinition.model_validate(raw), data_dir=data_dir)
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"label {i} (sequence value {value!r}): {error_message(exc)}"
            ) from exc
        lengths_mm.append(dots_to_mm(rendered.width_px))
    return bound, lengths_mm


async def _validate_and_measure(body: PrintRequest, data_dir: Path) -> tuple[int, list[float]]:
    """Shared pre-flight: the SAME cheap validation (serialization shape,
    per-label render/params validation, single-shared-tape check) POST
    /api/print has always done at 202-time, now also returning each label's
    rendered length in mm -- shared by create_print_job (which goes on to
    create+enqueue the job) and estimate_print_job (task 2.9's POST
    /api/print/estimate, which does neither). Returns (label_count,
    label_lengths_mm), in the same order build_job will eventually receive
    the images in.
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
            bound, lengths_mm = await anyio.to_thread.run_sync(
                _validate_serialized_print, body.labels[0], body.serialization, data_dir
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=error_message(exc)) from exc
        label_count = len(bound)
    else:
        try:
            lengths_mm = await anyio.to_thread.run_sync(
                _validate_render_side, body.labels, data_dir
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=error_message(exc)) from exc
        label_count = len(body.labels)

    tapes = {(label.tape.width_mm, label.tape.family) for label in body.labels}
    if len(tapes) > 1:
        raise HTTPException(
            status_code=422, detail="all labels in a print job must share the same tape"
        )

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
