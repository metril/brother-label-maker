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
from labelmaker.api.router_print import (
    PrintRequest,
    _job_to_response,
    _validate_render_side,
    _validate_serialized_print,
)

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

    `thumbnail_url` is null unless `status == "done"` -- jobs/worker.py's
    ONLY call that sets `preview_png` sets `status="done"` in that exact
    same update_job call (see _process_job's success path), so a job that
    hasn't reached "done" can never have a thumbnail yet. Deriving presence
    from `status` this way avoids fetching the (comparatively large) BLOB
    column for every row on every listing just to know whether it's NULL.
    """
    item = {key: job[key] for key in _LIGHT_ITEM_FIELDS}
    has_thumbnail = job["status"] == "done"
    item["thumbnail_url"] = f"/api/history/{job['id']}/thumbnail" if has_thumbnail else None
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
    POST /api/print's OWN pre-flight validation helpers
    (_validate_render_side/_validate_serialized_print) so "does this still
    render" is checked identically either way -- the only difference is the
    status code: a bad NEW request is a client error (422, POST /api/print),
    but a stored definition that no longer validates (e.g. a font or image
    it referenced was since removed) is this SERVER-side resource having
    gone stale, hence 409, not 422.
    """
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    try:
        print_request = PrintRequest.model_validate(job["definition"])
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=error_message(exc)) from exc

    try:
        if print_request.serialization is not None:
            bound = await anyio.to_thread.run_sync(
                _validate_serialized_print,
                print_request.labels[0],
                print_request.serialization,
                config.data_dir,
            )
            label_count = len(bound)
        else:
            await anyio.to_thread.run_sync(
                _validate_render_side, print_request.labels, config.data_dir
            )
            label_count = len(print_request.labels)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=error_message(exc)) from exc

    new_job = await db.create_print_job(
        definition=print_request.model_dump(mode="json"),
        label_count=label_count,
        chain_mode=print_request.options.chain_mode.value,
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
    file orphaned forever, since nothing else ever cleans it up."""
    deleted = await db.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="job not found")

    stream_path = config.data_dir / "jobs" / f"{job_id}.bin"
    if await anyio.to_thread.run_sync(stream_path.is_file):
        await anyio.to_thread.run_sync(stream_path.unlink)

    return Response(status_code=204)
