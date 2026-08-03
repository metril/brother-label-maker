"""Optional keep-awake poller (commit 6): the PT-E720BT auto-powers-off
after some idle period, and no documented command changes that timer.
Brother's own official Printer Setting Tool guide (see
docs/printer-setting-tool.md) describes the idle counter as counting time
the printer "does not receive data", and receiving data resets it -- so
periodically sending the ALREADY-EXISTING status-request command (`ESC i S`,
protocol.py's `STATUS_REQUEST`, the same bytes every real status fetch
already sends via driver/status.py's `request_status()`) should, empirically,
keep the printer from powering off.

# UNVERIFIED: whether a periodic status request actually resets/prevents the
auto-power-off idle timer has never been confirmed against real hardware --
this whole module exists to test that one empirical hypothesis. Toggle
`keep_printer_awake` on (Settings page, or `PUT /api/settings
{"keep_printer_awake": true}`) and watch whether a session that would
otherwise idle-off keeps the printer awake instead.

Started/cancelled in main.py's lifespan exactly like jobs/worker.py's
run_worker: one asyncio task, `run_keepalive(app.state)`, for the life of the
process. Deliberately does NOT craft any new bytes or touch
backend/src/labelmaker/driver/ at all -- every poll reuses
api/router_printer.py's own USB-status-fetch helper (`_fetch_usb_status`:
short-timeout USB_LOCK acquire, PyUsbTransport.open -> get_status -> close,
all inside a thread), the exact same path GET /api/printer/status already
uses to probe the printer. This module never touches the print-job path
(jobs/worker.py) either -- see that module's own USB_LOCK, which this
poller's short acquire-timeout is specifically designed to lose gracefully
against (see `_poll_once`'s `_StatusLockTimeout` handling below).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import anyio

from labelmaker.api.router_printer import _fetch_usb_status, _StatusLockTimeout

logger = logging.getLogger(__name__)

# How often the loop re-checks "is keep-awake even enabled (and in usb
# mode)" while inert -- deliberately much shorter than any real
# `keep_awake_interval_min` (minimum 1 minute) so flipping the setting on
# from the Settings page takes effect promptly without a restart. A module
# constant (not an inline literal) so test_keepalive.py can monkeypatch it
# down to a sub-second value and observe several loop iterations inside a
# short, bounded wait.
_RECHECK_INTERVAL_S = 15.0

# `keep_awake_interval_min` -> seconds conversion factor, broken out as its
# own constant for the same reason as _RECHECK_INTERVAL_S above:
# test_keepalive.py monkeypatches this down so a "1 minute" interval becomes
# a sub-second sleep in tests instead of an actual real-time minute.
_SECONDS_PER_MINUTE = 60.0


def initial_keepalive_status(enabled: bool) -> dict:
    """The shape `app.state.keepalive_status` starts in at boot (main.py's
    lifespan), computed from the settings overlay's effective value BEFORE
    `run_keepalive`'s very first loop iteration has had a chance to run --
    so GET /api/printer/status has something well-formed to report even in
    the first instant after startup, not just after this task's first
    check-in."""
    return {
        "enabled": enabled,
        "last_attempt_at": None,
        "last_result": None,
        "last_error": None,
    }


async def _poll_once(state) -> None:
    """One keep-awake attempt. Reuses api/router_printer.py's own
    `_fetch_usb_status` (USB_LOCK with a short acquire timeout, then
    PyUsbTransport.open -> get_status -> close, run off the event loop via
    `anyio.to_thread.run_sync` -- identical to how GET /api/printer/status
    itself probes the printer) instead of crafting any bytes here.

    Never raises: every outcome -- a clean status reply, the lock being
    held by something else (almost always an in-flight print job, which
    itself means the printer is awake right now -- skip silently, no log,
    no special retry), or a real transport failure (printer unplugged/
    unreachable, same routine case GET /api/printer/status already handles)
    -- is recorded on `state.keepalive_status` instead of propagating.
    `except Exception` (never `BaseException`) so `asyncio.CancelledError`
    still propagates out of this function -- run_keepalive's own docstring.
    """
    now = datetime.now(UTC).isoformat()
    try:
        await anyio.to_thread.run_sync(_fetch_usb_status)
    except _StatusLockTimeout:
        state.keepalive_status.update(
            last_attempt_at=now, last_result="skipped_busy", last_error=None
        )
    except Exception as exc:
        logger.info("keepalive: poll failed: %s", exc)
        state.keepalive_status.update(last_attempt_at=now, last_result="error", last_error=str(exc))
    else:
        state.keepalive_status.update(last_attempt_at=now, last_result="ok", last_error=None)


async def run_keepalive(state) -> None:
    """Loop forever: read the settings overlay's CURRENT effective values
    every iteration (so a `PUT /api/settings` from the Settings page takes
    effect without a restart -- never more than one `_RECHECK_INTERVAL_S`
    or one poll interval stale); if `keep_printer_awake` is off, or
    `printer_mode` isn't `"usb"` (mock mode has no idle timer to fight, and
    this poller must never open a mock transport either), stay inert --
    zero USB traffic -- and just re-check again after a short wait.
    Otherwise sleep the configured `keep_awake_interval_min` and then make
    one poll attempt (`_poll_once`).

    Cancelled cleanly by main.py's lifespan on shutdown, same as
    jobs/worker.py's run_worker -- `asyncio.CancelledError` propagates
    whether it lands during one of the `anyio.sleep` calls or (via anyio's
    own cancellation forwarding) during a poll's `to_thread.run_sync` in
    flight; nothing here catches `BaseException`.
    """
    while True:
        effective = state.settings.effective()
        state.keepalive_status["enabled"] = effective.keep_printer_awake

        if not effective.keep_printer_awake or effective.printer_mode != "usb":
            await anyio.sleep(_RECHECK_INTERVAL_S)
            continue

        await anyio.sleep(effective.keep_awake_interval_min * _SECONDS_PER_MINUTE)

        # L4 (2026-08 review): re-read the overlay AFTER the long sleep --
        # keep_printer_awake (or printer_mode) may have changed while this
        # coroutine slept, and without this re-check one more open ->
        # get_status -> close cycle would fire up to keep_awake_interval_min
        # minutes after being disabled, contradicting the disabled branch's
        # own "stay inert -- zero USB traffic" contract above. Updating
        # keepalive_status["enabled"] here too means /diagnostics reflects
        # the disable immediately rather than only at the next loop top.
        effective = state.settings.effective()
        state.keepalive_status["enabled"] = effective.keep_printer_awake
        if not effective.keep_printer_awake or effective.printer_mode != "usb":
            continue

        await _poll_once(state)
