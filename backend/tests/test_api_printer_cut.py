"""Tests for POST /api/printer/cut -- the feed-and-cut trigger job (task:
feed & cut trigger, docs/superpowers/specs/2026-08-04-feed-cut-trigger-
design.md).

Mock-mode e2e (POST -> queued -> worker -> done, the persisted stream ends
with the zero raster line + CTRL_Z -- exactly what MockPrinterTransport
captured, since jobs/worker.py writes `result.job.data` verbatim to both the
transport and the .bin file -- and the job/history rows carry kind=
'feed_cut') plus the no-printer failure path (PyUsbTransport.open
monkeypatched to raise, the same seam test_api_printer.py's own
test_printer_status_usb_mode_no_device_reports_disconnected uses, but
through the WORKER's transport this time, not router_printer's status
check): the job fails cleanly with the underlying error surfaced, never a
raw 500.
"""

from __future__ import annotations

import anyio
import httpx
import pytest

from labelmaker.config import AppConfig
from labelmaker.driver.status import REFERENCE_STATUS_BLOCK
from labelmaker.driver.transport import MockPrinterTransport, PrinterNotFoundError
from labelmaker.main import create_app


async def _wait_for_terminal_job(client, job_id: str, max_polls: int = 250, interval: float = 0.02):
    for _ in range(max_polls):
        resp = await client.get(f"/api/print/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "failed", "canceled"):
            return body
        await anyio.sleep(interval)
    pytest.fail(f"job {job_id} did not reach a terminal state within {max_polls * interval}s")


class _RecordingSocket:
    """Duck-typed EventBus client -- see test_api_print.py's identical
    helper; avoids pulling in a real WebSocket connection just to observe
    broadcasts."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.events.append(data)


async def _wait_for_event(
    recorder, event: str, job_id: str, max_polls: int = 250, interval: float = 0.02
):
    for _ in range(max_polls):
        for e in recorder.events:
            if e.get("event") == event and e.get("job_id") == job_id:
                return e
        await anyio.sleep(interval)
    pytest.fail(
        f"event {event!r} for job {job_id} was not broadcast within {max_polls * interval}s"
    )


# --- 1. Mock-mode e2e: POST -> worker -> done, stream ends zero-line+CTRL_Z --


async def test_feed_cut_mock_mode_e2e_done_stream_and_kind(app_and_client):
    app, client = app_and_client
    recorder = _RecordingSocket()
    app.state.bus.register(recorder)

    resp = await client.post("/api/printer/cut")
    assert resp.status_code == 202
    body = resp.json()
    job_id = body["job_id"]
    assert job_id

    # job.queued must already have been broadcast by the time POST returns
    # (create_print_job in router_printer.py broadcasts BEFORE enqueueing,
    # same ordering guarantee POST /api/print's own create_print_job makes).
    queued_events = [e for e in recorder.events if e.get("event") == "job.queued"]
    assert any(e["job_id"] == job_id for e in queued_events)

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    assert job["kind"] == "feed_cut"
    assert job["error"] is None
    # No thumbnail for a feed-cut trigger -- nothing meaningful to preview.
    assert job["thumbnail_png_b64"] is None

    await _wait_for_event(recorder, "job.done", job_id)

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200
    # ZERO_LINE's PACKBITS shorthand ('Z' == 0x5A) immediately followed by
    # CTRL_Z (0x1a) -- the last two bytes of any feed-cut stream (see
    # test_job_feed_cut.py's golden-byte test for the full derivation).
    # This is exactly what jobs/worker.py wrote to BOTH the transport
    # (MockPrinterTransport captured it) and this same .bin file.
    assert stream_resp.content.endswith(b"Z\x1a")

    history_resp = await client.get(f"/api/history/{job_id}")
    assert history_resp.status_code == 200
    history_body = history_resp.json()
    assert history_body["kind"] == "feed_cut"
    assert history_body["definition"]["labels"] == []

    list_resp = await client.get("/api/history")
    item = next(i for i in list_resp.json()["items"] if i["id"] == job_id)
    assert item["kind"] == "feed_cut"
    assert item["thumbnail_url"] is None


async def test_feed_cut_job_id_type_matches_post_print(app_and_client):
    # Pinned API contract: same id type POST /api/print returns -- a uuid4
    # hex str (db.create_print_job's own id scheme, shared by both routes).
    app, client = app_and_client
    print_resp = await client.post(
        "/api/print",
        json={
            "labels": [
                {
                    "type": "text",
                    "tape": {"width_mm": 24, "family": "tze"},
                    "params": {"lines": ["X"]},
                }
            ]
        },
    )
    print_job_id = print_resp.json()["job_id"]

    cut_resp = await client.post("/api/printer/cut")
    cut_job_id = cut_resp.json()["job_id"]

    assert type(cut_job_id) is type(print_job_id)  # noqa: E721
    assert isinstance(cut_job_id, str)
    assert len(cut_job_id) == len(print_job_id) == 32  # uuid4().hex


# --- 2. No-printer path: PyUsbTransport.open monkeypatched -----------------


async def test_feed_cut_usb_no_printer_job_fails_cleanly_with_error_surfaced(tmp_path, monkeypatch):
    def _raise_not_found(*args, **kwargs):
        raise PrinterNotFoundError("no USB printer found for vendor_id=0x04f9 product_id=0x224a")

    monkeypatch.setattr(
        "labelmaker.jobs.worker.PyUsbTransport.open", staticmethod(_raise_not_found)
    )

    config = AppConfig(printer_mode="usb", data_dir=tmp_path / "data")
    app = create_app(config)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            recorder = _RecordingSocket()
            app.state.bus.register(recorder)

            resp = await client.post("/api/printer/cut")
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            job = await _wait_for_terminal_job(client, job_id)
            assert job["status"] == "failed"
            assert "no USB printer found" in job["error"]
            assert job["kind"] == "feed_cut"

            failed_event = await _wait_for_event(recorder, "job.failed", job_id)
            assert "no USB printer found" in failed_event["error"]

            # No stream was ever written -- the open() failure happens before
            # any bytes reach a transport.
            stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
            assert stream_resp.status_code == 404


# --- 3. Fix wave item 4: unknown media width falls back, doesn't refuse ----


async def test_feed_cut_unknown_tape_width_falls_back_and_still_completes(
    app_and_client, monkeypatch
):
    """resolve_tape (driver/printer.py) returns `(None, ...)` when the
    printer-reported media width matches no known TapeSpec -- a normal
    print job correctly refuses that (TapeNotFoundError), but a feed-cut
    job's image is pure white (nothing to mismatch) and an operator reaching
    for this trigger most needs the manual cut to actually happen, not a
    'failed' row over a cassette that merely reads weird. jobs/worker.py's
    _open_feed_cut_close now falls back to the widest known TapeSpec for
    this path only -- proven here by overriding REFERENCE_STATUS_BLOCK's
    byte 10 (media_width_mm) to 99, a width no _TZE_ROWS/_HSE_*_ROWS entry
    in driver/geometry.py has (same override test_printer.py's own
    test_print_images_no_tape_spec_raises_tape_not_found_error uses to
    PROVE the normal print path still raises) -- and asserting the feed-cut
    job still reaches 'done', never 'failed'.
    """
    app, client = app_and_client

    unknown_width_status = bytearray(REFERENCE_STATUS_BLOCK)
    unknown_width_status[10] = 99  # byte 10: media_width_mm -- no TapeSpec matches
    unknown_width_status = bytes(unknown_width_status)

    monkeypatch.setattr(
        "labelmaker.jobs.worker.MockPrinterTransport",
        lambda: MockPrinterTransport(status_reply=unknown_width_status),
    )

    resp = await client.post("/api/printer/cut")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    assert job["kind"] == "feed_cut"
    assert job["error"] is None
    # Backfilled from the widest known TapeSpec fallback (TZE 24mm,
    # print_dots=128 -- the max across every family in driver/geometry.py's
    # tables, and the first such entry in iteration order).
    assert job["tape_width_mm"] == 24.0

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200
    assert stream_resp.content.endswith(b"Z\x1a")


# --- 4. Fix wave item 5: cancel a feed-cut job while it's still queued ------


async def test_cancel_feed_cut_job_while_queued(app_and_client):
    """Mirrors test_api_print.py's own
    test_cancel_lifecycle_and_worker_skips_already_canceled_job, for a
    `kind='feed_cut'` row instead of a print job: create the row directly
    against the db (deliberately NOT put on the queue, so the worker never
    touches it -- same "created but not enqueued" trick that test uses to
    exercise cancel-while-queued without a race against a real worker
    dequeue), cancel it via the SAME POST /api/print/jobs/{id}/cancel
    endpoint feed-cut jobs share with print jobs (router_print.py's
    cancel_job_if_queued CAS doesn't distinguish `kind` at all), and assert
    the row reads 'canceled' with no stream .bin ever written -- exactly
    what "canceled before a worker ever ran it" should look like for either
    kind of job.
    """
    app, client = app_and_client
    db = app.state.db

    job = await db.create_print_job(
        definition={"labels": [], "options": {"chain_mode": "cut_each", "auto_cut": True}},
        label_count=0,
        chain_mode="cut_each",
        kind="feed_cut",
    )
    job_id = job["id"]  # created directly in the db -- deliberately NOT enqueued

    resp = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"status": "canceled"}

    canceled = await db.get_job(job_id)
    assert canceled["status"] == "canceled"
    assert canceled["kind"] == "feed_cut"

    # A second cancel attempt is a 409 -- the CAS already moved the row off
    # 'queued', same contract print jobs get.
    resp_again = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert resp_again.status_code == 409

    # No worker ever touched this job -- no stream .bin was ever written.
    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 404
