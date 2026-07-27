"""Tests for labelmaker.db.database: aiosqlite layer, migrations, CRUD.

Pure persistence tests — no labelmaker.driver imports anywhere in this file
(the db module must not depend on the driver, and neither should its tests).
"""

import sqlite3

import pytest

from labelmaker.db.database import _MIGRATIONS_DIR, Database

# --- 1. Migration runner: WAL mode, idempotent re-open, persistence ---


async def test_open_sets_wal_mode_and_applies_migrations_once(tmp_path):
    # Derived from the REAL migrations dir (not hardcoded) so this test
    # doesn't need updating every time a new migration is added -- it's
    # asserting "every discovered migration applied exactly once", not a
    # specific count.
    expected_migration_count = len(Database._discover_migrations(_MIGRATIONS_DIR))

    db_path = tmp_path / "app.db"
    db = await Database.open(db_path)

    cur = await db._conn.execute("PRAGMA journal_mode")
    (mode,) = await cur.fetchone()
    assert mode.lower() == "wal"

    cur = await db._conn.execute("SELECT COUNT(*) FROM schema_migrations")
    (count,) = await cur.fetchone()
    assert count == expected_migration_count

    await db.set_setting("greeting", "hello")
    await db.close()

    # Re-open the same file: migrations must not re-apply, data must survive.
    db2 = await Database.open(db_path)
    cur = await db2._conn.execute("SELECT COUNT(*) FROM schema_migrations")
    (count2,) = await cur.fetchone()
    assert count2 == expected_migration_count
    assert await db2.get_setting("greeting") == "hello"
    await db2.close()


async def test_memory_database_opens_and_works():
    db = await Database.open(":memory:")
    await db.set_setting("k", 1)
    assert await db.get_setting("k") == 1
    await db.close()


async def test_database_async_context_manager(tmp_path):
    db = await Database.open(tmp_path / "ctx.db")
    async with db:
        await db.set_setting("k", "v")
        assert await db.get_setting("k") == "v"
    with pytest.raises(Exception):  # noqa: B017 - closed-connection error, driver-specific
        await db._conn.execute("SELECT 1")


# --- 2. Settings ---


async def test_settings_roundtrip_default_and_upsert():
    db = await Database.open(":memory:")
    try:
        assert await db.get_setting("missing", default="fallback") == "fallback"
        assert await db.get_setting("missing") is None

        await db.set_setting("nested", {"a": 1, "b": [1, 2, 3]})
        assert await db.get_setting("nested") == {"a": 1, "b": [1, 2, 3]}

        await db.set_setting("nested", {"a": 2})  # upsert overwrites
        assert await db.get_setting("nested") == {"a": 2}

        await db.set_setting("flag", True)
        assert await db.all_settings() == {"nested": {"a": 2}, "flag": True}
    finally:
        await db.close()


# --- 3. Presets ---


async def test_preset_crud_and_list_ordering(monkeypatch):
    db = await Database.open(":memory:")
    try:
        timestamps = iter(
            [
                "2026-01-01T00:00:00.000000Z",  # p1 create
                "2026-01-01T00:00:01.000000Z",  # p2 create
                "2026-01-01T00:00:02.000000Z",  # p3 create
                "2026-01-01T00:00:03.000000Z",  # p1 update
                "2026-01-01T00:00:04.000000Z",  # update_preset("nonexistent", ...) - still
                # computes a timestamp before discovering the id doesn't match any row
            ]
        )
        monkeypatch.setattr(
            "labelmaker.db.database._utcnow", lambda: next(timestamps)
        )

        p1 = await db.create_preset("A", "address", {"x": 1})
        p2 = await db.create_preset("B", "address", {"x": 2}, favorite=True)
        p3 = await db.create_preset("C", "shipping", {"x": 3}, tape_width_mm=24.0)

        assert p1["favorite"] is False
        assert p1["created_at"] == p1["updated_at"] == "2026-01-01T00:00:00.000000Z"
        assert p2["favorite"] is True
        assert p3["tape_width_mm"] == 24.0

        assert await db.get_preset(p1["id"]) == p1
        assert await db.get_preset("nonexistent") is None

        # favorites first, then updated_at desc among the rest (p3 newer than p1)
        listed = await db.list_presets()
        assert [p["id"] for p in listed] == [p2["id"], p3["id"], p1["id"]]

        listed_addr = await db.list_presets(label_type="address")
        assert {p["id"] for p in listed_addr} == {p1["id"], p2["id"]}

        updated = await db.update_preset(p1["id"], name="A2", favorite=True)
        assert updated["name"] == "A2"
        assert updated["favorite"] is True
        assert updated["updated_at"] == "2026-01-01T00:00:03.000000Z"
        assert updated["created_at"] == "2026-01-01T00:00:00.000000Z"  # unchanged

        with pytest.raises(ValueError):
            await db.update_preset(p1["id"], created_at="hacked")

        assert await db.update_preset("nonexistent", name="x") is None

        assert await db.delete_preset(p3["id"]) is True
        assert await db.get_preset(p3["id"]) is None
        assert await db.delete_preset(p3["id"]) is False
    finally:
        await db.close()


