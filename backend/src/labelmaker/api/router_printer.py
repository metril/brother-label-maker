"""GET /api/printer/status -- always 200; connectivity/errors are reported
in the body, not via HTTP error codes, since "can't reach the printer" is an
expected, routine state for this UI (not a server error)."""

from __future__ import annotations

import anyio
from fastapi import APIRouter

from labelmaker.api.deps import AppConfigDep
from labelmaker.driver.printer import get_status
from labelmaker.driver.status import PrinterStatus, StatusTimeoutError
from labelmaker.driver.transport import (
    MockPrinterTransport,
    PrinterNotFoundError,
    PyUsbTransport,
    TransportError,
)

router = APIRouter(prefix="/printer", tags=["printer"])


def _fetch_mock_status() -> PrinterStatus:
    transport = MockPrinterTransport()
    try:
        return get_status(transport)
    finally:
        transport.close()


def _fetch_usb_status() -> PrinterStatus:
    transport = PyUsbTransport.open()
    try:
        return get_status(transport)
    finally:
        transport.close()


@router.get("/status")
async def printer_status(config: AppConfigDep) -> dict:
    if config.printer_mode == "mock":
        status = await anyio.to_thread.run_sync(_fetch_mock_status)
        return {
            "connected": True,
            "printer_mode": config.printer_mode,
            "status": status.to_dict(),
            "error": None,
        }

    try:
        status = await anyio.to_thread.run_sync(_fetch_usb_status)
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
