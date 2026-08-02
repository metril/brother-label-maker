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
import uuid

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
from labelmaker.render.serialize import Sequence, expand_definition

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

    thumb_b64 = job["thumbnail_png_b64"]
    assert thumb_b64 is not None
    thumb_img = Image.open(io.BytesIO(base64.b64decode(thumb_b64)))
    assert thumb_img.height == 128


# --- 1b. task 2.8 carry-forward: worker backfills strategy/tape_width_mm/ --
# media_raw_byte on a successful print -- these three columns exist in the
# schema since 0001_init.sql but were never actually populated post-print
# until now (create_print_job's own strategy=/tape_width_mm=/media_raw_byte=
# kwargs are for a DIFFERENT, not-yet-used caller shape -- the worker itself
# always created jobs via the 3-positional-arg call and left them NULL).


async def test_print_backfills_strategy_tape_width_and_media_raw_byte_on_done(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/print", json={"labels": [_text_label("HELLO")]})
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done"

    # Mock mode still records the CONFIGURED strategy (there's no real
    # printer to have negotiated one with) -- app_config's plain default is
    # "classic" (see conftest.py's _DEFAULT_APP_CONFIG_KWARGS).
    assert job["strategy"] == "classic"
    # The mock transport always answers with REFERENCE_STATUS_BLOCK: 24mm,
    # media_type_raw 0x14 (see this module's docstring/_TAPE_24MM_TZE).
    assert job["tape_width_mm"] == 24.0
    assert job["media_raw_byte"] == 0x14


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


# --- 2c. task 4.5: worker honors a DB settings-overlay override too --------


async def test_print_stream_honors_settings_overlay_override_over_app_config_default(
    app_and_client,
):
    """task 4.5: PUT /api/settings can override printer_init_strategy/
    printer_bit_order/printer_flip_pins WITHOUT restarting the app -- the
    worker (jobs/worker.py's _process_job) must read the settings overlay's
    EFFECTIVE snapshot, not `app.state.config` directly. Byte-parity
    against an in-test build_job call using the OVERRIDDEN values (not
    app_config's own plain classic/msb_first/False defaults) proves the
    override actually reached the print pipeline -- mirrors
    test_print_stream_honors_non_default_strategy_bit_order_and_flip_pins
    above, but via the DB overlay instead of AppConfig construction."""
    app, client = app_and_client
    config = app.state.config
    assert (config.printer_init_strategy, config.printer_bit_order, config.printer_flip_pins) == (
        "classic",
        "msb_first",
        False,
    )

    put_resp = await client.put(
        "/api/settings",
        json={
            "printer_init_strategy": "e310bt",
            "printer_bit_order": "lsb_first",
            "printer_flip_pins": True,
        },
    )
    assert put_resp.status_code == 200

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
        get_strategy("e310bt"),
        JobOptions(
            chain_mode=ChainMode.CUT_EACH,
            margin_mm=2.0,
            auto_cut=True,
            raster_config=RasterConfig(bit_order=BitOrder("lsb_first"), flip_pins=True),
        ),
    )
    assert stream_resp.content == expected.data

    # app.state.config itself is untouched by the override -- only the
    # settings overlay changed; AppConfig stays the env-derived source of
    # truth the overlay layers on top of.
    assert (config.printer_init_strategy, config.printer_bit_order, config.printer_flip_pins) == (
        "classic",
        "msb_first",
        False,
    )


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


# --- 5b. task 2.4: serialization -- template + Sequence, server-side expansion ---


def _serial_template(text: str = "Port {seq}") -> dict:
    return {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": [text]},
    }


