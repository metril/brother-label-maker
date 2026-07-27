"""GET /api/printer/status -- always 200; connectivity/errors are reported
in the body, not via HTTP error codes, since "can't reach the printer" is an
expected, routine state for this UI (not a server error)."""

from __future__ import annotations

from collections.abc import Callable

import anyio
from fastapi import APIRouter

from labelmaker.api.deps import AppConfigDep
from labelmaker.driver.printer import get_status
from labelmaker.driver.status import PrinterStatus, StatusTimeoutError
from labelmaker.driver.transport import (
    USB_LOCK,
    MockPrinterTransport,
    PrinterNotFoundError,
    PyUsbTransport,
    Transport,
    TransportError,
)

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


def _fetch_usb_status() -> PrinterStatus:
    return _fetch_status(PyUsbTransport.open)


@router.get("/status")
async def printer_status(config: AppConfigDep) -> dict:
    fetch = _fetch_mock_status if config.printer_mode == "mock" else _fetch_usb_status

    try:
        status = await anyio.to_thread.run_sync(fetch)
    except _StatusLockTimeout:
        return {
            "connected": True,
            "printer_mode": config.printer_mode,
            "status": None,
            "error": "printer busy (print job in progress)",
        }
    except (PrinterNotFoundError, StatusTimeoutError, TransportError) as exc:
        return {
            "connected": False,
            "printer_mode": config.printer_mode,
            "status": None,
            "error": str(exc),
        }
    return {
        "connected": True,
        "printer_mode": config.printer_mode,
        "status": status.to_dict(),
        "error": None,
    }
