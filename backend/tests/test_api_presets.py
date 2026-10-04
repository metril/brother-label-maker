"""Tests for POST/GET/PUT/DELETE /api/presets and POST /api/presets/{id}/print
(task 2.8).

A preset's `definition` is the label TYPE's own params dict (e.g. "text"'s
TextLabelParams shape: `{"lines": [...], ...}`) -- NOT a full LabelDefinition
(type+tape+params). `label_type` and `tape_width_mm`/`tape_family` are
separate, independently-settable columns: `label_type` says which renderer's
Params `definition` is validated against, and `tape_width_mm` (nullable =
"any tape") / `tape_family` (NOT nullable, "tze" default --
0002_preset_tape_family.sql) are validated together against the real tape
table at create/update time. POST .../print builds a real Tape from those
two when the request body doesn't supply an explicit `tape` override (the
only way to print an "any tape" preset, or a different tape than the one
saved).
"""

from __future__ import annotations

import asyncio

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import JobOptions, build_job
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.status import REFERENCE_STATUS_BLOCK, MediaType
from labelmaker.driver.strategies import get_strategy
from labelmaker.driver.transport import MockPrinterTransport
from labelmaker.render import rasterize, render_definition
from labelmaker.render.document import LabelDefinition

_TAPE_24MM_TZE = find_tape(24, MediaFamily.TZE)
assert _TAPE_24MM_TZE is not None


