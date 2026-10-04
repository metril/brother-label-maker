"""Tests for jobs/keepalive.py's `run_keepalive` loop contract -- exercised
directly (a plain `SimpleNamespace` standing in for `app.state`, real
SettingsOverlay/Database underneath, same style as test_settings_overlay.py)
rather than through the HTTP layer, which is test_api_printer.py's job.

`keepalive._fetch_usb_status` (the reused api/router_printer.py status-fetch
helper) is the monkeypatched "poll" seam for every scenario below --
`fast_intervals` additionally shrinks keepalive.py's own two sleep-duration
constants to sub-second values so a handful of loop iterations fit inside a
short, bounded `asyncio.sleep` instead of this suite waiting out real
minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from labelmaker.api.router_printer import _StatusLockTimeout
from labelmaker.config import AppConfig
from labelmaker.db.database import Database
from labelmaker.driver.transport import PrinterNotFoundError
from labelmaker.jobs import keepalive
from labelmaker.jobs.keepalive import initial_keepalive_status, run_keepalive
from labelmaker.settings_overlay import SettingsOverlay

# How long a test lets run_keepalive's background task run before cancelling
# it -- generous relative to `fast_intervals`' shrunk sleep durations (a
# couple of orders of magnitude longer) so scheduler jitter never flakes an
# "at least N polls happened" assertion.
_RUN_S = 0.15


@pytest.fixture
async def db():
    database = await Database.open(":memory:")
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def cfg(tmp_path):
    """mock printer_mode by default -- individual tests that need the
    poller to actually be ABLE to poll build their own usb-mode AppConfig
    instead (see `usb_overlay` below), same split as test_settings_overlay.py's
    own `cfg` fixture."""
    return AppConfig(printer_mode="mock", data_dir=tmp_path / "data")


@pytest.fixture
def fast_intervals(monkeypatch):
    """Shrinks both of keepalive.py's own sleep-duration constants to
    sub-second -- see that module's own docstrings on _RECHECK_INTERVAL_S/
    _SECONDS_PER_MINUTE for why they're module constants instead of inline
    literals. Without this, "enabled+usb" scenarios would need to wait a
    real 1-60 minutes (keep_awake_interval_min's own bounds) before a single
    poll happens."""
    monkeypatch.setattr(keepalive, "_RECHECK_INTERVAL_S", 0.02)
    monkeypatch.setattr(keepalive, "_SECONDS_PER_MINUTE", 0.02)


@pytest.fixture
async def usb_overlay(db, tmp_path):
    """A SettingsOverlay whose effective printer_mode is "usb" (the only
    mode run_keepalive ever actually polls in), with keep_printer_awake
    still at its DB-only default (False) -- individual tests opt into
    keep_printer_awake themselves via set_many, so a test that forgets to
    isn't accidentally "enabled" by this fixture."""
    cfg = AppConfig(printer_mode="usb", data_dir=tmp_path / "data")
    return await SettingsOverlay.create(cfg, db)


async def _run_briefly(state, seconds: float = _RUN_S) -> None:
    """Runs run_keepalive(state) as a background task for `seconds`, then
    cancels it and drains the CancelledError it raises back out -- mirrors
    main.py's own lifespan shutdown sequence for this task."""
    task = asyncio.create_task(run_keepalive(state))
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# -- initial_keepalive_status ------------------------------------------------


def test_initial_keepalive_status_shape():
    assert initial_keepalive_status(True) == {
        "enabled": True,
        "last_attempt_at": None,
        "last_result": None,
        "last_error": None,
    }
    assert initial_keepalive_status(False)["enabled"] is False


# -- disabled: zero polls -----------------------------------------------------


async def test_disabled_never_polls(db, cfg, fast_intervals, monkeypatch):
    overlay = await SettingsOverlay.create(cfg, db)  # keep_printer_awake defaults False
    calls: list[None] = []
    monkeypatch.setattr(keepalive, "_fetch_usb_status", lambda: calls.append(None))
    state = SimpleNamespace(settings=overlay, keepalive_status=initial_keepalive_status(False))

    await _run_briefly(state)

    assert calls == []
    assert state.keepalive_status["enabled"] is False
    assert state.keepalive_status["last_attempt_at"] is None
    assert state.keepalive_status["last_result"] is None


async def test_enabled_but_mock_mode_never_polls(db, tmp_path, fast_intervals, monkeypatch):
    """keep_printer_awake=True alone isn't enough -- mock mode has no idle
    timer to fight, and this poller must never open a mock transport
    either (zero USB traffic means zero traffic of ANY kind while inert)."""
    cfg = AppConfig(printer_mode="mock", data_dir=tmp_path / "data")
    overlay = await SettingsOverlay.create(cfg, db)
    await overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 1})
    calls: list[None] = []
    monkeypatch.setattr(keepalive, "_fetch_usb_status", lambda: calls.append(None))
    state = SimpleNamespace(settings=overlay, keepalive_status=initial_keepalive_status(True))

    await _run_briefly(state)

    assert calls == []


# -- enabled + usb: polls repeatedly at the configured interval -------------


async def test_enabled_usb_polls_repeatedly_at_the_configured_interval(
    usb_overlay, fast_intervals, monkeypatch
):
    await usb_overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 1})
    calls: list[None] = []
    monkeypatch.setattr(keepalive, "_fetch_usb_status", lambda: calls.append(None))
    state = SimpleNamespace(settings=usb_overlay, keepalive_status=initial_keepalive_status(True))

    await _run_briefly(state)

    assert len(calls) >= 2
    assert state.keepalive_status["enabled"] is True
    assert state.keepalive_status["last_result"] == "ok"
    assert state.keepalive_status["last_error"] is None
    assert state.keepalive_status["last_attempt_at"] is not None


