"""Tests for the print job walking skeleton: POST /api/print, GET job, cancel,
and the stream download -- mock mode end to end, worker included.

Byte-parity against an in-test `build_job(...)` call (identical strategy/tape/
options to what the worker uses) is the core guarantee here, mirroring
test_api_preview.py's preview-parity discipline one layer down the stack.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging

import anyio
import pytest
from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import JobOptions, build_job
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.status import REFERENCE_STATUS_BLOCK
from labelmaker.driver.strategies import get_strategy
from labelmaker.driver.transport import MockPrinterTransport
from labelmaker.render import rasterize, render_definition
from labelmaker.render.document import LabelDefinition

# The mock transport always answers with REFERENCE_STATUS_BLOCK: 24mm,
# undecoded media type -> print_images assumes TZe. Every label definition
# used here targets this exact tape so the rendered image height matches
# what print_images resolves at print time (see printer.resolve_tape).
_TAPE_24MM_TZE = find_tape(24, MediaFamily.TZE)
assert _TAPE_24MM_TZE is not None


def _expected_job_options(config, chain_mode: ChainMode) -> JobOptions:
    """I4: derive the expected JobOptions FROM the config the app under
    test is actually running with (app.state.config) -- not a hardcoded
    'classic'/msb_first/False assumption -- so these byte-parity tests stay
    correct whether app_config carries its plain defaults or is
    parametrized to a non-default strategy/bit-order/flip-pins combination
    (see test_print_stream_honors_non_default_strategy_bit_order_and_flip_pins
    below)."""
    return JobOptions(
        chain_mode=chain_mode,
        margin_mm=2.0,
        auto_cut=True,
        raster_config=RasterConfig(
            bit_order=BitOrder(config.printer_bit_order),
            flip_pins=config.printer_flip_pins,
        ),
    )


def _text_label(text: str) -> dict:
    return {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": [text]},
    }


async def _wait_for_terminal_job(client, job_id: str, max_polls: int = 250, interval: float = 0.02):
    """Bounded async poll (~5s worst case): no unbounded sleeps, no flakiness
    from a fixed single wait -- returns as soon as the job leaves 'queued'/
    'printing', or fails the test if it never does."""
    for _ in range(max_polls):
        resp = await client.get(f"/api/print/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "failed", "canceled"):
            return body
        await anyio.sleep(interval)
    pytest.fail(f"job {job_id} did not reach a terminal state within {max_polls * interval}s")


class _RecordingSocket:
    """Duck-typed EventBus client: EventBus.broadcast only ever calls
    `await ws.send_json(...)`, so anything with that method works -- avoids
    pulling in a real WebSocket connection just to observe broadcasts."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.events.append(data)


# --- 1. Walking-skeleton e2e: POST -> worker -> done -> stream byte-parity ---


