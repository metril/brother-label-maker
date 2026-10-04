"""Task 2.9 API-level tests: POST /api/print/estimate, tape_used_mm at
creation+completion, all three chain modes end to end (byte-compare), CAS
cancel (queued->200+event, printing->409 race, unknown->404, double->409),
and job.progress broadcasts during a real (mock-mode) print.

Follows test_api_print.py's own conventions (_RecordingSocket duck-typed
EventBus client, _wait_for_terminal_job bounded polling, byte-parity against
an in-test build_job() call using the SAME strategy/tape/options the worker
uses).
"""

from __future__ import annotations

import anyio
import pytest

from labelmaker.driver.geometry import MediaFamily, dots_to_mm, find_tape
from labelmaker.driver.job import JobOptions, build_job
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.strategies import get_strategy
from labelmaker.render import rasterize, render_definition
from labelmaker.render.document import LabelDefinition
from labelmaker.render.estimate import estimate

_TAPE_24MM_TZE = find_tape(24, MediaFamily.TZE)
assert _TAPE_24MM_TZE is not None


def _text_label(text: str, **params) -> dict:
    return {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": [text], **params},
    }


def _expected_job_options(config, chain_mode: ChainMode) -> JobOptions:
    return JobOptions(
        chain_mode=chain_mode,
        margin_mm=2.0,
        auto_cut=True,
        raster_config=RasterConfig(
            bit_order=BitOrder(config.printer_bit_order),
            flip_pins=config.printer_flip_pins,
        ),
    )


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
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.events.append(data)


# =====================================================================
# 1. POST /api/print/estimate
# =====================================================================