async def test_print_with_serialization_e2e_label_count_and_stream_byte_parity(app_and_client):
    app, client = app_and_client
    serialization = {"kind": "list", "values": ["A", "B", "C"], "copies_per_value": 1}

    resp = await client.post(
        "/api/print",
        json={
            "labels": [_serial_template()],
            "serialization": serialization,
            "options": {"chain_mode": "cut_each"},
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    # label_count reflects the EXPANDED total (3 distinct x 1 copy), not
    # the single template entry `labels` was posted with.
    assert job["label_count"] == 3

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200

    # Byte-parity against an in-test expand_definition() + render/rasterize
    # + build_job() pipeline -- identical to what jobs/worker.py does, and
    # to this file's own non-serialized parity tests (see module docstring)
    # -- this also pins expand_definition's COPIES_ADJACENT/default
    # collation ORDER, since build_job concatenates images in list order.
    config = app.state.config
    seq = Sequence.model_validate(serialization)
    bound = expand_definition(_serial_template(), seq)
    images = [rasterize(render_definition(LabelDefinition.model_validate(d))) for d in bound]
    expected = build_job(
        images,
        _TAPE_24MM_TZE,
        get_strategy(config.printer_init_strategy),
        _expected_job_options(config, ChainMode.CUT_EACH),
    )
    assert stream_resp.content == expected.data

    # The DB snapshot stores the TEMPLATE + spec UNEXPANDED (task 2.4's
    # DECIDED contract), not the 3 already-expanded labels.
    job_resp = await client.get(f"/api/print/jobs/{job_id}")
    definition = job_resp.json()["definition"]
    assert len(definition["labels"]) == 1
    assert definition["labels"][0]["params"]["lines"] == ["Port {seq}"]
    assert definition["serialization"]["kind"] == "list"
    assert definition["serialization"]["values"] == ["A", "B", "C"]


async def test_print_serialization_requires_exactly_one_template_label(client):
    resp = await client.post(
        "/api/print",
        json={
            "labels": [_text_label("ONE"), _text_label("TWO")],
            "serialization": {"kind": "list", "values": ["A", "B"]},
        },
    )
    assert resp.status_code == 422


async def test_print_serialization_alpha_underflow_rejected_before_queueing(client, app_and_client):
    # A sequence that can't actually expand (ALPHA stepping below 'A') must
    # fail the POST itself with a 422 -- never reach "queued" at all, the
    # same "cheap validation happens before 202" guarantee
    # _validate_render_side gives the non-serialized path.
    app, _ = app_and_client
    db = app.state.db
    before = await db.list_jobs(page_size=100)  # page_size is capped at 100 (task 2.8)

    resp = await client.post(
        "/api/print",
        json={
            "labels": [_serial_template("{seq}")],
            "serialization": {"kind": "alpha", "alpha_start": "A", "step": -1, "count": 2},
        },
    )
    assert resp.status_code == 422

    after = await db.list_jobs(page_size=100)
    assert after["total"] == before["total"]  # nothing was ever persisted


async def test_print_serialization_csv_unknown_column_rejected_before_queueing(client):
    resp = await client.post(
        "/api/print",
        json={
            "labels": [_serial_template("{csv.missing}")],
            "serialization": {"kind": "csv", "rows": [{"port": "1"}]},
        },
    )
    assert resp.status_code == 422
    assert "missing" in resp.json()["detail"]


async def test_print_serialization_pre_flight_422_names_the_failing_label_and_value(client):
    # Review fix-up: a run can be up to 1000 labels -- a bare
    # render_definition() error ("each line must be <= 200 chars, got 250")
    # is useless without saying WHICH of them broke. text_label.py's
    # TextLabelParams caps a line at 200 chars; only the THIRD value here
    # (index 2) is over that, so the 422 must name index 2 and that exact
    # value, not just repeat the underlying validation message.
    too_long_value = "X" * 250
    resp = await client.post(
        "/api/print",
        json={
            "labels": [_serial_template("{seq}")],
            "serialization": {"kind": "list", "values": ["A", "B", too_long_value]},
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "label 2" in detail
    assert too_long_value in detail
    assert "200" in detail  # the underlying TextLabelParams message survives intact


# --- 6. Unknown job id: 404s ---


async def test_get_unknown_job_404(client):
    resp = await client.get("/api/print/jobs/does-not-exist")
    assert resp.status_code == 404


async def test_stream_unknown_job_404(client):
    resp = await client.get("/api/print/jobs/does-not-exist/stream")
    assert resp.status_code == 404


# --- 7. task 2.7: print job for a "text" label with an image icon ----------
# End-to-end proof that jobs/worker.py's _expand_and_render/_render_all
# thread the app's real data_dir through to TextLabelRenderer.render the
# same way router_labels.py's preview path does (test_api_preview.py) --
# an uploaded image icon must resolve at PRINT time too, off the queue,
# not just at preview time.


async def test_print_text_with_image_icon_completes_and_uses_uploaded_image(client):
    upload = await client.post(
        "/api/images",
        files={"file": ("logo.png", io.BytesIO(_icon_png_bytes()), "image/png")},
    )
    assert upload.status_code == 201
    image_id = upload.json()["image_id"]

    label = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["CAM-3"], "icon": {"kind": "image", "image_id": image_id}},
    }
    resp = await client.post("/api/print", json={"labels": [label]})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done"
    assert job["error"] is None


async def test_print_unknown_image_icon_rejected_before_queueing(client, app_and_client):
    app, _ = app_and_client
    db = app.state.db
    before = await db.list_jobs(page_size=100)  # page_size is capped at 100 (task 2.8)

    unknown_id = uuid.uuid4().hex  # well-formed (matches IMAGE_ID_RE), never uploaded
    label = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["CAM-3"], "icon": {"kind": "image", "image_id": unknown_id}},
    }
    resp = await client.post("/api/print", json={"labels": [label]})
    assert resp.status_code == 422
    assert "unknown image_id" in resp.json()["detail"]

    after = await db.list_jobs(page_size=100)
    assert after["total"] == before["total"]  # nothing was ever persisted


# --- SECURITY (coordinator-review-caught CRITICAL bug): a malformed/path- --
# escaping image_id must 422 BEFORE a job is ever queued, never 200/202
# with an arbitrary local file printed, never a raw 500. See
# render/images.py's module docstring and test_images.py's section 7 for
# the full writeup; pinned here through the REAL /api/print endpoint.


@pytest.mark.parametrize(
    "malicious_image_id",
    ["/etc/passwd", "../../etc/passwd", "..", "a/b"],
)
async def test_print_with_malicious_image_icon_id_rejected_before_queueing(
    client, app_and_client, malicious_image_id
):
    app, _ = app_and_client
    db = app.state.db
    before = await db.list_jobs(page_size=100)  # page_size is capped at 100 (task 2.8)

    label = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["X"], "icon": {"kind": "image", "image_id": malicious_image_id}},
    }
    resp = await client.post("/api/print", json={"labels": [label]})
    assert resp.status_code == 422
    assert "invalid image_id" in resp.json()["detail"]

    after = await db.list_jobs(page_size=100)
    assert after["total"] == before["total"]  # nothing was ever persisted


def _icon_png_bytes(width: int = 20, height: int = 20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buf, format="PNG")
    return buf.getvalue()
