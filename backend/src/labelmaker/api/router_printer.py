"""GET /api/printer/status -- always 200; connectivity/errors are reported
in the body, not via HTTP error codes, since "can't reach the printer" is an
expected, routine state for this UI (not a server error).

POST /api/printer/cut (docs/superpowers/specs/2026-08-04-feed-cut-trigger-
design.md) -- the "advance tape past the cutter and cut" manual trigger, for
when a chained job (or auto-cut off) leaves printed tape sitting in the
mechanism. Implemented as a REAL queued print_jobs row (kind='feed_cut'),
mirroring router_print.py's create_print_job path exactly -- same 202
{"job_id": ...} shape, same broadcast-before-enqueue ordering, same single
worker + USB_LOCK serialization against in-flight prints. jobs/worker.py
does the actual work (builds the blank page directly, no fake label
definitions -- see that module).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import anyio
from fastapi import APIRouter

from labelmaker.api.deps import (
    AppConfigDep,
    BusDep,
    DbDep,
    KeepaliveStatusDep,
    QueueDep,
    SettingsDep,
)
from labelmaker.api.errors import err
from labelmaker.api.schemas import (
    BridgeIdentityOut,
    JobCreatedOut,
    KeepAliveOut,
    PrinterStatusDetail,
    PrinterStatusOut,
)
from labelmaker.driver.geometry import MARGIN_MIN_MM
from labelmaker.driver.printer import get_status
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.status import PrinterStatus, StatusTimeoutError
from labelmaker.driver.transport import (
    USB_LOCK,
    MockPrinterTransport,
    PrinterNotFoundError,
    Transport,
    TransportError,
    open_real_transport,
)
from labelmaker.settings_overlay import EffectiveSettings

router = APIRouter(prefix="/printer", tags=["printer"])

# C1: how long a status check waits for USB_LOCK before giving up and
# reporting "busy" instead of queuing up behind a print job that could take
# many seconds -- this endpoint is polled every few seconds by the UI
# (usePrinterStatus.ts) and must stay snappy.
_LOCK_ACQUIRE_TIMEOUT_S = 0.5


class _StatusLockTimeout(Exception):
    """Internal signal only (never escapes this module): USB_LOCK is held by
    something else (almost always a print job, see jobs/worker.py) and
    `acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S)` gave up rather than block.
    Caught in printer_status() and turned into the busy-but-still-
    "connected" response (C1) instead of stalling the request behind
    whatever's holding the lock.
    """


def _fetch_status(open_transport: Callable[[], Transport]) -> PrinterStatus:
    """C1: shared by both the mock and USB status paths (mock doesn't need
    USB_LOCK -- nothing physical to serialize against -- but takes it anyway
    for uniformity, per the same rule as jobs/worker.py's
    _open_print_close). Acquires with a short timeout rather than blocking:
    raises _StatusLockTimeout instead of waiting out a long print job.
    """
    if not USB_LOCK.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S):
        raise _StatusLockTimeout()
    try:
        transport = open_transport()
        try:
            return get_status(transport)
        finally:
            transport.close()
    finally:
        USB_LOCK.release()


def _fetch_mock_status() -> PrinterStatus:
    return _fetch_status(MockPrinterTransport)


def _fetch_usb_status(effective: EffectiveSettings, data_dir: Path) -> PrinterStatus:
    """Real-printer status (USB or remote bridge, per `effective`)."""
    return _fetch_status(lambda: open_real_transport(effective, data_dir))


@router.get(
    "/status",
    response_model=PrinterStatusOut,
    summary="Get printer connection status",
    responses=err(500),
)
async def printer_status(
    settings: SettingsDep, keepalive_status: KeepaliveStatusDep, config: AppConfigDep
) -> PrinterStatusOut:
    """Probe the printer (USB, mock, or remote bridge) and report its state.

    Always 200: being unable to reach the printer is an expected state, so it
    is reported in the body (`connected=false`, `error`, `error_code`) rather
    than as an HTTP error. A running print job holding the USB lock yields
    `connected=true` with `error_code="printer_busy"`.
    """
    # Reads the settings overlay's EFFECTIVE printer_mode (override if one
    # is stored, else AppConfig/env), not `config.printer_mode` directly --
    # a DB override set via PUT /api/settings must be reflected here (both
    # which transport this endpoint actually probes, and the value it
    # reports) without a restart, same as everywhere else the app reads an
    # overridable setting.
    effective = settings.effective()
    printer_mode = effective.printer_mode
    if printer_mode == "mock":
        fetch = _fetch_mock_status
    else:

        def fetch() -> PrinterStatus:
            return _fetch_usb_status(effective, config.data_dir)

    # commit 6: the optional keep-awake poller's own status (jobs/
    # keepalive.py), additive on every branch below -- a shallow copy so
    # the response body is a snapshot at request time, not the same live
    # dict `run_keepalive` keeps mutating in the background.
    keep_alive = KeepAliveOut.model_validate(dict(keepalive_status))

    try:
        status = await anyio.to_thread.run_sync(fetch)
    except _StatusLockTimeout:
        return PrinterStatusOut(
            connected=True,
            printer_mode=printer_mode,
            error="printer busy (print job in progress)",
            error_code="printer_busy",
            keep_alive=keep_alive,
        )
    except (PrinterNotFoundError, TransportError) as exc:
        return PrinterStatusOut(
            connected=False,
            printer_mode=printer_mode,
            error=str(exc),
            error_code=exc.code,
            keep_alive=keep_alive,
        )
    except StatusTimeoutError as exc:
        return PrinterStatusOut(
            connected=False,
            printer_mode=printer_mode,
            error=str(exc),
            error_code="status_timeout",
            keep_alive=keep_alive,
        )
    return PrinterStatusOut(
        connected=True,
        printer_mode=printer_mode,
        status=PrinterStatusDetail.model_validate(status.to_dict()),
        keep_alive=keep_alive,
    )


@router.get(
    "/bridge-identity",
    response_model=BridgeIdentityOut,
    summary="Get this app's bridge certificate",
    responses=err(500),
)
async def bridge_identity(config: AppConfigDep) -> BridgeIdentityOut:
    """This app's PUBLIC bridge certificate (PEM) and SHA-256 fingerprint,
    for pairing on the bridge. The key is generated on first request and
    never leaves <data_dir>/bridge/. Behind the same auth gate as every
    other /api route."""
    from labelmaker.driver.bridge_identity import cert_fingerprint, ensure_identity

    def _load() -> BridgeIdentityOut:
        _key, cert = ensure_identity(config.data_dir / "bridge", "client")
        pem = cert.read_text()
        return BridgeIdentityOut(cert_pem=pem, fingerprint=cert_fingerprint(pem))

    return await anyio.to_thread.run_sync(_load)


def _feed_cut_definition() -> dict:
    """The `print_jobs.definition` placeholder for a feed-cut trigger row --
    NOT a real PrintRequest (there are no labels, see jobs/worker.py's own
    "no fake label definitions" rule): empty `labels`, plus the SAME
    options (cut_each/auto_cut=True/margin_mm=MARGIN_MIN_MM) driver.job.
    feed_cut_options() uses to actually build the job, so a human reading
    a feed-cut row's stored `definition` (GET /api/history/{id}) sees
    options consistent with what the worker really ran, not a lie.
    Returns a fresh dict every call -- this ends up json.dumps'd once by
    db.create_print_job and never mutated, but building fresh avoids any
    caller ever being handed a shared mutable module-level literal.
    """
    return {
        "labels": [],
        "options": {
            "chain_mode": ChainMode.CUT_EACH.value,
            "auto_cut": True,
            "margin_mm": MARGIN_MIN_MM,
        },
    }


async def create_feed_cut_job(db: DbDep, queue: QueueDep, bus: BusDep) -> dict:
    """Create + persist + broadcast + enqueue a feed-cut trigger job -- the
    exact create-job path both POST /api/printer/cut (below) and
    router_history.py's reprint_job (for reprinting a `kind='feed_cut'`
    history row) need. Factored out here rather than duplicated so the two
    routes can't drift apart: persist a queued print_jobs row (kind=
    'feed_cut', see _feed_cut_definition above for its `definition`/
    `chain_mode` placeholders), broadcast job.queued BEFORE enqueueing (same
    ordering guarantee router_print.create_print_job's own comment
    documents -- job.queued must reach any connected client before the
    worker could possibly emit job.started for the same id), enqueue.

    Returns the newly created job dict (not just its id) -- reprint_job
    needs nothing more than `["id"]` today, same as this module's own
    caller below, but returning the full row costs nothing extra and saves
    a future caller a re-fetch.
    """
    job = await db.create_print_job(
        definition=_feed_cut_definition(),
        label_count=0,
        chain_mode=ChainMode.CUT_EACH.value,
        kind="feed_cut",
    )
    job_id = job["id"]

    await bus.broadcast({"event": "job.queued", "job_id": job_id})
    await queue.put(job_id)

    return job


@router.post(
    "/cut",
    status_code=202,
    response_model=JobCreatedOut,
    summary="Feed tape and cut",
    responses=err(500),
)
async def feed_and_cut(db: DbDep, queue: QueueDep, bus: BusDep) -> JobCreatedOut:
    """Queue a feed-and-cut job (advance tape past the cutter and cut).

    No request body. Same id type (a uuid4 hex str) POST /api/print
    returns. Reuses the SAME db/queue/bus deps and the SAME single worker +
    USB_LOCK that serializes every other print job -- see
    create_feed_cut_job above for the actual create+persist+broadcast+
    enqueue sequence.
    """
    job = await create_feed_cut_job(db, queue, bus)
    return JobCreatedOut(job_id=job["id"])