async def test_list_presets_q_filters_name_substring_case_insensitively():
    db = await Database.open(":memory:")
    try:
        rack = await db.create_preset("Rack Label", "address", {})
        port = await db.create_preset("Port Sticker", "address", {})
        await db.create_preset("Shipping Tag", "shipping", {})

        listed = await db.list_presets(q="ack")  # substring, mixed case below
        assert {p["id"] for p in listed} == {rack["id"]}

        listed = await db.list_presets(q="STICKER")
        assert {p["id"] for p in listed} == {port["id"]}

        listed = await db.list_presets(q="nonexistent-substring")
        assert listed == []

        # q combines (AND) with label_type, not OR.
        listed = await db.list_presets(label_type="shipping", q="rack")
        assert listed == []
    finally:
        await db.close()


# --- 4. Print jobs ---


async def test_print_job_lifecycle():
    db = await Database.open(":memory:")
    try:
        definition = {"labels": [{"text": "hi"}], "options": {"chain_mode": "cut_each"}}
        job = await db.create_print_job(
            definition,
            label_count=1,
            chain_mode="cut_each",
            strategy="classic",
            tape_width_mm=24.0,
            media_raw_byte=0x81,
        )
        assert job["status"] == "queued"
        assert job["error"] is None
        assert job["definition"] == definition
        assert job["preview_png"] is None

        assert await db.get_job(job["id"]) == job

        with pytest.raises(ValueError):
            await db.update_job(job["id"], status="not-a-real-status")

        updated = await db.update_job(job["id"], status="printing")
        assert updated["status"] == "printing"

        updated = await db.update_job(
            job["id"], status="failed", error="tape jam", tape_used_mm=15.5
        )
        assert updated["status"] == "failed"
        assert updated["error"] == "tape jam"
        assert updated["tape_used_mm"] == 15.5

        png = b"\x89PNG\r\n fake preview bytes \x00\x01"
        updated = await db.update_job(job["id"], preview_png=png)
        assert updated["preview_png"] == png
        got = await db.get_job(job["id"])
        assert got["preview_png"] == png
        assert got["definition"] == definition  # still round-trips as dict

        assert await db.update_job("nonexistent-id", status="done") is None
    finally:
        await db.close()


async def test_update_job_widened_columns_and_clear_error_sentinel():
    """Task 2.8 carry-forward: update_job widened to also accept
    strategy/tape_width_mm/media_raw_byte (the worker backfill columns --
    see jobs/worker.py), plus a `clear_error` flag to explicitly null out
    `error` on e.g. a manual re-queue.

    `clear_error` (not a None-sentinel on `error` itself) because `error`
    already means "leave unchanged" at None throughout this method, same as
    every other optional column here (tape_used_mm, preview_png, ...) --
    overloading None to ALSO mean "set it to NULL" for just this one field
    would make it the sole exception to that convention, and silently
    ambiguous besides (a caller who does `update_job(id, error=maybe_none)`
    could never tell "don't touch" from "clear" apart at the call site). A
    separate explicit bool keeps every field's None meaning exactly what it
    already means everywhere else in this signature.
    """
    db = await Database.open(":memory:")
    try:
        job = await db.create_print_job({"labels": []}, label_count=1, chain_mode="cut_each")

        updated = await db.update_job(
            job["id"], strategy="classic", tape_width_mm=24.0, media_raw_byte=0x14
        )
        assert updated["strategy"] == "classic"
        assert updated["tape_width_mm"] == 24.0
        assert updated["media_raw_byte"] == 0x14

        failed = await db.update_job(job["id"], status="failed", error="tape jam")
        assert failed["error"] == "tape jam"

        # clear_error=True nulls `error` out even though no new `error` was
        # given -- e.g. a manual re-queue back to "queued" clearing a stale
        # failure message.
        cleared = await db.update_job(job["id"], status="queued", clear_error=True)
        assert cleared["status"] == "queued"
        assert cleared["error"] is None

        # Columns untouched by that last call keep their prior values --
        # clear_error doesn't reset anything else.
        assert cleared["strategy"] == "classic"

        with pytest.raises(ValueError):
            await db.update_job(job["id"], error="x", clear_error=True)

        with pytest.raises(ValueError):
            await db.update_job(job["id"], status="not-a-real-status")
    finally:
        await db.close()


