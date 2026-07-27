"""POST /api/print, GET /api/print/jobs/{id}, POST /api/print/jobs/{id}/cancel,
GET /api/print/jobs/{id}/stream.

The actual render/build/print work happens in jobs/worker.py, off a queue --
this router only does cheap validation, persistence, and job-record I/O.
"""

from __future__ import annotations

import base64

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from labelmaker.api.deps import AppConfigDep, BusDep, DbDep, QueueDep, error_message
from labelmaker.driver.protocol import ChainMode
from labelmaker.render import render_definition
from labelmaker.render.document import LabelDefinition

router = APIRouter(prefix="/print", tags=["print"])


class PrintOptions(BaseModel):
    chain_mode: ChainMode = ChainMode.CUT_EACH
    margin_mm: float = 2.0
    auto_cut: bool = True


class PrintRequest(BaseModel):
    labels: list[LabelDefinition] = Field(min_length=1, max_length=100)
    options: PrintOptions = Field(default_factory=PrintOptions)


def _validate_render_side(labels: list[LabelDefinition]) -> None:
    """Cheap per-label validation: resolve each label's tape and validate its
    params against the target type's own Params model (render_definition
    does both, plus building the SVG -- still no resvg call). The expensive
    step, rasterize(), is deliberately deferred to the worker so a batch of
    100 labels doesn't rasterize before the client even gets a job id back.
    """
    for defn in labels:
        render_definition(defn)


@router.post("", status_code=202)
async def create_print_job(body: PrintRequest, db: DbDep, queue: QueueDep, bus: BusDep) -> dict:
    try:
        await anyio.to_thread.run_sync(_validate_render_side, body.labels)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    tapes = {(label.tape.width_mm, label.tape.family) for label in body.labels}
    if len(tapes) > 1:
        raise HTTPException(
            status_code=422, detail="all labels in a print job must share the same tape"
        )

    job = await db.create_print_job(
        definition=body.model_dump(mode="json"),
        label_count=len(body.labels),
        chain_mode=body.options.chain_mode.value,
    )
    job_id = job["id"]

    # Broadcast before enqueueing: guarantees job.queued reaches any
    # connected client before the worker could possibly emit job.started for
    # the same id (see test_api_ws.py's ordering assertion).
    await bus.broadcast({"event": "job.queued", "job_id": job_id})
    await queue.put(job_id)

    return {"job_id": job_id}


def _job_to_response(job: dict) -> dict:
    body = dict(job)
    png = body.pop("preview_png", None)
    body["preview_png"] = base64.b64encode(png).decode("ascii") if png else None
    return body


@router.get("/jobs/{job_id}")
async def get_print_job(job_id: str, db: DbDep) -> dict:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_to_response(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_print_job(job_id: str, db: DbDep) -> dict:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "queued":
        raise HTTPException(
            status_code=409, detail=f"cannot cancel job in status {job['status']!r}"
        )
    updated = await db.update_job(job_id, status="canceled")
    return {"status": updated["status"]}


@router.get("/jobs/{job_id}/stream")
async def stream_print_job(job_id: str, config: AppConfigDep) -> Response:
    path = config.data_dir / "jobs" / f"{job_id}.bin"
    if not await anyio.to_thread.run_sync(path.is_file):
        raise HTTPException(status_code=404, detail="stream not found")
    data = await anyio.to_thread.run_sync(path.read_bytes)
    return Response(content=data, media_type="application/octet-stream")
