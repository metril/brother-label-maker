"""GET /api/history (+ /{id}, /{id}/thumbnail), POST /api/history/{id}/reprint,
DELETE /api/history/{id} (task 2.8).

Print-job history, one layer up from router_print.py's job-lifecycle
endpoints (POST /api/print, GET/cancel/stream of a single job by id): this
router adds LISTING (paginated, filterable) and REPRINT on top of the same
`print_jobs` rows router_print.py already creates/updates.

Phase-1 review's "split the job resource" note: GET /api/history's list
items are a deliberately light shape (id/created_at/status/error/
label_count/chain_mode/strategy/tape_width_mm/tape_used_mm/thumbnail_url) --
never the full `definition` (can be sizeable -- up to 1000 expanded labels'
worth for a serialized run) and never inline base64 thumbnail bytes (a page
of N items would otherwise ship N decoded PNGs whether or not the caller is
even displaying them). GET /api/history/{id} is the full resource instead
(same shape GET /api/print/jobs/{id} already returns) for when a caller
actually wants the definition.
"""

from __future__ import annotations

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import ValidationError

from labelmaker.api.deps import AppConfigDep, BusDep, DbDep, QueueDep, error_message
from labelmaker.api.router_print import PrintRequest, _job_to_response, _validate_and_measure
from labelmaker.render.estimate import estimate

router = APIRouter(prefix="/history", tags=["history"])

_LIGHT_ITEM_FIELDS = (
    "id",
    "created_at",
    "status",
    "error",
    "label_count",
    "chain_mode",
    "strategy",
    "tape_width_mm",
    "tape_used_mm",
)


def _to_light_item(job: dict) -> dict:
    """The list shape: `_LIGHT_ITEM_FIELDS` verbatim, plus a `thumbnail_url`
    pointing at GET /api/history/{id}/thumbnail instead of inline bytes.

    `thumbnail_url` is null unless `job["has_thumbnail"]` -- db.list_jobs
    (review fix-up) derives that directly from `preview_png IS NOT NULL` in
    SQL, rather than this router inferring it from `status == "done"`. The
    two happen to coincide today (jobs/worker.py's only call that sets
    `preview_png` also sets `status="done"`, in the same update_job call),
    but deriving it from the real column removes the coupling instead of
    relying on that never drifting.
    """
    item = {key: job[key] for key in _LIGHT_ITEM_FIELDS}
    item["thumbnail_url"] = (
        f"/api/history/{job['id']}/thumbnail" if job["has_thumbnail"] else None
    )
    return item