async def test_list_jobs_bounds_raise_value_error():
    """Phase-1 review triage: page_size=-1 used to reach SQL as `LIMIT -1`,
    which SQLite treats as "no limit" -- an unbounded query from a single
    malformed query param. page/page_size are now validated up front."""
    db = await Database.open(":memory:")
    try:
        for kwargs in (
            {"page": 0},
            {"page": -1},
            {"page_size": 0},
            {"page_size": 101},
            {"page_size": -1},
        ):
            with pytest.raises(ValueError):
                await db.list_jobs(**kwargs)
    finally:
        await db.close()


async def test_print_job_pagination_newest_first_excludes_preview():
    db = await Database.open(":memory:")
    try:
        ids = []
        for i in range(25):
            job = await db.create_print_job(
                {"i": i}, label_count=1, chain_mode="cut_each", preview_png=b"thumb"
            )
            ids.append(job["id"])

        page1 = await db.list_jobs(page=1, page_size=20)
        assert page1["total"] == 25
        assert page1["page"] == 1
        assert page1["page_size"] == 20
        assert len(page1["items"]) == 20

        page2 = await db.list_jobs(page=2, page_size=20)
        assert len(page2["items"]) == 5

        # newest first: the last job created is the first item overall.
        assert page1["items"][0]["id"] == ids[-1]
        assert page2["items"][-1]["id"] == ids[0]

        for item in page1["items"] + page2["items"]:
            assert "preview_png" not in item
            assert isinstance(item["definition"], dict)
    finally:
        await db.close()


async def test_list_jobs_status_and_q_filters():
    """task 2.8: `status` and `q` back GET /api/history's own filters (see
    api/router_history.py). `q` is deliberately unfancy -- a raw
    case-insensitive substring match against the serialized `definition`
    JSON text, not a field-aware search (the brief's "skip q if it
    complicates" escape hatch; this is the simple option, documented)."""
    db = await Database.open(":memory:")
    try:
        done = await db.create_print_job(
            {"labels": [{"params": {"lines": ["PORT-07"]}}]},
            label_count=1,
            chain_mode="cut_each",
        )
        await db.update_job(done["id"], status="done")

        failed = await db.create_print_job(
            {"labels": [{"params": {"lines": ["RACK-A1"]}}]},
            label_count=1,
            chain_mode="cut_each",
        )
        await db.update_job(failed["id"], status="failed", error="tape jam")

        result = await db.list_jobs(status="done")
        assert [item["id"] for item in result["items"]] == [done["id"]]

        result = await db.list_jobs(status="failed")
        assert [item["id"] for item in result["items"]] == [failed["id"]]

        result = await db.list_jobs(q="port-07")  # case-insensitive substring
        assert [item["id"] for item in result["items"]] == [done["id"]]

        result = await db.list_jobs(q="nonexistent-substring")
        assert result["items"] == []
        assert result["total"] == 0

        # status and q combine (AND).
        result = await db.list_jobs(status="done", q="rack")
        assert result["items"] == []

        with pytest.raises(ValueError):
            await db.list_jobs(status="not-a-real-status")
    finally:
        await db.close()


async def test_delete_job_removes_row_and_reports_missing():
    db = await Database.open(":memory:")
    try:
        job = await db.create_print_job({"labels": []}, label_count=1, chain_mode="cut_each")

        assert await db.delete_job(job["id"]) is True
        assert await db.get_job(job["id"]) is None
        assert await db.delete_job(job["id"]) is False
        assert await db.delete_job("nonexistent-id") is False
    finally:
        await db.close()


# --- Invalid status validated even with no matching job ---


async def test_update_job_invalid_status_raises_before_lookup():
    db = await Database.open(":memory:")
    try:
        with pytest.raises(ValueError):
            await db.update_job("no-such-job", status="bogus")
    finally:
        await db.close()


# --- 5. Media observations ---


async def test_media_observations_insert_and_list_newest_first():
    db = await Database.open(":memory:")
    try:
        raw1 = bytes(range(32))
        assert len(raw1) == 32
        obs1 = await db.add_media_observation(
            raw1, media_byte=0x0A, width_mm=24, user_note="kit tape"
        )

        raw2 = bytes(reversed(range(32)))
        obs2 = await db.add_media_observation(raw2, media_byte=0x0B, width_mm=12)

        listed = await db.list_media_observations()
        assert [o["id"] for o in listed] == [obs2["id"], obs1["id"]]
        assert listed[0]["raw_status"] == raw2
        assert len(listed[0]["raw_status"]) == 32
        assert listed[1]["raw_status"] == raw1
        assert listed[1]["user_note"] == "kit tape"
        assert listed[0]["user_note"] is None
    finally:
        await db.close()


# --- 6. Migration runner is general (proven with an injected 0002) ---


