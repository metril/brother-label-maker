"""Background print-job worker: one coroutine, started in `main.py`'s
lifespan, that dequeues job ids and drives each through render -> build ->
print -> persist, broadcasting lifecycle events along the way.

Every blocking driver/render call (render_definition, rasterize, preview_png,
PyUsbTransport.open/close, print_images) -- and, for a task 2.4 serialized
job, the Sequence.model_validate/expand_definition re-expansion that
precedes rendering (see _expand_and_render) -- runs via
`anyio.to_thread.run_sync` -- this coroutine must never block the event loop
the rest of the API (and every other in-flight job's polling client) shares
with it.

A job's `kind` (0003_print_jobs_kind.sql, feed & cut trigger --
docs/superpowers/specs/2026-08-04-feed-cut-trigger-design.md) branches
_process_job between two entirely different bodies of work: 'print' (the
default, everything above/below) renders label definitions and prints them;
'feed_cut' (api/router_printer.py's POST /api/printer/cut) skips rendering
entirely and builds the blank feed-and-cut page directly (see
_open_feed_cut_close) -- no fake label definitions are ever synthesized for
it. Both share the exact same lifecycle: status="printing" -> job.started,
USB_LOCK-serialized open/print/close off the event-loop thread, the .bin
stream written to the same jobs_dir, status="done"/job.done or
status="failed"/job.failed on the way out.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path

import anyio
from PIL import Image

from labelmaker.driver.geometry import MIN_FEED_MM, TapeSpec, all_tapes, dots_to_mm
from labelmaker.driver.job import JobOptions, feed_cut_image, feed_cut_options
from labelmaker.driver.printer import (
    PrinterBusyError,
    PrintResult,
    get_status,
    print_images,
    resolve_tape,
)
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.strategies import InitStrategy, get_strategy
from labelmaker.driver.transport import (
    USB_LOCK,
    MockPrinterTransport,
    PyUsbTransport,
    Transport,
)
from labelmaker.jobs.events import EventBus
from labelmaker.render import preview_png, rasterize, render_definition
from labelmaker.render.document import LabelDefinition
from labelmaker.render.estimate import estimate
from labelmaker.render.serialize import Sequence, expand_definition

logger = logging.getLogger(__name__)

# job.progress broadcasts are throttled to firing only when `sent` crosses a
# new multiple of this many percentage points since the last broadcast (see
# _make_progress_cb) -- at most ~11 broadcasts per job (0%, 10%, ..., 100%).
_PROGRESS_BROADCAST_THRESHOLD_PERCENT = 10


def _make_progress_cb(bus: EventBus, job_id: str) -> Callable[[int, int], None]:
    """Builds the sync progress_cb threaded down into print_images (via
    _open_print_close/_print) for one job. print_images calls it from
    INSIDE the worker thread spawned by THIS job's anyio.to_thread.run_sync
    call (see _open_print_close's docstring) -- `anyio.from_thread.run()`
    is what lets a plain synchronous callback hop back onto the event loop
    to actually `await bus.broadcast(...)`; per anyio's docs this works
    without an explicit portal specifically because it's called from a
    thread anyio itself spawned via `to_thread.run_sync` (which is exactly
    _open_print_close's whole call chain, C1: open->print->drain->close as
    one synchronous call on a single worker thread).

    Throttled by percentage (task 2.9): print_images calls the raw
    progress_cb once per ~4096-byte write chunk (printer.
    DEFAULT_WRITE_CHUNK_SIZE), which could be dozens of calls for a large
    multi-label job -- broadcasting a WS event for every single one would
    flood connected clients for no UI benefit. This wrapper only actually
    broadcasts when `sent` has crossed a NEW
    _PROGRESS_BROADCAST_THRESHOLD_PERCENT-point boundary since the last
    broadcast, or unconditionally on the final chunk (sent >= total) -- so
    a job always ends on an exact 100% event even if the total isn't a
    clean multiple of the threshold.
    """
    last_percent = -1

    def _progress_cb(sent: int, total: int) -> None:
        nonlocal last_percent
        if total <= 0:
            return
        percent = min(100, (sent * 100) // total)
        is_final = sent >= total
        if not is_final and percent < last_percent + _PROGRESS_BROADCAST_THRESHOLD_PERCENT:
            return
        last_percent = percent
        anyio.from_thread.run(
            bus.broadcast,
            {"event": "job.progress", "job_id": job_id, "sent": sent, "total": total},
        )

    return _progress_cb


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
    # task 4.5: a snapshot of the DB-backed settings overlay, taken HERE on
    # the event loop -- before anything below reaches `anyio.to_thread.
    # run_sync` -- so a PUT /api/settings racing this job can only affect
    # the NEXT job, never this one mid-print (see settings_overlay.py's
    # own "Thread safety" docstring section). `config.data_dir` (not
    # overridable) still comes from `config` directly, unchanged.
    effective = state.settings.effective()

    job = await db.get_job(job_id)
    if job is None or job["status"] != "queued":
        # Canceled (or otherwise no longer queued) between enqueue and
        # dequeue -- the router already reflects its real status; skip
        # silently rather than resurrecting/overwriting it.
        return

    await db.update_job(job_id, status="printing")
    await bus.broadcast({"event": "job.started", "job_id": job_id})

    try:
        if job["kind"] == "feed_cut":
            await _process_feed_cut_job(state, job_id, effective)
            return

        definition = job["definition"]
        options = definition.get("options", {})

        images, definitions = await anyio.to_thread.run_sync(
            _expand_and_render, definition, config.data_dir
        )

        strategy = get_strategy(effective.printer_init_strategy)
        job_options = JobOptions(
            chain_mode=ChainMode(options.get("chain_mode", ChainMode.CUT_EACH.value)),
            auto_cut=options.get("auto_cut", True),
            margin_mm=options.get("margin_mm", 2.0),
            raster_config=RasterConfig(
                bit_order=BitOrder(effective.printer_bit_order),
                flip_pins=effective.printer_flip_pins,
            ),
        )

        # I1: the design's declared tape width, needed only if the print
        # step below fails with a height mismatch against what's actually
        # loaded -- all labels in a job share one tape (enforced at
        # POST /api/print time, router_print.py), so any definition's works.
        design_tape_mm = definitions[0].tape.width_mm

        # task 2.9: throttled job.progress broadcaster for THIS job (see
        # _make_progress_cb) -- built here, in the event-loop coroutine, but
        # only ever actually INVOKED from inside the worker thread
        # _open_print_close spawns below (via print_images' chunked write).
        progress_cb = _make_progress_cb(bus, job_id)

        # C1: open -> print -> drain -> close as ONE synchronous call on a
        # single worker thread, entirely under USB_LOCK -- see transport.py's
        # USB_LOCK docstring. Doing this as one to_thread.run_sync call
        # (rather than separate open/print/close calls, each potentially on
        # a different thread-pool thread) keeps the acquire and release on
        # the same thread, and guarantees nothing else can open the
        # transport (another job, or router_printer's status check) for the
        # full open..close lifetime of THIS job's print -- and is also what
        # makes _make_progress_cb's anyio.from_thread.run() usage valid (see
        # that function's docstring).
        result = await anyio.to_thread.run_sync(
            _open_print_close,
            effective.printer_mode,
            images,
            strategy,
            job_options,
            design_tape_mm,
            progress_cb,
        )

        jobs_dir = config.data_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        stream_path = jobs_dir / f"{job_id}.bin"
        await anyio.to_thread.run_sync(stream_path.write_bytes, result.job.data)

        thumbnail = await anyio.to_thread.run_sync(preview_png, images[0], 1)

        # task 2.9: refine tape_used_mm to the ACTUAL rendered lengths now
        # that the print has genuinely happened, rather than leaving
        # router_print.py's POST-time estimate (computed from the exact
        # same render_definition() pipeline, over the exact same
        # definitions -- so normally identical) as the job's final figure.
        # `img.width` is the device-pixel width AFTER rasterize() -- which
        # rasterize.py itself asserts equals each RenderedLabel.width_px
        # (see render/rasterize.py), so this doesn't require re-rendering.
        lengths_mm = [dots_to_mm(img.width) for img in images]
        tape_estimate = estimate(
            lengths_mm, chain_mode=job_options.chain_mode.value, margin_mm=job_options.margin_mm
        )

        # Task 2.8 carry-forward: backfill strategy/tape_width_mm/
        # media_raw_byte from what this print ACTUALLY used, not what the
        # request declared -- result.job.strategy_name is the strategy that
        # actually built the stream (config.printer_init_strategy, resolved
        # by _open_print_close above; mock mode still records this, since
        # it's the configured strategy either way, not something the mock
        # negotiates). result.tape/status_before come from print_images'
        # OWN tape resolution against the printer's live status (I4's
        # resolve_tape, possibly TZe-assumed) -- the same "what's actually
        # loaded" source I1's tape-mismatch error message above already
        # relies on, not the label's merely-declared tape.
        await db.update_job(
            job_id,
            status="done",
            preview_png=thumbnail,
            strategy=result.job.strategy_name,
            tape_width_mm=result.tape.nominal_mm,
            media_raw_byte=result.status_before.media_type_raw,
            tape_used_mm=tape_estimate.total_mm,
        )
        await bus.broadcast({"event": "job.done", "job_id": job_id})
    except Exception as exc:
        await db.update_job(job_id, status="failed", error=str(exc))
        await bus.broadcast({"event": "job.failed", "job_id": job_id, "error": str(exc)})


async def _process_feed_cut_job(state, job_id: str, effective) -> None:
    """The feed-cut counterpart of the tail of _process_job's print branch
    (build -> write stream -> backfill -> job.done). Called from inside
    _process_job's own try block (see there) -- any exception here
    propagates straight to that SAME except-and-mark-failed handler, so a
    feed-cut job gets the exact same status="failed"/job.failed treatment a
    print job's render/build/print failure gets, no separate handling
    needed here.

    `effective` is threaded through from _process_job rather than
    re-snapshotted here -- task 4.5's own invariant (see _process_job's
    comment on `effective`) is that the settings-overlay snapshot is taken
    ONCE, before the status="printing" update/job.started broadcast, so a
    PUT /api/settings racing this job can only ever affect the NEXT job.
    Calling state.settings.effective() again here, after those awaits,
    would quietly break that guarantee for feed-cut jobs specifically.

    Deliberately does NOT call _expand_and_render/render_definition/
    rasterize -- there is no label definition to render (job["definition"]
    is router_printer.py's own placeholder, not a real PrintRequest -- see
    that router's _feed_cut_definition) -- and does NOT set preview_png:
    the printed page is a single blank dot-wide column, nothing meaningful
    to thumbnail, so a feed-cut history row simply has no thumbnail_url
    (db.list_jobs' `has_thumbnail` already derives straight from the
    preview_png column, so this falls out for free -- see that method).
    """
    db = state.db
    bus = state.bus
    config = state.config

    strategy = get_strategy(effective.printer_init_strategy)
    progress_cb = _make_progress_cb(bus, job_id)

    # C1: same single to_thread.run_sync-wrapped open->print->drain->close
    # call _open_print_close's docstring describes for the print path --
    # see _open_feed_cut_close below for why this one ALSO has to resolve
    # the tape itself (status before image) rather than just handing
    # already-built images to print_images.
    result = await anyio.to_thread.run_sync(
        _open_feed_cut_close, effective.printer_mode, strategy, progress_cb
    )

    jobs_dir = config.data_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    stream_path = jobs_dir / f"{job_id}.bin"
    await anyio.to_thread.run_sync(stream_path.write_bytes, result.job.data)

    # M7's own convention (cli.py's _print_job_summary): tape consumed,
    # floored at MIN_FEED_MM's mechanical head-to-cutter gap -- a feed-cut
    # job's single raster line is far shorter than that gap, so this is
    # MIN_FEED_MM in practice, same as the design doc's own "~24.5mm" framing.
    tape_used_mm = max(dots_to_mm(result.job.total_raster_lines), MIN_FEED_MM)

    await db.update_job(
        job_id,
        status="done",
        strategy=result.job.strategy_name,
        tape_width_mm=result.tape.nominal_mm,
        media_raw_byte=result.status_before.media_type_raw,
        tape_used_mm=tape_used_mm,
    )
    await bus.broadcast({"event": "job.done", "job_id": job_id})


def _open_feed_cut_close(
    printer_mode: str,
    strategy: InitStrategy,
    progress_cb: Callable[[int, int], None] | None = None,
) -> PrintResult:
    """Feed-cut counterpart of _open_print_close (see that function's own
    docstring for the USB_LOCK/open/close contract, which this mirrors
    exactly -- same lock-acquire-blocking, same mock/USB transport choice,
    same finally-close/finally-release nesting).

    The one structural difference: a normal print job's image is already
    built (against the LABEL's declared tape) before _open_print_close ever
    runs -- print_images then resolves the printer's LIVE tape and either
    matches or raises a friendly mismatch error (_print's own job). A
    feed-cut job has no declared tape to render against -- job.
    feed_cut_image(tape) needs the REAL one (print_dots varies by tape
    width) to build the blank image at all, so the status request has to
    happen HERE, before print_images is even called, exactly like cli.py's
    _run_usb_print does for its own test patterns (see that function's own
    docstring for the same status-before-image-size ordering constraint).
    status_before=status is then handed to print_images so it doesn't
    re-request status a second time.

    has_error/resolve_tape are therefore checked twice in total across one
    feed-cut job when resolve_tape succeeds -- once here (to learn
    tape.print_dots before an image can exist at all), once more inside
    print_images itself (from the same status_before, structurally
    unreachable but cheap) -- the exact same double-check cli._run_usb_print
    already accepts for its own test patterns, not a new pattern introduced
    here.

    Fix wave item 4: when resolve_tape yields NO TapeSpec at all (an
    unrecognized media width -- see resolve_tape's own contract), a normal
    print job correctly refuses (TapeNotFoundError -- it has real content
    that needs the ACTUAL loaded tape's geometry to render correctly). A
    feed-cut job has no such content: feed_cut_image builds a 1-dot-wide,
    ALL-WHITE image (see that function's own docstring) -- tape geometry
    here only sizes a blank raster taller or shorter, it can never change
    what (nothing) prints. Refusing the trigger here would block an
    operator from the one thing it exists for -- a manual cut -- at exactly
    the moment they most need it: right when the cassette's status reads
    weird. So THIS path falls back to the widest known TapeSpec
    (_widest_known_tape) instead of raising, and passes it to print_images
    as `tape_override` (see that function's own docstring) so print_images'
    OWN internal resolve_tape() call -- which would otherwise hit the exact
    same "no TapeSpec" case and raise anyway -- is skipped for this one
    request. When resolve_tape DOES succeed, `tape_override` is left None
    and the double-check above still applies unchanged.
    """
    USB_LOCK.acquire()
    try:
        if printer_mode == "mock":
            transport: Transport = MockPrinterTransport()
        else:
            transport = PyUsbTransport.open()
        try:
            status = get_status(transport)
            if status.has_error:
                raise PrinterBusyError(status)
            tape, _assumed_tze = resolve_tape(status)
            fallback_tape = tape is None
            if fallback_tape:
                tape = _widest_known_tape()

            return print_images(
                [feed_cut_image(tape)],
                strategy=strategy,
                options=feed_cut_options(),
                transport=transport,
                status_before=status,
                progress_cb=progress_cb,
                tape_override=tape if fallback_tape else None,
            )
        finally:
            transport.close()
    finally:
        USB_LOCK.release()


def _widest_known_tape() -> TapeSpec:
    """Fix wave item 4: the feed-cut fallback used by _open_feed_cut_close
    above when resolve_tape can't match the printer-reported media width to
    any known TapeSpec. The widest (max print_dots) known tape can never be
    "too narrow" for whatever cassette is actually loaded -- and since
    feed_cut_image's blank image has no black pixel anywhere (see that
    function's own docstring), an oversized-relative-to-reality print_dots
    changes nothing about what lands on tape, only how tall the meaningless
    blank raster is. Never used by the normal print path, which always
    needs the ACTUAL loaded tape to render real content correctly.
    """
    return max(all_tapes(), key=lambda t: t.print_dots)


def _expand_and_render(
    definition: dict, data_dir: Path
) -> tuple[list[Image.Image], list[LabelDefinition]]:
    """Off the event-loop thread (see this module's docstring) end to end:
    validate `definition`'s labels -- re-expanding via Sequence.
    model_validate + expand_definition first when a task 2.4 serialization
    spec is present -- then render/rasterize every resulting label.
    `data_dir` (task 2.7) is passed straight through to `_render_all` so a
    "text" label's `icon.kind="image"` param can resolve its uploaded file.

    Review fix-up: the expansion step used to run directly on the event
    loop, BEFORE the to_thread.run_sync call that did the rendering (a
    max-cap, 1000-label expansion measured at ~19ms of event-loop-blocking
    work). Folding it into this SAME to_thread.run_sync call keeps ALL of
    a job's CPU-bound work off the event loop the rest of the API (and
    every other in-flight job's polling client) shares with it -- the
    guarantee this module's docstring already claims for render_definition/
    rasterize now actually covers the expansion step too.
    """
    labels = definition["labels"]
    serialization = definition.get("serialization")

    if serialization is not None:
        # task 2.4: the snapshot holds exactly ONE template label (see
        # router_print.py's create_print_job, which enforces that at POST
        # time) plus the Sequence spec, UNEXPANDED -- re-expand HERE, at
        # render time, not at POST time, so reprint is reproducible from
        # the same (template, spec) pair without ever having persisted N
        # separate label definitions.
        seq = Sequence.model_validate(serialization)
        bound = expand_definition(labels[0], seq)
        definitions = [LabelDefinition.model_validate(raw) for raw in bound]
    else:
        definitions = [LabelDefinition.model_validate(label) for label in labels]

    return _render_all(definitions, data_dir), definitions


def _render_all(definitions: list[LabelDefinition], data_dir: Path) -> list[Image.Image]:
    return [rasterize(render_definition(defn, data_dir=data_dir)) for defn in definitions]


def _open_print_close(
    printer_mode: str,
    images: list[Image.Image],
    strategy: InitStrategy,
    options: JobOptions,
    design_tape_mm: float,
    progress_cb: Callable[[int, int], None] | None = None,
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

    `progress_cb` (task 2.9) is threaded straight through to print_images --
    this whole function IS the single to_thread.run_sync call
    _make_progress_cb's docstring says is required for its
    anyio.from_thread.run() usage to work.
    """
    USB_LOCK.acquire()
    try:
        if printer_mode == "mock":
            transport: Transport = MockPrinterTransport()
        else:
            transport = PyUsbTransport.open()
        try:
            return _print(images, strategy, options, transport, design_tape_mm, progress_cb)
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
    progress_cb: Callable[[int, int], None] | None = None,
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
        return print_images(
            images,
            strategy=strategy,
            options=options,
            transport=transport,
            progress_cb=progress_cb,
        )
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