async def _wait_for_terminal_job(client, job_id: str, max_polls: int = 250, interval: float = 0.02):
    for _ in range(max_polls):
        resp = await client.get(f"/api/print/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "failed", "canceled"):
            return body
        await asyncio.sleep(interval)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _text_definition(text: str = "HELLO") -> dict:
    return {"lines": [text]}


def _expected_job_options(config) -> JobOptions:
    return JobOptions(
        chain_mode=ChainMode.CUT_EACH,
        margin_mm=2.0,
        auto_cut=True,
        raster_config=RasterConfig(
            bit_order=BitOrder(config.printer_bit_order),
            flip_pins=config.printer_flip_pins,
        ),
    )


# --- 1. Create ------------------------------------------------------------


async def test_create_preset_returns_201_with_row(client):
    resp = await client.post(
        "/api/presets",
        json={
            "name": "Port Label",
            "label_type": "text",
            "definition": _text_definition("PORT-01"),
            "tape_width_mm": 24,
            "favorite": True,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["name"] == "Port Label"
    assert body["label_type"] == "text"
    assert body["definition"] == _text_definition("PORT-01")
    assert body["tape_width_mm"] == 24
    assert body["favorite"] is True
    assert body["created_at"] == body["updated_at"]


async def test_create_preset_minimal_body_defaults(client):
    resp = await client.post(
        "/api/presets",
        json={"name": "Minimal", "label_type": "text", "definition": _text_definition()},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tape_width_mm"] is None
    assert body["tape_family"] == "tze"
    assert body["favorite"] is False


async def test_create_preset_rejects_tape_width_not_in_family(client):
    # review fix-up: validated against the real tape table at create time,
    # not just accepted and left to surprise POST .../print later. 100mm
    # doesn't exist in ANY family (max TZE nominal is 24mm).
    resp = await client.post(
        "/api/presets",
        json={
            "name": "Bad tape",
            "label_type": "text",
            "definition": _text_definition(),
            "tape_width_mm": 100,
        },
    )
    assert resp.status_code == 422

    # 9.0mm IS a real width -- but only for hse_3_1, not the default "tze".
    resp = await client.post(
        "/api/presets",
        json={
            "name": "Wrong family for width",
            "label_type": "text",
            "definition": _text_definition(),
            "tape_width_mm": 9.0,
            "tape_family": "hse_2_1",
        },
    )
    assert resp.status_code == 422

    ok = await client.post(
        "/api/presets",
        json={
            "name": "Right family for width",
            "label_type": "text",
            "definition": _text_definition(),
            "tape_width_mm": 9.0,
            "tape_family": "hse_3_1",
        },
    )
    assert ok.status_code == 201
    assert ok.json()["tape_family"] == "hse_3_1"


async def test_create_preset_rejects_name_out_of_bounds(client):
    resp = await client.post(
        "/api/presets",
        json={"name": "", "label_type": "text", "definition": _text_definition()},
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/presets",
        json={"name": "x" * 81, "label_type": "text", "definition": _text_definition()},
    )
    assert resp.status_code == 422


async def test_create_preset_definition_not_matching_label_type_422(client):
    resp = await client.post(
        "/api/presets",
        json={
            "name": "Bad",
            "label_type": "text",
            "definition": {"lines": "not-a-list"},  # TextLabelParams.lines wants list[str]
        },
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/presets",
        json={"name": "Bad type", "label_type": "does-not-exist", "definition": {}},
    )
    assert resp.status_code == 422


# --- 2. Read / list ---------------------------------------------------------


async def test_get_preset_by_id_and_404_unknown(client):
    resp = await client.post(
        "/api/presets",
        json={"name": "P", "label_type": "text", "definition": _text_definition()},
    )
    preset_id = resp.json()["id"]

    got = await client.get(f"/api/presets/{preset_id}")
    assert got.status_code == 200
    assert got.json()["id"] == preset_id

    missing = await client.get("/api/presets/does-not-exist")
    assert missing.status_code == 404


async def test_list_presets_ordering_favorites_first_then_updated_desc(client):
    p1 = (
        await client.post(
            "/api/presets",
            json={"name": "P1", "label_type": "text", "definition": _text_definition()},
        )
    ).json()
    p2 = (
        await client.post(
            "/api/presets",
            json={
                "name": "P2",
                "label_type": "text",
                "definition": _text_definition(),
                "favorite": True,
            },
        )
    ).json()
    p3 = (
        await client.post(
            "/api/presets",
            json={"name": "P3", "label_type": "barcode", "definition": {"data": "X"}},
        )
    ).json()

    listed = await client.get("/api/presets")
    assert listed.status_code == 200
    ids = [p["id"] for p in listed.json()]
    # favorite (p2) first, then updated_at desc among the rest (p3 newer than p1).
    assert ids == [p2["id"], p3["id"], p1["id"]]


async def test_list_presets_filters_by_label_type_and_q(client):
    text_preset = (
        await client.post(
            "/api/presets",
            json={"name": "Rack Label", "label_type": "text", "definition": _text_definition()},
        )
    ).json()
    await client.post(
        "/api/presets",
        json={"name": "Shipping Tag", "label_type": "barcode", "definition": {"data": "X"}},
    )

    by_type = await client.get("/api/presets", params={"label_type": "text"})
    assert [p["id"] for p in by_type.json()] == [text_preset["id"]]

    by_q = await client.get("/api/presets", params={"q": "rack"})
    assert [p["id"] for p in by_q.json()] == [text_preset["id"]]

    by_q_miss = await client.get("/api/presets", params={"q": "nonexistent"})
    assert by_q_miss.json() == []


# --- 3. Update ---------------------------------------------------------


async def test_put_preset_updates_fields_and_revalidates_definition(client):
    created = (
        await client.post(
            "/api/presets",
            json={"name": "Orig", "label_type": "text", "definition": _text_definition("A")},
        )
    ).json()

    updated = await client.put(
        f"/api/presets/{created['id']}",
        json={"name": "Renamed", "favorite": True},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "Renamed"
    assert body["favorite"] is True
    assert body["definition"] == _text_definition("A")  # untouched

    # PUT validates a changed `definition` the same way POST does.
    bad = await client.put(
        f"/api/presets/{created['id']}",
        json={"definition": {"lines": "not-a-list"}},
    )
    assert bad.status_code == 422

    good = await client.put(
        f"/api/presets/{created['id']}",
        json={"definition": _text_definition("B")},
    )
    assert good.status_code == 200
    assert good.json()["definition"] == _text_definition("B")


async def test_put_preset_unknown_404(client):
    resp = await client.put("/api/presets/does-not-exist", json={"name": "x"})
    assert resp.status_code == 404


async def test_put_preset_rejects_explicit_null_for_non_nullable_fields(client):
    # review fix-up: `name`/`label_type`/`favorite`/`tape_family` are all
    # NOT NULL columns -- an explicit `null` for any of them used to reach
    # sqlite3 unguarded (name/label_type: raw 500 IntegrityError) or
    # silently coerce (favorite: int(bool(None)) == 0, clearing the flag
    # without any error at all). All four now 422, naming the field.
    created = (
        await client.post(
            "/api/presets",
            json={
                "name": "Orig",
                "label_type": "text",
                "definition": _text_definition(),
                "favorite": True,
                "tape_width_mm": 24,
            },
        )
    ).json()
    preset_id = created["id"]

    for field in ("name", "label_type", "favorite", "tape_family"):
        resp = await client.put(f"/api/presets/{preset_id}", json={field: None})
        assert resp.status_code == 422, field
        assert field in resp.json()["detail"]

    # The preset itself must be untouched by any of the rejected attempts --
    # in particular `favorite` must NOT have been silently cleared.
    unchanged = await client.get(f"/api/presets/{preset_id}")
    assert unchanged.json()["name"] == "Orig"
    assert unchanged.json()["favorite"] is True
    assert unchanged.json()["tape_family"] == "tze"


async def test_put_preset_explicit_null_tape_width_mm_clears_to_any_tape(client):
    created = (
        await client.post(
            "/api/presets",
            json={
                "name": "Has tape",
                "label_type": "text",
                "definition": _text_definition(),
                "tape_width_mm": 24,
            },
        )
    ).json()

    resp = await client.put(f"/api/presets/{created['id']}", json={"tape_width_mm": None})
    assert resp.status_code == 200
    assert resp.json()["tape_width_mm"] is None


async def test_put_preset_revalidates_tape_width_and_family_pair(client):
    created = (
        await client.post(
            "/api/presets",
            json={
                "name": "P",
                "label_type": "text",
                "definition": _text_definition(),
                "tape_width_mm": 9.0,
                "tape_family": "hse_3_1",
            },
        )
    ).json()

    # Changing ONLY tape_family to one that doesn't have a 9.0mm tape must
    # re-validate against the (new family, EXISTING width) pair.
    bad = await client.put(f"/api/presets/{created['id']}", json={"tape_family": "hse_2_1"})
    assert bad.status_code == 422

    # Still 9.0mm/hse_3_1 -- unaffected by the rejected attempt.
    unchanged = await client.get(f"/api/presets/{created['id']}")
    assert unchanged.json()["tape_family"] == "hse_3_1"

    good = await client.put(f"/api/presets/{created['id']}", json={"tape_width_mm": 5.2})
    assert good.status_code == 200  # 5.2mm IS a real hse_3_1 width
    assert good.json()["tape_width_mm"] == 5.2


# --- 4. Delete ---------------------------------------------------------


async def test_delete_preset_204_then_404(client):
    created = (
        await client.post(
            "/api/presets",
            json={"name": "P", "label_type": "text", "definition": _text_definition()},
        )
    ).json()

    resp = await client.delete(f"/api/presets/{created['id']}")
    assert resp.status_code == 204

    missing = await client.get(f"/api/presets/{created['id']}")
    assert missing.status_code == 404

    again = await client.delete(f"/api/presets/{created['id']}")
    assert again.status_code == 404


# --- 5. Print convenience endpoint --------------------------------------


async def test_preset_print_creates_job_with_presets_definition(app_and_client):
    app, client = app_and_client
    created = (
        await client.post(
            "/api/presets",
            json={
                "name": "Port",
                "label_type": "text",
                "definition": _text_definition("PORT-07"),
                "tape_width_mm": 24,
            },
        )
    ).json()

    resp = await client.post(f"/api/presets/{created['id']}/print")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    assert job["definition"]["labels"][0]["type"] == "text"
    assert job["definition"]["labels"][0]["params"]["lines"] == ["PORT-07"]
    assert job["definition"]["labels"][0]["tape"]["width_mm"] == 24


async def test_preset_print_unknown_preset_404(client):
    resp = await client.post("/api/presets/does-not-exist/print")
    assert resp.status_code == 404


async def test_preset_print_without_tape_width_422(client):
    created = (
        await client.post(
            "/api/presets",
            json={"name": "No tape", "label_type": "text", "definition": _text_definition()},
        )
    ).json()
    assert created["tape_width_mm"] is None

    resp = await client.post(f"/api/presets/{created['id']}/print")
    assert resp.status_code == 422


async def test_preset_print_any_tape_preset_with_body_tape_override_succeeds(app_and_client):
    # review fix-up: an "any tape" preset (tape_width_mm=None) previously
    # had NO way to ever be printed via this endpoint (always 422). An
    # explicit `tape` in the request body is now the escape hatch. Uses
    # 24mm/tze -- the mock transport's own default reported tape (see this
    # module's docstring / test_api_print.py's _TAPE_24MM_TZE) -- so the
    # print actually succeeds end to end, not just gets queued.
    app, client = app_and_client
    created = (
        await client.post(
            "/api/presets",
            json={"name": "Any tape", "label_type": "text", "definition": _text_definition()},
        )
    ).json()
    assert created["tape_width_mm"] is None

    resp = await client.post(
        f"/api/presets/{created['id']}/print",
        json={"tape": {"width_mm": 24, "family": "tze"}},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    assert job["definition"]["labels"][0]["tape"] == {"width_mm": 24, "family": "tze"}


async def test_preset_print_body_tape_overrides_presets_own_tape(app_and_client):
    # The preset itself declares 12mm; the mock transport always reports
    # 24mm loaded. If the body's `tape` override were ignored (silently
    # falling back to the preset's own 12mm), rendering at 12mm against a
    # 24mm-loaded mock would FAIL with a tape-mismatch error (see
    # test_api_print.py's own such test) -- succeeding here, at the
    # OVERRIDDEN 24mm, proves the override actually took priority.
    app, client = app_and_client
    created = (
        await client.post(
            "/api/presets",
            json={
                "name": "Has 12mm",
                "label_type": "text",
                "definition": _text_definition(),
                "tape_width_mm": 12,
            },
        )
    ).json()

    resp = await client.post(
        f"/api/presets/{created['id']}/print",
        json={"tape": {"width_mm": 24, "family": "tze"}},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]
    assert job["definition"]["labels"][0]["tape"]["width_mm"] == 24  # body wins, not 12


async def test_preset_print_hse_3_1_9mm_resolves_correct_dots_not_tze(app_and_client, monkeypatch):
    # review fix-up: family was previously hardcoded "tze" regardless of
    # what the preset actually stored -- a 9.0mm hse_3_1 preset would have
    # silently resolved against the 9mm TZE tape (50 print dots) instead of
    # the correct hse_3_1 one (44 print dots), failing later at print time
    # with a misleading raster-mismatch message. Proven here by
    # byte-comparing the printed stream against an in-test build_job call
    # using the CORRECT (hse_3_1, 9.0mm) tape.
    #
    # The mock transport's default REFERENCE_STATUS_BLOCK reports 24mm/
    # undecoded media -- doesn't match a 9mm hse_3_1 design, so the mock's
    # status reply is monkeypatched here (same technique as
    # test_api_print.py's own tape-mismatch test) to report 9mm/
    # HEAT_SHRINK_3_1, matching what this preset actually declares.
    status_block = bytearray(REFERENCE_STATUS_BLOCK)
    status_block[10] = 9  # byte 10: media_width_mm
    status_block[11] = MediaType.HEAT_SHRINK_3_1.value  # byte 11: media_type_raw
    monkeypatch.setattr(
        "labelmaker.jobs.worker.MockPrinterTransport",
        lambda: MockPrinterTransport(status_reply=bytes(status_block)),
    )

    app, client = app_and_client
    created = (
        await client.post(
            "/api/presets",
            json={
                "name": "HSe port",
                "label_type": "text",
                "definition": _text_definition("H"),
                "tape_width_mm": 9.0,
                "tape_family": "hse_3_1",
            },
        )
    ).json()

    resp = await client.post(f"/api/presets/{created['id']}/print")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = await _wait_for_terminal_job(client, job_id)
    assert job["status"] == "done", job["error"]

    stream_resp = await client.get(f"/api/print/jobs/{job_id}/stream")
    assert stream_resp.status_code == 200

    config = app.state.config
    defn = LabelDefinition.model_validate(
        {
            "type": "text",
            "tape": {"width_mm": 9.0, "family": "hse_3_1"},
            "params": _text_definition("H"),
        }
    )
    rendered = render_definition(defn)
    assert rendered.height_px == 44  # NOT 50 (the 9mm TZE tape's print_dots)

    image = rasterize(rendered)
    hse_3_1_9mm = find_tape(9, MediaFamily.HSE_3_1)
    assert hse_3_1_9mm is not None
    assert hse_3_1_9mm.print_dots == 44
    expected = build_job(
        [image],
        hse_3_1_9mm,
        get_strategy(config.printer_init_strategy),
        _expected_job_options(config),
    )
    assert stream_resp.content == expected.data