@router.get("")
async def list_history(
    db: DbDep,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    q: str | None = None,
) -> dict:
    try:
        result = await db.list_jobs(page=page, page_size=page_size, status=status, q=q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    return {
        "items": [_to_light_item(job) for job in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
        "total": result["total"],
    }


@router.get("/{job_id}")
async def get_history_job(job_id: str, db: DbDep) -> dict:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_to_response(job)  # same full shape as GET /api/print/jobs/{id}


@router.get("/{job_id}/thumbnail")
async def get_history_thumbnail(job_id: str, db: DbDep) -> Response:
    job = await db.get_job(job_id)
    if job is None or not job.get("preview_png"):
        raise HTTPException(status_code=404, detail="thumbnail not found")
    return Response(content=job["preview_png"], media_type="image/png")


@router.post("/{job_id}/reprint", status_code=202)
async def reprint_job(
    job_id: str, db: DbDep, queue: QueueDep, bus: BusDep, config: AppConfigDep
) -> dict:
    """Re-renders from the stored `definition` snapshot (template +
    serialization block, if present -- see router_print.py's
    create_print_job docstring on why that snapshot is stored UNEXPANDED)
    and enqueues a brand NEW job: new id, its own definition copy. Reuses
    POST /api/print's OWN pre-flight validation+measurement helper
    (_validate_and_measure) so "does this still render" -- and the rendered
    lengths tape_used_mm is estimated from -- are computed identically
    either way -- the only difference is the status code: a bad NEW
    request is a client error (422, POST /api/print), but a stored
    definition that no longer validates (e.g. a font or image it
    referenced was since removed) is this SERVER-side resource having gone
    stale, hence 409, not 422 -- so a 422 raised by _validate_and_measure is
    caught and re-raised as 409 here, its detail message unchanged.
    """
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    try:
        print_request = PrintRequest.model_validate(job["definition"])
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=error_message(exc)) from exc

    try:
        label_count, lengths_mm = await _validate_and_measure(print_request, config.data_dir)
    except HTTPException as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc

    # task 2.9: same POST-time tape_used_mm estimate POST /api/print stores
    # (router_print.py's create_print_job) -- reprint is otherwise
    # indistinguishable from a fresh POST /api/print of the same snapshot.
    tape_estimate = estimate(
        lengths_mm,
        chain_mode=print_request.options.chain_mode.value,
        margin_mm=print_request.options.margin_mm,
    )

    new_job = await db.create_print_job(
        definition=print_request.model_dump(mode="json"),
        label_count=label_count,
        chain_mode=print_request.options.chain_mode.value,
        tape_used_mm=tape_estimate.total_mm,
    )
    new_job_id = new_job["id"]

    # Same queued-before-enqueued ordering guarantee as POST /api/print
    # (see that handler's own comment) -- job.queued must reach any
    # connected client before the worker could possibly emit job.started.
    await bus.broadcast({"event": "job.queued", "job_id": new_job_id})
    await queue.put(new_job_id)

    return {"job_id": new_job_id}


@router.delete("/{job_id}", status_code=204)
async def delete_history_job(job_id: str, db: DbDep, config: AppConfigDep) -> Response:
    """204 removes the print_jobs row (which also disposes of the
    `preview_png` thumbnail -- it's a BLOB column on that same row, not a
    separate file) AND the on-disk stream .bin file jobs/worker.py wrote
    (data_dir/jobs/{id}.bin) -- deleting the row alone would leave that
    file orphaned forever, since nothing else ever cleans it up.

    Review L2: db.delete_job is now a status-guarded CAS that refuses to
    remove a job the worker has queued or is currently printing (deleting
    it mid-print would orphan the .bin file worker.py writes only AFTER
    the print completes, since nothing else ever cleans that file up
    either). A False result is classified the same way
    router_print.py's cancel_job endpoint classifies its own CAS miss: a
    follow-up get_job() distinguishes "unknown id" (404) from "known but
    queued/printing" (409).

    Review L2 follow-up: the two non-terminal statuses get DIFFERENT 409
    details rather than one detail naming an action that isn't always
    true. 'queued' really can be canceled (POST .../cancel,
    cancel_job_if_queued's CAS matches 'queued' only), so that detail
    still says so. 'printing' cannot -- there is no cancel-a-printing-job
    operation anywhere in this API -- so telling that caller to "cancel it
    first" would be advice they cannot follow. That status instead gets an
    honest wait-it-out message, plus a pointer at the startup
    reconciliation (Database.fail_orphaned_jobs, called from main.py's
    lifespan) that exists precisely so a job stuck at 'printing' by a
    crash/restart doesn't stay undeletable forever -- it flips to 'failed'
    on the next boot and becomes deletable then.
    """
    deleted = await db.delete_job(job_id)
    if not deleted:
        job = await db.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job["status"] == "queued":
            detail = "job is 'queued'; cancel it first"
        else:
            detail = (
                "job is 'printing'; wait for it to finish "
                "(interrupted jobs are marked failed at restart)"
            )
        raise HTTPException(status_code=409, detail=detail)

    stream_path = config.data_dir / "jobs" / f"{job_id}.bin"
    if await anyio.to_thread.run_sync(stream_path.is_file):
        await anyio.to_thread.run_sync(stream_path.unlink)

    return Response(status_code=204)