async def test_migration_runner_applies_additional_migration(tmp_path):
    import shutil

    # Copies ONLY 0001_init.sql (not the whole real migrations dir, via
    # shutil.copytree) -- this test injects its OWN synthetic "0002" next
    # migration, which would collide (duplicate version) with whatever the
    # real migrations dir's own next migration happens to be numbered.
    # Isolating from that keeps this test about the GENERAL mechanism, not
    # coupled to however many real migrations currently exist.
    custom_dir = tmp_path / "migrations"
    custom_dir.mkdir()
    shutil.copy(_MIGRATIONS_DIR / "0001_init.sql", custom_dir / "0001_init.sql")
    (custom_dir / "0002_add_preset_note.sql").write_text(
        "ALTER TABLE presets ADD COLUMN note TEXT;\n"
    )

    db_path = tmp_path / "custom.db"
    db = await Database.open(db_path, migrations_dir=custom_dir)
    try:
        cur = await db._conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        rows = await cur.fetchall()
        assert [row[0] for row in rows] == [1, 2]

        cur = await db._conn.execute("PRAGMA table_info(presets)")
        columns = {row[1] for row in await cur.fetchall()}
        assert "note" in columns
    finally:
        await db.close()

    # Re-opening with the same custom dir must not re-apply either migration.
    db2 = await Database.open(db_path, migrations_dir=custom_dir)
    cur = await db2._conn.execute("SELECT COUNT(*) FROM schema_migrations")
    (count,) = await cur.fetchone()
    assert count == 2
    await db2.close()


async def test_migration_gap_fill_applies_missing_version_below_already_applied_max(tmp_path):
    """Phase-1 review triage: the old gate compared each discovered version
    against MAX(applied version) -- so a migration numbered BELOW an
    already-applied higher version (e.g. 0002 merged in after 0003 already
    shipped to this db, from a diverged branch) was silently skipped
    forever, even though it was never actually applied. The fix gates on
    SET membership of applied versions instead: "is this exact version
    already recorded", not "is this version <= the highest one recorded"."""
    import shutil

    # Same isolation as test_migration_runner_applies_additional_migration
    # above: copy ONLY 0001_init.sql, not the whole real migrations dir, so
    # this test's own synthetic "0002"/"0003" files can't collide with
    # whatever the real migrations dir's own next migrations are numbered.
    custom_dir = tmp_path / "migrations"
    custom_dir.mkdir()
    shutil.copy(_MIGRATIONS_DIR / "0001_init.sql", custom_dir / "0001_init.sql")
    (custom_dir / "0003_add_note3.sql").write_text(
        "ALTER TABLE presets ADD COLUMN note3 TEXT;\n"
    )

    db_path = tmp_path / "gapfill.db"
    db = await Database.open(db_path, migrations_dir=custom_dir)
    cur = await db._conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    rows = await cur.fetchall()
    assert [row[0] for row in rows] == [1, 3]
    await db.close()

    # 0002 lands in the migrations dir AFTER 0003 was already applied to
    # this db file -- a gap below the recorded max. Re-opening must still
    # apply it.
    (custom_dir / "0002_add_note2.sql").write_text(
        "ALTER TABLE presets ADD COLUMN note2 TEXT;\n"
    )

    db2 = await Database.open(db_path, migrations_dir=custom_dir)
    try:
        cur = await db2._conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        rows = await cur.fetchall()
        assert [row[0] for row in rows] == [1, 2, 3]

        cur = await db2._conn.execute("PRAGMA table_info(presets)")
        columns = {row[1] for row in await cur.fetchall()}
        assert "note2" in columns
        assert "note3" in columns
    finally:
        await db2.close()


async def test_migration_discovery_rejects_duplicate_version_numbers(tmp_path):
    custom_dir = tmp_path / "migrations"
    custom_dir.mkdir()
    (custom_dir / "0001_init.sql").write_text("CREATE TABLE foo (id INTEGER PRIMARY KEY);\n")
    (custom_dir / "0001_also_init.sql").write_text("CREATE TABLE bar (id INTEGER PRIMARY KEY);\n")

    db_path = tmp_path / "dup.db"
    with pytest.raises(ValueError, match="duplicate migration version"):
        await Database.open(db_path, migrations_dir=custom_dir)


async def test_migration_runs_in_a_transaction_rolls_back_on_failure(tmp_path):
    custom_dir = tmp_path / "migrations"
    custom_dir.mkdir()
    (custom_dir / "0001_init.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE this is not valid sql (;\n"
    )

    db_path = tmp_path / "broken.db"
    with pytest.raises(Exception):  # noqa: B017 - sqlite3 raises OperationalError
        await Database.open(db_path, migrations_dir=custom_dir)

    # Inspect with a plain sqlite3 connection: the failed migration must have
    # left no partial trace (table not created, version not recorded), even
    # though the runner's own schema_migrations bootstrap did commit.
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "foo" not in tables
    assert "schema_migrations" in tables
