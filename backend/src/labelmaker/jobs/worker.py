"""Background print-job worker: one coroutine, started in `main.py`'s
lifespan, that dequeues job ids and drives each through render -> build ->
print -> persist, broadcasting lifecycle events along the way.

Every blocking driver/render call (render_definition, rasterize, preview_png,
PyUsbTransport.open/close, print_images) runs via `anyio.to_thread.run_sync`
-- this coroutine must never block the event loop the rest of the API (and
every other in-flight job's polling client) shares with it.
"""

from __future__ import annotations

import contextlib
import logging

import anyio
from PIL import Image

from labelmaker.driver.job import JobOptions
from labelmaker.driver.printer import PrintResult, get_status, print_images
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.strategies import InitStrategy, get_strategy
from labelmaker.driver.transport import (
    USB_LOCK,
    MockPrinterTransport,
    PyUsbTransport,
    Transport,
)
from labelmaker.render import preview_png, rasterize, render_definition
from labelmaker.render.document import LabelDefinition

logger = logging.getLogger(__name__)


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

    I3: this used to just `pass` -- silently leaving the job stuck at
    "queued" forever with nothing in the logs. Now it logs the failure (so
    it's observable instead of a silent stall) and makes a best-effort
    attempt to mark the job failed + broadcast job.failed, so a client
    waiting on it gets a terminal state instead of hanging. Both of those
    are wrapped in `contextlib.suppress(Exception)`: this is already the
    last-resort handler, so a SECOND failure here (e.g. the db call that
    just failed is still failing) must not blow up the worker loop either --
    it just means the job stays "queued", exactly like before this fix.
    """
    while True:
        job_id = await state.queue.get()
        try:
            await _process_job(state, job_id)
        except Exception as exc:
            logger.exception("worker: unhandled error for job %s", job_id)
            with contextlib.suppress(Exception):
                await state.db.update_job(job_id, status="failed", error=f"internal: {exc}")
            with contextlib.suppress(Exception):
                await state.bus.broadcast(
                    {"event": "job.failed", "job_id": job_id, "error": f"internal: {exc}"}
                )
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

        # I1: the design's declared tape width, needed only if the print
        # step below fails with a height mismatch against what's actually
        # loaded -- all labels in a job share one tape (enforced at
        # POST /api/print time, router_print.py), so any definition's works.
        design_tape_mm = definitions[0].tape.width_mm

        # C1: open -> print -> drain -> close as ONE synchronous call on a
        # single worker thread, entirely under USB_LOCK -- see transport.py's
        # USB_LOCK docstring. Doing this as one to_thread.run_sync call
        # (rather than separate open/print/close calls, each potentially on
        # a different thread-pool thread) keeps the acquire and release on
        # the same thread, and guarantees nothing else can open the
        # transport (another job, or router_printer's status check) for the
        # full open..close lifetime of THIS job's print.
        result = await anyio.to_thread.run_sync(
            _open_print_close, config.printer_mode, images, strategy, job_options, design_tape_mm
        )

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


def _open_print_close(
    printer_mode: str,
    images: list[Image.Image],
    strategy: InitStrategy,
    options: JobOptions,
    design_tape_mm: float,
) -> PrintResult:
    """C1: runs entirely off the event loop thread (see run_worker's
    docstring on why every blocking call here does). Acquires USB_LOCK with
    a BLOCKING wait (a queued print job should wait its turn, not give up --
    contrast router_printer._fetch_status's short `acquire(timeout=...)`),
    opens the transport, prints (which also drains post-print status -- see
    printer.print_images), closes the transport, and only then releases the
    lock -- the whole open -> print -> drain -> close sequence is one
    unbroken hold, so nothing else touching USB_LOCK (another job, or a
    status check) can interleave with any part of it.

    MockPrinterTransport doesn't need the lock (nothing physical to
    serialize against), but takes it anyway for uniformity -- every USB-
    transport-opening code path goes through the same helpers, mock or not.
    """
    USB_LOCK.acquire()
    try:
        if printer_mode == "mock":
            transport: Transport = MockPrinterTransport()
        else:
            transport = PyUsbTransport.open()
        try:
            return _print(images, strategy, options, transport, design_tape_mm)
        finally:
            transport.close()
    finally:
        USB_LOCK.release()


def _print(
    images: list[Image.Image],
    strategy: InitStrategy,
    options: JobOptions,
    transport: Transport,
    design_tape_mm: float,
) -> PrintResult:
    """The actual print step, isolated as its own module-level function so
    tests can monkeypatch it to force a deterministic failure (see
    test_api_print.py's failure-path test) without needing a real broken
    transport.

    I1: raster.py's image_to_pin_lines raises a ValueError naming raw pixel
    dimensions ("image height N must equal tape.print_dots M") when the
    rendered image (built against the LABEL's declared tape) doesn't match
    the tape build_job actually resolved from the printer's live status --
    i.e. the wrong cassette is loaded. That message is meaningless to an end
    user; caught here and re-raised with a human-readable mm-based one
    instead (original message kept, in parentheses, for anyone who does need
    the raw numbers). Re-queries the printer for its current status to name
    what's actually loaded -- safe to do here because a build_job failure
    happens before any bytes are written to `transport` (see job.py's
    _build_chained/_build_strip_marks: encode_image/image_to_pin_lines are
    the first thing either does), so the transport is still exactly as
    fresh as when print_images's own internal status request left it. If
    THAT re-query itself fails for any reason, falls back to the original
    (less friendly, but still accurate) ValueError rather than losing the
    failure entirely.
    """
    try:
        return print_images(images, strategy=strategy, options=options, transport=transport)
    except ValueError as exc:
        if "tape.print_dots" not in str(exc):
            raise
        try:
            status = get_status(transport)
        except Exception:
            # The re-query itself failed -- fall back to the original,
            # less friendly ValueError rather than losing the failure
            # entirely. `from None` suppresses chaining onto the re-query's
            # OWN exception (irrelevant to the caller; only the original
            # raster-mismatch ValueError matters here).
            raise exc from None
        raise ValueError(
            f"label is designed for {design_tape_mm:g}mm tape but the printer reports "
            f"{status.media_width_mm}mm loaded — change the design tape or the "
            f"cassette ({exc})"
        ) from exc
