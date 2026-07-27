"""Background print-job worker: one coroutine, started in `main.py`'s
lifespan, that dequeues job ids and drives each through render -> build ->
print -> persist, broadcasting lifecycle events along the way.

Every blocking driver/render call (render_definition, rasterize, preview_png,
PyUsbTransport.open/close, print_images) runs via `anyio.to_thread.run_sync`
-- this coroutine must never block the event loop the rest of the API (and
every other in-flight job's polling client) shares with it.
"""

from __future__ import annotations

import anyio
from PIL import Image

from labelmaker.driver.job import JobOptions
from labelmaker.driver.printer import PrintResult, print_images
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.strategies import InitStrategy, get_strategy
from labelmaker.driver.transport import MockPrinterTransport, PyUsbTransport, Transport
from labelmaker.render import preview_png, rasterize, render_definition
from labelmaker.render.document import LabelDefinition


async def run_worker(state) -> None:
    """Loop forever: dequeue one job id, process it, repeat. Cancelled by
    main.py's lifespan on shutdown -- cancellation while idle on
    `queue.get()` propagates immediately (nothing was dequeued, nothing to
    clean up); cancellation mid-job still runs `task_done()` via `finally`.

    `_process_job` already turns every render/build/print/persist failure
    into a job.failed record + broadcast (its own internal try/except). The
    `except Exception` here is a last-resort net for a failure OUTSIDE that
    block -- the initial `db.get_job`/mark-printing/broadcast-started calls,
    which the brief's pseudocode doesn't wrap in the per-job try either.
    Without it, one such failure would kill this coroutine entirely and
    silently strand every job queued after it for the rest of the process's
    life (never caught anywhere else -- see main.py's lifespan, which only
    awaits this task at shutdown). `except Exception` (not `BaseException`)
    deliberately still lets `asyncio.CancelledError` propagate, so shutdown
    cancellation is unaffected.
    """
    while True:
        job_id = await state.queue.get()
        try:
            await _process_job(state, job_id)
        except Exception:
            pass
        finally:
            state.queue.task_done()


async def _process_job(state, job_id: str) -> None:
    db = state.db
    bus = state.bus
    config = state.config

    job = await db.get_job(job_id)
    if job is None or job["status"] != "queued":
        # Canceled (or otherwise no longer queued) between enqueue and
        # dequeue -- the router already reflects its real status; skip
        # silently rather than resurrecting/overwriting it.
        return

    await db.update_job(job_id, status="printing")
    await bus.broadcast({"event": "job.started", "job_id": job_id})

    try:
        labels = job["definition"]["labels"]
        options = job["definition"].get("options", {})
        definitions = [LabelDefinition.model_validate(label) for label in labels]

        images = await anyio.to_thread.run_sync(_render_all, definitions)

        strategy = get_strategy(config.printer_init_strategy)
        job_options = JobOptions(
            chain_mode=ChainMode(options.get("chain_mode", ChainMode.CUT_EACH.value)),
            auto_cut=options.get("auto_cut", True),
            margin_mm=options.get("margin_mm", 2.0),
            raster_config=RasterConfig(
                bit_order=BitOrder(config.printer_bit_order),
                flip_pins=config.printer_flip_pins,
            ),
        )

        if config.printer_mode == "mock":
            transport: Transport = MockPrinterTransport()
        else:
            transport = await anyio.to_thread.run_sync(PyUsbTransport.open)

        try:
            result = await anyio.to_thread.run_sync(
                _print, images, strategy, job_options, transport
            )
        finally:
            await anyio.to_thread.run_sync(transport.close)

        jobs_dir = config.data_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        stream_path = jobs_dir / f"{job_id}.bin"
        await anyio.to_thread.run_sync(stream_path.write_bytes, result.job.data)

        thumbnail = await anyio.to_thread.run_sync(preview_png, images[0], 1)

        # tape_used_mm stays whatever it already was (None at creation) --
        # the tape-length estimator is Phase 2.9, not this task.
        await db.update_job(job_id, status="done", preview_png=thumbnail)
        await bus.broadcast({"event": "job.done", "job_id": job_id})
    except Exception as exc:
        await db.update_job(job_id, status="failed", error=str(exc))
        await bus.broadcast({"event": "job.failed", "job_id": job_id, "error": str(exc)})


def _render_all(definitions: list[LabelDefinition]) -> list[Image.Image]:
    return [rasterize(render_definition(defn)) for defn in definitions]


def _print(
    images: list[Image.Image],
    strategy: InitStrategy,
    options: JobOptions,
    transport: Transport,
) -> PrintResult:
    """The actual print step, isolated as its own module-level function so
    tests can monkeypatch it to force a deterministic failure (see
    test_api_print.py's failure-path test) without needing a real broken
    transport."""
    return print_images(images, strategy=strategy, options=options, transport=transport)
