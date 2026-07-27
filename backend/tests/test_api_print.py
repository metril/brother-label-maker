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

import anyio
import pytest
from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import JobOptions, build_job
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import RasterConfig
from labelmaker.driver.strategies import get_strategy
from labelmaker.render import rasterize, render_definition
from labelmaker.render.document import LabelDefinition

# The mock transport always answers with REFERENCE_STATUS_BLOCK: 24mm,
# undecoded media type -> print_images assumes TZe. Every label definition
# used here targets this exact tape so the rendered image height matches
# what print_images resolves at print time (see printer.resolve_tape).
_TAPE_24MM_TZE = find_tape(24, MediaFamily.TZE)
assert _TAPE_24MM_TZE is not None

_DEFAULT_JOB_OPTIONS_KWARGS = {
    "margin_mm": 2.0,
    "auto_cut": True,
    "raster_config": RasterConfig(),
}


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

    defn = LabelDefinition.model_validate(_text_label("HELLO"))
    image = rasterize(render_definition(defn))
    expected = build_job(
        [image],
        _TAPE_24MM_TZE,
        get_strategy("classic"),
        JobOptions(chain_mode=ChainMode.CUT_EACH, **_DEFAULT_JOB_OPTIONS_KWARGS),
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

    images = [rasterize(render_definition(LabelDefinition.model_validate(d))) for d in labels]
    expected = build_job(
        images,
        _TAPE_24MM_TZE,
        get_strategy("classic"),
        JobOptions(chain_mode=ChainMode.CHAIN_FF, **_DEFAULT_JOB_OPTIONS_KWARGS),
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


async def test_worker_survives_a_failure_outside_the_per_job_try_block(
    app_and_client, monkeypatch
):
    # _process_job's own try/except only wraps render/build/print/persist --
    # a failure in the "mark printing" update_job call right before it (per
    # the brief's pseudocode) is NOT covered by that. run_worker's outer
    # `except Exception: pass` (see its docstring) exists precisely so this
    # doesn't kill the worker loop and strand every job queued after it --
    # prove that here: job1's very first update_job call raises, job2 (sent
    # right after) must still complete normally.
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

    resp1 = await client.post("/api/print", json={"labels": [_text_label("ONE")]})
    job1_id = resp1.json()["job_id"]

    resp2 = await client.post("/api/print", json={"labels": [_text_label("TWO")]})
    job2_id = resp2.json()["job_id"]

    job2 = await _wait_for_terminal_job(client, job2_id)
    assert job2["status"] == "done"  # proves the worker loop survived job1's crash

    job1 = await client.get(f"/api/print/jobs/{job1_id}")
    assert job1.json()["status"] == "queued"  # orphaned, as documented -- never resurrected


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
