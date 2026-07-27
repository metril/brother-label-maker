"""Tests for POST/GET/PUT/DELETE /api/presets and POST /api/presets/{id}/print
(task 2.8).

A preset's `definition` is the label TYPE's own params dict (e.g. "text"'s
TextLabelParams shape: `{"lines": [...], ...}`) -- NOT a full LabelDefinition
(type+tape+params). `label_type` and `tape_width_mm` are separate,
independently-settable columns: `label_type` says which renderer's Params
`definition` is validated against, and `tape_width_mm` is an OPTIONAL tape
hint (nullable = "any tape", per the 0001_init.sql migration comment) used
for filtering/display and, when set, to build a real Tape (family always
"tze" -- presets don't track family) for the POST .../print convenience
endpoint.
"""

from __future__ import annotations

import asyncio

from labelmaker.driver.geometry import MediaFamily, find_tape

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
    assert body["favorite"] is False


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