async def test_print_walking_skeleton_e2e_mock_mode(app_and_client):
    app, client = app_and_client

    resp = await client.post(
        "/api/print",
        json={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done"
    assert job["error"] is None

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200
    assert stream_resp.headers["content-type"] == "application/octet-stream"

    config = app.state.config
    defn = LabelDefinition.model_validate(_text_label("HELLO"))
    image = rasterize(render_definition(defn))
    expected = build_job(
        [image],
        _TAPE_24MM_TZE,
        get_strategy(config.printer_init_strategy),
        _expected_job_options(config, ChainMode.CUT_EACH),
    )
    assert stream_resp.content == expected.data

    thumb_b64 = job["preview_png"]
    assert thumb_b64 is not None
    thumb_img = Image.open(io.BytesIO(base64.b64decode(thumb_b64)))
    assert thumb_img.height == 128


# --- 2. chain_ff, two labels: byte-parity against in-test build_job ---


async def test_print_chain_ff_two_labels_stream_byte_parity(app_and_client):
    app, client = app_and_client
    labels = [_text_label("ONE"), _text_label("TWO")]

    resp = await client.post(
        "/api/print", json={"labels": labels, "options": {"chain_mode": "chain_ff"}}
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done"

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200

    config = app.state.config
    images = [rasterize(render_definition(LabelDefinition.model_validate(d))) for d in labels]
    expected = build_job(
        images,
        _TAPE_24MM_TZE,
        get_strategy(config.printer_init_strategy),
        _expected_job_options(config, ChainMode.CHAIN_FF),
    )
    assert stream_resp.content == expected.data


# --- 2b. I4: worker actually honors app_config's checkpoint fields end to end ---


@pytest.mark.parametrize(
    "app_config",
    [
        {
            "printer_init_strategy": "e310bt",
            "printer_bit_order": "lsb_first",
            "printer_flip_pins": True,
        }
    ],
    indirect=True,
)
async def test_print_stream_honors_non_default_strategy_bit_order_and_flip_pins(app_and_client):
    """I4: every other byte-parity test in this file runs against
    app_config's plain defaults (classic/msb_first/False) -- this pins that
    the worker isn't just hardcoded to those, but genuinely reads
    config.printer_init_strategy/printer_bit_order/printer_flip_pins off
    whatever AppConfig it was actually given (here, indirectly parametrized
    to e310bt/lsb_first/flip_pins=True, the checkpoint's other candidate
    combination). Byte-parity against an in-test build_job call using those
    same non-default settings, not hand-derived literals -- this is a
    config-plumbing regression test, not a protocol-correctness one (that's
    test_job.py/test_job_supplement.py's job)."""
    app, client = app_and_client
    config = app.state.config
    assert (config.printer_init_strategy, config.printer_bit_order, config.printer_flip_pins) == (
        "e310bt",
        "lsb_first",
        True,
    )

    resp = await client.post(
        "/api/print",
        json={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200

    defn = LabelDefinition.model_validate(_text_label("HELLO"))
    image = rasterize(render_definition(defn))
    expected = build_job(
        [image],
        _TAPE_24MM_TZE,
        get_strategy(config.printer_init_strategy),
        _expected_job_options(config, ChainMode.CUT_EACH),
    )
    assert stream_resp.content == expected.data


# --- 3. Cancel lifecycle + worker skip-if-not-queued ---


async def test_cancel_lifecycle_and_worker_skips_already_canceled_job(app_and_client):
    app, client = app_and_client
    db = app.state.db
    queue = app.state.queue

    job = await db.create_print_job(
        definition={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
    )
    job_id = job["id"]  # created directly in the db -- deliberately NOT enqueued yet

    resp = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"status": "canceled"}

    resp_again = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert resp_again.status_code == 409

    resp_unknown = await client.post("/api/print/jobs/does-not-exist/cancel")
    assert resp_unknown.status_code == 404

    # Now put the already-canceled id on the REAL queue: the worker must
    # dequeue it, see status != "queued", and skip it -- queue.join() is a
    # deterministic (non-polling) bounded wait for "the worker finished
    # handling everything put on the queue so far".
    await queue.put(job_id)
    await asyncio.wait_for(queue.join(), timeout=5)

    final = await db.get_job(job_id)
    assert final["status"] == "canceled"  # untouched by the worker

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 404  # worker never wrote a stream file


# --- 4. Failure path: worker's print step raises -> job failed + job.failed event ---


async def test_print_failure_marks_job_failed_and_broadcasts_job_failed(
    app_and_client, monkeypatch
):
    app, client = app_and_client

    def _raise(*args, **kwargs):
        raise RuntimeError("printer caught fire")

    monkeypatch.setattr("labelmaker.jobs.worker._print", _raise)

    recorder = _RecordingSocket()
    app.state.bus.register(recorder)

    resp = await client.post(
        "/api/print",
        json={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
    )
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "failed"
    assert "printer caught fire" in job["error"]

    failed_events = [e for e in recorder.events if e.get("event") == "job.failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["job_id"] == job_id
    assert "printer caught fire" in failed_events[0]["error"]


# --- 4b. I1: tape-mismatch preflight -- friendly message on a real cassette/design mismatch ---


async def test_print_tape_mismatch_gets_friendly_error_message(app_and_client, monkeypatch):
    # A 12mm status block (REFERENCE_STATUS_BLOCK with byte10 swapped from
    # 0x18/24 to 0x0C/12) + a 24mm-designed label: build_job resolves the
    # ACTUAL printer tape from the mock's status reply (12mm, TZe
    # print_dots=70 -- undecoded media_type_raw 0x14 falls back to TZe, see
    # printer.resolve_tape), but the rendered image was built at the
    # LABEL's declared 24mm tape (TZe print_dots=128) -- raster.py's height
    # check raises, and worker._print must turn that into the friendly,
    # mm-based message (I1), not the raw pixel-dimension one.
    app, client = app_and_client

    twelve_mm_status = bytearray(REFERENCE_STATUS_BLOCK)
    twelve_mm_status[10] = 12  # byte 10: media_width_mm
    twelve_mm_status = bytes(twelve_mm_status)

    monkeypatch.setattr(
        "labelmaker.jobs.worker.MockPrinterTransport",
        lambda: MockPrinterTransport(status_reply=twelve_mm_status),
    )

    resp = await client.post(
        "/api/print",
        json={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
    )
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "failed"
    assert job["error"] == (
        "label is designed for 24mm tape but the printer reports 12mm loaded "
        "— change the design tape or the cassette "
        "(image height 128 must equal tape.print_dots 70)"
    )


async def test_worker_survives_a_failure_outside_the_per_job_try_block(
    app_and_client, monkeypatch, caplog
):
    # _process_job's own try/except only wraps render/build/print/persist --
    # a failure in the "mark printing" update_job call right before it (per
    # the brief's pseudocode) is NOT covered by that. run_worker's outer
    # `except Exception` (see its docstring) exists precisely so this
    # doesn't kill the worker loop and strand every job queued after it --
    # prove that here: job1's very first update_job call raises, job2 (sent
    # right after) must still complete normally.
    #
    # I3: that outer except used to just `pass`, silently leaving job1 stuck
    # at "queued" forever with no trace in the logs. It now logs (asserted
    # via caplog below) and best-effort marks the job failed instead --
    # job1's SECOND update_job call (the outer except's own best-effort
    # failure-marking one) is calls["n"] == 2, which _flaky_update_job lets
    # through to the real implementation, so it actually succeeds here.
    from labelmaker.db.database import Database

    app, client = app_and_client
    original_update_job = Database.update_job
    calls = {"n": 0}

    async def _flaky_update_job(self, job_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated db hiccup on the first update_job call")
        return await original_update_job(self, job_id, **kwargs)

    monkeypatch.setattr(Database, "update_job", _flaky_update_job)
    caplog.set_level(logging.ERROR, logger="labelmaker.jobs.worker")

    resp1 = await client.post("/api/print", json={"labels": [_text_label("ONE")]})
    job1_id = resp1.json()["job_id"]

    resp2 = await client.post("/api/print", json={"labels": [_text_label("TWO")]})
    job2_id = resp2.json()["job_id"]

    job2 = await _wait_for_terminal_job(client, job2_id)
    assert job2["status"] == "done"  # proves the worker loop survived job1's crash

    # job1/job2 are processed strictly in order by the single-coroutine
    # worker loop, so by the time job2 is done, job1's outer-except handling
    # (including its own update_job call) has already fully run.
    job1 = await client.get(f"/api/print/jobs/{job1_id}")
    job1_body = job1.json()
    assert job1_body["status"] == "failed"  # no longer orphaned at "queued"
    assert job1_body["error"] == "internal: simulated db hiccup on the first update_job call"

    worker_records = [r for r in caplog.records if r.name == "labelmaker.jobs.worker"]
    assert any(
        r.levelno == logging.ERROR
        and "unhandled error for job" in r.getMessage()
        and job1_id in r.getMessage()
        for r in worker_records
    )


# --- 5. Request-level validation: mixed tapes, bad params, size bounds ---


async def test_print_rejects_mixed_tapes_with_422(client):
    labels = [
        _text_label("ONE"),
        {**_text_label("TWO"), "tape": {"width_mm": 12, "family": "tze"}},
    ]
    resp = await client.post("/api/print", json={"labels": labels})
    assert resp.status_code == 422


async def test_print_rejects_invalid_label_definition_with_422(client):
    bad_label = {**_text_label("HELLO"), "type": "does-not-exist"}
    resp = await client.post("/api/print", json={"labels": [bad_label]})
    assert resp.status_code == 422


async def test_print_rejects_empty_labels_list_with_422(client):
    resp = await client.post("/api/print", json={"labels": []})
    assert resp.status_code == 422


# --- 6. Unknown job id: 404s ---


async def test_get_unknown_job_404(client):
    resp = await client.get("/api/print/jobs/does-not-exist")
    assert resp.status_code == 404


async def test_stream_unknown_job_404(client):
    resp = await client.get("/api/print/jobs/does-not-exist/stream")
    assert resp.status_code == 404
