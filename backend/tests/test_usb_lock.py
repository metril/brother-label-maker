"""C1: USB_LOCK integration test -- proves jobs/worker.py's print path and
api/router_printer.py's status path are actually serialized against each
other through the SAME process-wide lock, via real production code (not a
hand-rolled substitute for it). See transport.py's USB_LOCK docstring and
test_transport.py's lower-level lock-primitive tests for the rest of the
C1 coverage.

Runs entirely in mock printer mode -- USB_LOCK is taken uniformly by both
mock and real-USB code paths (see worker.py's _open_print_close and
router_printer.py's _fetch_status), so no real hardware or PyUsbTransport
monkeypatching is needed to exercise the contention itself.
"""

from __future__ import annotations

import time

import anyio
import pytest

from labelmaker.driver.transport import USB_LOCK

_TEXT_LABEL = {
    "type": "text",
    "tape": {"width_mm": 24, "family": "tze"},
    "params": {"lines": ["HELLO"]},
}


async def test_status_reports_busy_while_worker_holds_usb_lock_then_recovers(
    app_and_client, monkeypatch
):
    """A monkeypatched slow `_print` holds USB_LOCK for `hold_s` seconds
    (simulating a slow USB write mid-job, per the brief's "fake transport
    with a slow write under the lock"). While it's held, GET
    /api/printer/status must NOT block behind it -- its own
    `acquire(timeout=0.5)` gives up and answers with the busy sentinel
    instead of queuing up behind a long print. Once the job finishes (lock
    released in _open_print_close's `finally`), status answers normally
    again.
    """
    app, client = app_and_client
    hold_s = 1.0

    def _slow_print(*args, **kwargs):
        time.sleep(hold_s)
        raise RuntimeError("simulated slow print (test double)")

    monkeypatch.setattr("labelmaker.jobs.worker._print", _slow_print)

    resp = await client.post(
        "/api/print",
        json={"labels": [_TEXT_LABEL], "options": {"chain_mode": "cut_each"}},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Wait until the worker has actually acquired USB_LOCK (dequeued the job
    # and entered _open_print_close) rather than sleeping a fixed guess --
    # bounded, not flaky. While free, a non-blocking probe acquire succeeds
    # and is immediately released; once the worker has it, the probe fails
    # and the loop exits.
    deadline = time.monotonic() + 5.0
    while USB_LOCK.acquire(timeout=0):
        USB_LOCK.release()
        if time.monotonic() > deadline:
            pytest.fail("worker never acquired USB_LOCK")
        await anyio.sleep(0.01)

    status_resp = await client.get("/api/printer/status")
    assert status_resp.status_code == 200
    assert status_resp.json() == {
        "connected": True,
        "printer_mode": "mock",
        "status": None,
        "error": "printer busy (print job in progress)",
    }

    # Wait for the job to reach a terminal state -- proves _open_print_close
    # has returned (released the lock in its `finally`) on the OTHER side
    # too, not just that our own probe above briefly saw it free.
    for _ in range(300):
        job_resp = await client.get(f"/api/print/jobs/{job_id}")
        if job_resp.json()["status"] in ("done", "failed", "canceled"):
            break
        await anyio.sleep(0.02)
    else:
        pytest.fail("job never reached a terminal state")
    assert job_resp.json()["status"] == "failed"  # _slow_print always raises

    status_resp2 = await client.get("/api/printer/status")
    assert status_resp2.status_code == 200
    body2 = status_resp2.json()
    assert body2["connected"] is True
    assert body2["error"] is None
    assert body2["status"] is not None