# -- lock-busy: skipped_busy recorded, loop keeps going ----------------------


async def test_lock_busy_records_skipped_busy_and_keeps_looping(
    usb_overlay, fast_intervals, monkeypatch
):
    await usb_overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 1})
    calls: list[None] = []

    def _raise_busy():
        calls.append(None)
        raise _StatusLockTimeout()

    monkeypatch.setattr(keepalive, "_fetch_usb_status", _raise_busy)
    state = SimpleNamespace(settings=usb_overlay, keepalive_status=initial_keepalive_status(True))

    await _run_briefly(state)

    # "skip silently" (printing means awake) -- but still recorded, and the
    # loop must not get stuck after the first busy skip.
    assert len(calls) >= 2
    assert state.keepalive_status["last_result"] == "skipped_busy"
    assert state.keepalive_status["last_error"] is None


# -- poll raising: error recorded, loop keeps going ---------------------------


async def test_poll_error_records_error_and_keeps_looping(usb_overlay, fast_intervals, monkeypatch):
    await usb_overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 1})
    calls: list[None] = []

    def _raise_not_found():
        calls.append(None)
        raise PrinterNotFoundError("no USB printer found for vendor_id=0x04f9 product_id=0x224a")

    monkeypatch.setattr(keepalive, "_fetch_usb_status", _raise_not_found)
    state = SimpleNamespace(settings=usb_overlay, keepalive_status=initial_keepalive_status(True))

    await _run_briefly(state)

    assert len(calls) >= 2  # a failed poll must not stop the loop
    assert state.keepalive_status["last_result"] == "error"
    assert "no USB printer found" in state.keepalive_status["last_error"]


# -- toggling the setting mid-run takes effect without restart ---------------


async def test_toggling_keep_printer_awake_mid_run_takes_effect_without_restart(
    usb_overlay, fast_intervals, monkeypatch
):
    calls: list[None] = []
    monkeypatch.setattr(keepalive, "_fetch_usb_status", lambda: calls.append(None))
    state = SimpleNamespace(settings=usb_overlay, keepalive_status=initial_keepalive_status(False))

    task = asyncio.create_task(run_keepalive(state))
    try:
        await asyncio.sleep(_RUN_S)
        assert calls == []  # still off -- the same overlay instance, no override yet
        assert state.keepalive_status["enabled"] is False

        await usb_overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 1})
        await asyncio.sleep(_RUN_S)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Same task, same process -- no restart -- now polling.
    assert len(calls) >= 1
    assert state.keepalive_status["enabled"] is True
    assert state.keepalive_status["last_result"] == "ok"


# -- disabling mid-sleep skips the pending poll (L4, 2026-08 review) --------


async def test_disabling_mid_sleep_skips_the_pending_poll(usb_overlay, fast_intervals, monkeypatch):
    """The overlay is re-read AFTER the long `keep_awake_interval_min`
    sleep, so disabling `keep_printer_awake` WHILE the coroutine is asleep
    must skip the poll that would otherwise fire right after waking --
    previously the enabled branch slept the full interval and then polled
    unconditionally, firing one extra ESC i S request after being
    disabled (and leaving keepalive_status["enabled"] stale until the
    next loop top)."""
    # keep_awake_interval_min=10 * fast_intervals' _SECONDS_PER_MINUTE
    # (0.02) = a 0.2s sleep -- long enough to reliably disable partway
    # through it, well before it would wake and poll.
    await usb_overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 10})
    calls: list[None] = []
    monkeypatch.setattr(keepalive, "_fetch_usb_status", lambda: calls.append(None))
    state = SimpleNamespace(settings=usb_overlay, keepalive_status=initial_keepalive_status(True))

    task = asyncio.create_task(run_keepalive(state))
    try:
        await asyncio.sleep(0.05)
        assert calls == []  # still mid-sleep -- no poll yet
        await usb_overlay.set_many({"keep_printer_awake": False})

        # Wait past when the (now-skipped) poll would otherwise have fired.
        await asyncio.sleep(0.3)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert calls == []
    assert state.keepalive_status["enabled"] is False


# -- cancellation is clean ----------------------------------------------------


async def test_cancellation_propagates_cleanly(db, cfg, fast_intervals):
    overlay = await SettingsOverlay.create(cfg, db)
    state = SimpleNamespace(settings=overlay, keepalive_status=initial_keepalive_status(False))

    task = asyncio.create_task(run_keepalive(state))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_interval_change_applies_without_waiting_out_the_old_interval(
    usb_overlay, monkeypatch
):
    monkeypatch.setattr(keepalive, "_RECHECK_INTERVAL_S", 0.02)
    monkeypatch.setattr(keepalive, "_SECONDS_PER_MINUTE", 0.5)
    await usb_overlay.set_many({"keep_printer_awake": True, "keep_awake_interval_min": 2})
    calls: list[None] = []
    monkeypatch.setattr(keepalive, "_fetch_usb_status", lambda: calls.append(None))
    state = SimpleNamespace(settings=usb_overlay, keepalive_status=initial_keepalive_status(True))

    task = asyncio.create_task(run_keepalive(state))
    await asyncio.sleep(0.1)
    await usb_overlay.set_many({"keep_awake_interval_min": 1})  # 0.5s, vs the old 1.0s sleep
    await asyncio.sleep(0.7)  # old code: still asleep (1.0s); new: polled at ~0.5s
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert len(calls) >= 1
