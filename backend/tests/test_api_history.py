"""Tests for GET /api/history (+ /{id}, /{id}/thumbnail, /{id}/reprint,
DELETE /{id}) -- task 2.8.

GET /api/history's list items are a deliberately LIGHT shape (id,
created_at, status, error, label_count, chain_mode, strategy, tape_width_mm,
tape_used_mm, thumbnail_url) -- the Phase-1 review's "split the job
resource" note: no `definition` (can be large -- up to 1000 expanded
labels' worth for a serialized run), no inline base64 thumbnail bytes.
GET /api/history/{id} is the full resource (same shape as
GET /api/print/jobs/{id}), for when a caller actually wants the definition.
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


def _text_label(text: str = "HELLO") -> dict:
    return {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": [text]},
    }


def _serial_template(text: str = "Port {seq}") -> dict:
    return {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": [text]},
    }


async def _print_and_wait(client, label_text: str = "HELLO") -> dict:
    resp = await client.post("/api/print", json={"labels": [_text_label(label_text)]})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    return await _wait_for_terminal_job(client, job_id)


# --- 1. Pagination / light shape --------------------------------------------


async def test_history_list_is_light_shape_without_definition_or_thumbnail_bytes(client):
    job = await _print_and_wait(client)

    resp = await client.get("/api/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1

    item = body["items"][0]
    assert item["id"] == job["id"]
    assert set(item) == {
        "id",
        "created_at",
        "status",
        "error",
        "label_count",
        "chain_mode",
        "strategy",
        "tape_width_mm",
        "tape_used_mm",
        "thumbnail_url",
    }
    assert item["status"] == "done"
    assert item["strategy"] == "classic"
    assert item["thumbnail_url"] == f"/api/history/{job['id']}/thumbnail"


async def test_history_list_thumbnail_url_derives_from_preview_png_not_status(app_and_client):
    """review fix-up: thumbnail_url used to be derived from `status ==
    "done"` -- correct today only because jobs/worker.py happens to always
    set preview_png and status="done" in the same update_job call. db.
    list_jobs now selects `preview_png IS NOT NULL` directly, so this holds
    even for a row where that coupling doesn't apply -- proven here with a
    job created directly with a preview_png but left at status="queued"
    (never touched by the worker): the OLD status-based derivation would
    have wrongly reported no thumbnail_url for this row."""
    app, client = app_and_client
    db = app.state.db
    job = await db.create_print_job(
        {"labels": [_text_label()], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
        preview_png=b"\x89PNG\r\n\x1a\nfake thumbnail bytes",
    )
    assert job["status"] == "queued"

    resp = await client.get("/api/history")
    item = next(i for i in resp.json()["items"] if i["id"] == job["id"])
    assert item["status"] == "queued"
    assert item["thumbnail_url"] == f"/api/history/{job['id']}/thumbnail"

    thumb = await client.get(item["thumbnail_url"])
    assert thumb.status_code == 200


async def test_history_list_newest_first_and_pagination(client):
    ids = []
    for i in range(3):
        job = await _print_and_wait(client, f"LABEL-{i}")
        ids.append(job["id"])

    page = await client.get("/api/history", params={"page": 1, "page_size": 2})
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == ids[-1]  # newest first

    page2 = await client.get("/api/history", params={"page": 2, "page_size": 2})
    assert len(page2.json()["items"]) == 1
    assert page2.json()["items"][0]["id"] == ids[0]


async def test_history_list_bounds_map_to_422(client):
    for params in (
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": -1},
    ):
        resp = await client.get("/api/history", params=params)
        assert resp.status_code == 422, params


async def test_history_list_extreme_page_maps_to_422_not_500(client):
    # M1 (2026-08 review): `offset = (page - 1) * page_size` used to be
    # bound straight into `LIMIT ? OFFSET ?` unbounded above -- past
    # 2**63-1 sqlite3 raises OverflowError (not ValueError), which escaped
    # router_history.py's `except ValueError -> 422` mapping and reached
    # Starlette as an uncaught 500. db.list_jobs now rejects a
    # pathologically large offset itself, so this is a clean 422 like every
    # other malformed pagination value, never a 500.
    for page in (10**18, 10**19):
        resp = await client.get("/api/history", params={"page": page})
        assert resp.status_code == 422, page


async def test_history_list_large_but_legal_page_is_200_with_empty_items(client):
    # A big page number that still produces an offset well under the
    # 10**9 cap must behave like any other out-of-range-but-valid page:
    # 200 with an empty page, not rejected.
    resp = await client.get("/api/history", params={"page": 10**6})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["page"] == 10**6
    assert body["total"] == 0


async def test_history_list_filters_by_status_and_q(app_and_client):
    app, client = app_and_client
    db = app.state.db

    done = await _print_and_wait(client, "PORT-07")
    assert done["status"] == "done"

    failed_job = await db.create_print_job(
        {"labels": [_text_label("RACK-A1")], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
    )
    await db.update_job(failed_job["id"], status="failed", error="tape jam")

    by_status = await client.get("/api/history", params={"status": "failed"})
    assert [item["id"] for item in by_status.json()["items"]] == [failed_job["id"]]

    by_q = await client.get("/api/history", params={"q": "PORT-07"})
    assert [item["id"] for item in by_q.json()["items"]] == [done["id"]]


# --- 2. Full GET -------------------------------------------------------------


async def test_history_get_by_id_includes_full_definition(client):
    job = await _print_and_wait(client)

    resp = await client.get(f"/api/history/{job['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["definition"]["labels"][0]["params"]["lines"] == ["HELLO"]
    assert body["thumbnail_png_b64"] is not None


async def test_history_get_unknown_404(client):
    resp = await client.get("/api/history/does-not-exist")
    assert resp.status_code == 404


# --- 3. Thumbnail -------------------------------------------------------------


async def test_history_thumbnail_200_then_404_for_jobless(client):
    job = await _print_and_wait(client)

    resp = await client.get(f"/api/history/{job['id']}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    missing = await client.get("/api/history/does-not-exist/thumbnail")
    assert missing.status_code == 404


async def test_history_thumbnail_404_when_job_has_none_yet(app_and_client):
    app, client = app_and_client
    db = app.state.db
    job = await db.create_print_job(
        {"labels": [_text_label()], "options": {"chain_mode": "cut_each"}},
        label_count=1,
        chain_mode="cut_each",
    )
    resp = await client.get(f"/api/history/{job['id']}/thumbnail")
    assert resp.status_code == 404


# --- 4. Reprint ----------------------------------------------------------


async def test_reprint_creates_new_job_with_identical_rendered_stream(client):
    job = await _print_and_wait(client)
    original_stream = await client.get(f"/api/print/jobs/{job['id']}/stream")
    assert original_stream.status_code == 200

    resp = await client.post(f"/api/history/{job['id']}/reprint")
    assert resp.status_code == 202
    new_job_id = resp.json()["job_id"]
    assert new_job_id != job["id"]

    new_job = await _wait_for_terminal_job(client, new_job_id)
    assert new_job["status"] == "done", new_job["error"]

    new_stream = await client.get(f"/api/print/jobs/{new_job_id}/stream")
    assert new_stream.status_code == 200
    assert new_stream.content == original_stream.content

    # A fresh definition COPY, not a reference to the same row.
    new_full = await client.get(f"/api/history/{new_job_id}")
    original_full = await client.get(f"/api/history/{job['id']}")
    assert new_full.json()["definition"] == original_full.json()["definition"]


async def test_reprint_serialization_job_reexpands_to_same_label_count(client):
    serialization = {"kind": "list", "values": ["A", "B", "C"], "copies_per_value": 1}
    resp = await client.post(
        "/api/print",
        json={"labels": [_serial_template()], "serialization": serialization},
    )
    job_id = resp.json()["job_id"]
    job = await _wait_for_terminal_job(client, job_id)
    assert job["label_count"] == 3

    reprint_resp = await client.post(f"/api/history/{job_id}/reprint")
    assert reprint_resp.status_code == 202
    new_job_id = reprint_resp.json()["job_id"]

    new_job = await _wait_for_terminal_job(client, new_job_id)
    assert new_job["status"] == "done", new_job["error"]
    assert new_job["label_count"] == 3

    # Same stream bytes -- re-expanded from the same (template, spec) pair.
    original_stream = await client.get(f"/api/print/jobs/{job_id}/stream")
    new_stream = await client.get(f"/api/print/jobs/{new_job_id}/stream")
    assert new_stream.content == original_stream.content


async def test_reprint_unknown_job_404(client):
    resp = await client.post("/api/history/does-not-exist/reprint")
    assert resp.status_code == 404


async def test_reprint_409_when_stored_definition_no_longer_validates(app_and_client):
    app, client = app_and_client
    db = app.state.db

    # db.create_print_job doesn't validate `definition` at all (only the
    # API layer does, at POST /api/print time) -- inserting an unrenderable
    # definition directly simulates "this job's definition no longer
    # validates" (e.g. a font/label type was removed after it was printed)
    # without needing to actually delete a font file.
    bad_definition = {
        "labels": [
            {
                "type": "does-not-exist",
                "tape": {"width_mm": 24, "family": "tze"},
                "params": {},
            }
        ],
        "options": {"chain_mode": "cut_each"},
    }
    job = await db.create_print_job(bad_definition, label_count=1, chain_mode="cut_each")

    resp = await client.post(f"/api/history/{job['id']}/reprint")
    assert resp.status_code == 409
    assert "does-not-exist" in resp.json()["detail"]


# --- 5. Delete -------------------------------------------------------------


async def test_delete_history_job_removes_row_and_stream_file(app_and_client):
    app, client = app_and_client
    config = app.state.config
    job = await _print_and_wait(client)

    stream_path = config.data_dir / "jobs" / f"{job['id']}.bin"
    assert stream_path.is_file()

    resp = await client.delete(f"/api/history/{job['id']}")
    assert resp.status_code == 204

    assert not stream_path.exists()

    missing = await client.get(f"/api/history/{job['id']}")
    assert missing.status_code == 404

    again = await client.delete(f"/api/history/{job['id']}")
    assert again.status_code == 404