async def test_estimate_matches_in_test_estimate_call_and_creates_no_job(app_and_client):
    app, client = app_and_client
    db = app.state.db
    before = await db.list_jobs(page_size=100)

    labels = [_text_label("ONE"), _text_label("TWO")]
    resp = await client.post(
        "/api/print/estimate",
        json={"labels": labels, "options": {"chain_mode": "chain_ff", "margin_mm": 2.0}},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["label_count"] == 2

    lengths_mm = [
        dots_to_mm(render_definition(LabelDefinition.model_validate(d)).width_px) for d in labels
    ]
    expected = estimate(lengths_mm, chain_mode="chain_ff", margin_mm=2.0)
    assert body["total_mm"] == pytest.approx(expected.total_mm)
    assert body["content_mm"] == pytest.approx(expected.content_mm)
    assert body["feed_overhead_mm"] == pytest.approx(expected.feed_overhead_mm)
    assert body["per_label_mm"] == pytest.approx(expected.per_label_mm)
    assert body["label_lengths_mm"] == pytest.approx(expected.label_lengths_mm)
    assert body["notes"] == expected.notes

    # No job was created -- history is unchanged, and nothing was enqueued.
    after = await db.list_jobs(page_size=100)
    assert after["total"] == before["total"]
    assert app.state.queue.empty()


async def test_estimate_with_serialization_expands_label_count_and_matches(app_and_client):
    app, client = app_and_client
    db = app.state.db
    before = await db.list_jobs(page_size=100)

    template = _text_label("Port {seq}")
    serialization = {"kind": "numeric", "start": 1, "step": 1, "count": 5, "pad_width": 2}

    resp = await client.post(
        "/api/print/estimate",
        json={
            "labels": [template],
            "serialization": serialization,
            "options": {"chain_mode": "cut_each", "margin_mm": 2.0},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["label_count"] == 5
    assert len(body["label_lengths_mm"]) == 5

    from labelmaker.render.serialize import Sequence, expand_definition

    seq = Sequence.model_validate(serialization)
    bound = expand_definition(template, seq)
    lengths_mm = [
        dots_to_mm(render_definition(LabelDefinition.model_validate(d)).width_px) for d in bound
    ]
    expected = estimate(lengths_mm, chain_mode="cut_each", margin_mm=2.0)
    assert body["total_mm"] == pytest.approx(expected.total_mm)

    after = await db.list_jobs(page_size=100)
    assert after["total"] == before["total"]  # still no job created


async def test_estimate_rejects_mixed_tapes_with_422(client):
    labels = [
        _text_label("ONE"),
        {**_text_label("TWO"), "tape": {"width_mm": 12, "family": "tze"}},
    ]
    resp = await client.post("/api/print/estimate", json={"labels": labels})
    assert resp.status_code == 422


async def test_estimate_rejects_invalid_label_with_422(client):
    bad_label = {**_text_label("HELLO"), "type": "does-not-exist"}
    resp = await client.post("/api/print/estimate", json={"labels": [bad_label]})
    assert resp.status_code == 422


# --- L6 (2026-08 review): margin_mm is now bounded to match the driver's --
# own clamp_margin_mm, instead of being accepted unbounded and silently
# diverging from what strategies.py actually sends the printer.


def test_router_print_margin_bounds_match_geometry_clamp():
    """Drift guard: PrintOptions.margin_mm's Field(ge=..., le=...) must stay
    numerically identical to driver/geometry.py's own MARGIN_MIN_MM/
    MARGIN_MAX_MM -- the whole point of the L6 fix is that the API-edge
    bound and the wire-path clamp can never silently diverge again."""
    from labelmaker.api.router_print import PrintOptions
    from labelmaker.driver.geometry import MARGIN_MAX_MM, MARGIN_MIN_MM

    field_info = PrintOptions.model_fields["margin_mm"]
    ge_constraint = next(
        meta.ge for meta in field_info.metadata if getattr(meta, "ge", None) is not None
    )
    le_constraint = next(
        meta.le for meta in field_info.metadata if getattr(meta, "le", None) is not None
    )
    assert ge_constraint == MARGIN_MIN_MM
    assert le_constraint == MARGIN_MAX_MM


@pytest.mark.parametrize("margin_mm", [0.0, 1.999, 127.001, 1000.0, -5.0])
async def test_estimate_rejects_out_of_range_margin_mm_with_422(client, margin_mm):
    labels = [_text_label("HELLO")]
    resp = await client.post(
        "/api/print/estimate",
        json={"labels": labels, "options": {"margin_mm": margin_mm}},
    )
    assert resp.status_code == 422


async def test_estimate_accepts_margin_mm_at_the_clamp_bounds(client):
    from labelmaker.driver.geometry import MARGIN_MAX_MM, MARGIN_MIN_MM

    labels = [_text_label("HELLO")]
    for margin_mm in (MARGIN_MIN_MM, MARGIN_MAX_MM):
        resp = await client.post(
            "/api/print/estimate",
            json={"labels": labels, "options": {"margin_mm": margin_mm}},
        )
        assert resp.status_code == 200, resp.text


# =====================================================================
# 2. tape_used_mm: set at creation, refined after completion
# =====================================================================


async def test_tape_used_mm_set_at_creation_and_refined_on_completion(app_and_client):
    app, client = app_and_client
    labels = [_text_label("HELLO"), _text_label("WORLD")]

    resp = await client.post(
        "/api/print",
        json={"labels": labels, "options": {"chain_mode": "chain_ff", "margin_mm": 2.0}},
    )
    job_id = resp.json()["job_id"]

    # Poll almost immediately: even before the job reaches a terminal
    # state, tape_used_mm should already be populated from POST-time.
    initial = await client.get(f"/api/print/jobs/{job_id}")
    assert initial.json()["tape_used_mm"] is not None

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    assert job["tape_used_mm"] is not None

    lengths_mm = [
        dots_to_mm(render_definition(LabelDefinition.model_validate(d)).width_px) for d in labels
    ]
    expected = estimate(lengths_mm, chain_mode="chain_ff", margin_mm=2.0)
    assert job["tape_used_mm"] == pytest.approx(expected.total_mm)


async def test_tape_used_mm_present_even_for_a_failed_job(app_and_client, monkeypatch):
    app, client = app_and_client

    def _raise(*args, **kwargs):
        raise RuntimeError("printer caught fire")

    monkeypatch.setattr("labelmaker.jobs.worker._print", _raise)

    resp = await client.post("/api/print", json={"labels": [_text_label("HELLO")]})
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "failed"
    # tape_used_mm was stored at creation time -- still present on a job
    # that never actually printed, per the brief's "so history shows it
    # even for failed jobs" requirement.
    assert job["tape_used_mm"] is not None


# =====================================================================
# 3. All three chain modes, end to end (byte-compare)
# =====================================================================


@pytest.mark.parametrize("chain_mode", ["cut_each", "chain_ff", "strip_marks"])
async def test_chain_mode_e2e_stream_byte_parity(app_and_client, chain_mode):
    app, client = app_and_client
    labels = [_text_label("ONE"), _text_label("TWO"), _text_label("THREE")]

    resp = await client.post(
        "/api/print", json={"labels": labels, "options": {"chain_mode": chain_mode}}
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200

    config = app.state.config
    images = [rasterize(render_definition(LabelDefinition.model_validate(d))) for d in labels]
    expected = build_job(
        images,
        _TAPE_24MM_TZE,
        get_strategy(config.printer_init_strategy),
        _expected_job_options(config, ChainMode(chain_mode)),
    )
    assert stream_resp.content == expected.data


# =====================================================================
# 4. Cancel CAS: queued->200+event, printing->409 race, unknown->404, double->409
# =====================================================================


async def test_cancel_queued_job_returns_200_and_broadcasts_job_canceled(app_and_client):
    app, client = app_and_client
    db = app.state.db

    job = await db.create_print_job(
        definition={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
    )
    job_id = job["id"]  # created directly in the db -- deliberately NOT enqueued

    recorder = _RecordingSocket()
    app.state.bus.register(recorder)

    resp = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"status": "canceled"}

    canceled_events = [e for e in recorder.events if e.get("event") == "job.canceled"]
    assert len(canceled_events) == 1
    assert canceled_events[0]["job_id"] == job_id

    got = await db.get_job(job_id)
    assert got["status"] == "canceled"


async def test_cancel_unknown_job_returns_404(client):
    resp = await client.post("/api/print/jobs/does-not-exist/cancel")
    assert resp.status_code == 404


async def test_cancel_already_canceled_job_returns_409(app_and_client):
    app, client = app_and_client
    db = app.state.db
    job = await db.create_print_job(
        definition={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
    )
    job_id = job["id"]

    first = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert first.status_code == 200

    second = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert second.status_code == 409
    assert "canceled" in second.json()["detail"]


async def test_cancel_race_job_already_printing_returns_409_naming_status(app_and_client):
    """The exact race db.cancel_job_if_queued's CAS closes: the job is
    marked "printing" (simulating the worker having already dequeued it)
    BEFORE the cancel request arrives -- the CAS must fail, and the 409
    must name the CURRENT status ("printing"), not silently succeed."""
    app, client = app_and_client
    db = app.state.db
    job = await db.create_print_job(
        definition={"labels": [_text_label("HELLO")], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
    )
    job_id = job["id"]
    await db.update_job(job_id, status="printing")

    resp = await client.post(f"/api/print/jobs/{job_id}/cancel")
    assert resp.status_code == 409
    assert "printing" in resp.json()["detail"]

    got = await db.get_job(job_id)
    assert got["status"] == "printing"  # untouched


# =====================================================================
# 5. job.progress broadcasts during a real (mock-mode) print
# =====================================================================


@pytest.mark.parametrize("app_config", [{"printer_init_strategy": "e310bt"}], indirect=True)
async def test_print_broadcasts_job_progress_events_monotonic_and_final_matches_total(
    app_and_client,
):
    # RAW compression (e310bt) makes stream size predictable regardless of
    # rendered content (every column costs a fixed 19 bytes -- no PackBits
    # collapsing of blank space) -- a wide fixed-length label comfortably
    # exceeds printer.DEFAULT_WRITE_CHUNK_SIZE (4096 bytes), guaranteeing
    # multiple job.progress broadcasts.
    app, client = app_and_client
    recorder = _RecordingSocket()
    app.state.bus.register(recorder)

    label = _text_label("X", length_mm=200.0)
    resp = await client.post("/api/print", json={"labels": [label]})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]

    progress_events = [
        e for e in recorder.events if e.get("event") == "job.progress" and e["job_id"] == job_id
    ]
    assert len(progress_events) >= 1
    assert len(progress_events) <= 11  # throttled to ~every 10%

    sent_values = [e["sent"] for e in progress_events]
    assert sent_values == sorted(sent_values)
    assert len(set(sent_values)) == len(sent_values)  # strictly increasing

    last = progress_events[-1]
    assert last["sent"] == last["total"]

    totals = {e["total"] for e in progress_events}
    assert len(totals) == 1  # total is constant across every event for one job
