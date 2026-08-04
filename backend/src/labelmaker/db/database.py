"""Async SQLite persistence layer.

Pure persistence: this module must never import from ``labelmaker.driver``.
Connects via aiosqlite in autocommit mode (``isolation_level=None``) so that
transaction boundaries are always explicit (``BEGIN``/``COMMIT``/``ROLLBACK``)
rather than left to sqlite3's implicit-transaction heuristics.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_FILE_RE = re.compile(r"^(\d{4})_.*\.sql$")

_VALID_JOB_STATUSES = {"queued", "printing", "done", "failed", "canceled"}
_UPDATABLE_PRESET_FIELDS = {
    "name",
    "definition",
    "tape_width_mm",
    "tape_family",
    "favorite",
    "label_type",
}


def _utcnow() -> str:
    """Current UTC time as ISO-8601 with a literal 'Z' suffix and fixed-width
    microseconds, so consecutive calls remain lexically sortable as TEXT."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _escape_like(value: str) -> str:
    """Escape LIKE's own wildcard characters (`%`, `_`) -- and the escape
    character itself -- in a user-supplied substring, so a literal '%' or
    '_' typed by a caller (e.g. a preset named "50% Off Labels") searches
    for that literal character instead of matching as a wildcard. Pair with
    `LIKE ? ESCAPE '\\'` in the calling SQL (list_presets/list_jobs)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Database:
    """Async wrapper around a single aiosqlite connection.

    Construct via ``await Database.open(path)``, not directly.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    # -- lifecycle -----------------------------------------------------

    @classmethod
    async def open(
        cls,
        path: Path | str,
        migrations_dir: Path | str | None = None,
    ) -> "Database":
        conn = await aiosqlite.connect(str(path), isolation_level=None)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")

        db = cls(conn)
        mdir = Path(migrations_dir) if migrations_dir is not None else _MIGRATIONS_DIR
        try:
            await db._migrate(mdir)
        except Exception:
            await conn.close()
            raise
        return db

    async def close(self) -> None:
        await self._conn.close()

    async def __aenter__(self) -> "Database":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # -- migrations ------------------------------------------------------

    async def _migrate(self, migrations_dir: Path) -> None:
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )

        # Phase-1 review triage: gate on SET MEMBERSHIP of applied versions,
        # not MAX(version). A MAX-based gate ("skip anything <= the highest
        # version we've recorded") silently and permanently skips a
        # migration numbered BELOW an already-applied higher one -- e.g.
        # 0002 merged in from a diverged branch after 0003 already shipped
        # to this db file. That migration would never run, with no error --
        # just a schema quietly missing whatever 0002 was supposed to add.
        # Checking "is THIS EXACT version already recorded" instead applies
        # any such gap-fill correctly regardless of where it falls relative
        # to what's already been applied.
        cur = await self._conn.execute("SELECT version FROM schema_migrations")
        rows = await cur.fetchall()
        applied_versions = {row[0] for row in rows}

        for version, path in self._discover_migrations(migrations_dir):
            if version in applied_versions:
                continue
            statements = self._split_statements(path.read_text())
            await self._conn.execute("BEGIN")
            try:
                for statement in statements:
                    await self._conn.execute(statement)
                await self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, _utcnow()),
                )
            except Exception:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    @staticmethod
    def _split_statements(sql: str) -> list[str]:
        """Split a migration file into individual statements.

        Strips ``--`` line comments first (a semicolon may legitimately
        appear inside one, e.g. a column comment) before splitting on ';'.
        Not a general SQL tokenizer — assumes no string literals containing
        '--' or ';', which holds for this project's DDL-only migrations.
        """
        stripped_lines = []
        for line in sql.splitlines():
            idx = line.find("--")
            stripped_lines.append(line if idx == -1 else line[:idx])
        stripped = "\n".join(stripped_lines)
        return [s.strip() for s in stripped.split(";") if s.strip()]

    @staticmethod
    def _discover_migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
        """Glob `migrations_dir` for `NNNN_*.sql` files, sorted by version.

        Phase-1 review triage: two files sharing the same version number
        (e.g. a rebase/merge collision) used to resolve silently by whichever
        one glob() happened to yield first -- the other was dropped with no
        error, and which one "won" wasn't even deterministic across
        filesystems. Rejected here, at discovery, with a clear error naming
        both filenames, before either one is ever read let alone executed.
        """
        found: dict[int, Path] = {}
        for path in sorted(migrations_dir.glob("*.sql")):
            match = _MIGRATION_FILE_RE.match(path.name)
            if not match:
                continue
            version = int(match.group(1))
            if version in found:
                raise ValueError(
                    f"duplicate migration version {version}: "
                    f"{found[version].name!r} and {path.name!r}"
                )
            found[version] = path
        return sorted(found.items())

    # -- settings ----------------------------------------------------------

    async def get_setting(self, key: str, default: Any = None) -> Any:
        cur = await self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    async def set_setting(self, key: str, value: Any) -> None:
        await self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    async def delete_setting(self, key: str) -> None:
        """Removes the row entirely (task 4.5's settings overlay: a `None`
        PUT means "revert to env/default", which requires the row's
        ABSENCE, not a stored JSON `null` -- `get_setting`/`all_settings`
        can't tell "explicitly set to null" apart from "never set" once a
        `null` is actually persisted, so a clearing write must delete
        instead)."""
        await self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    async def all_settings(self) -> dict[str, Any]:
        cur = await self._conn.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    # -- presets -------------------------------------------------------
    #
    # A preset's `definition` is that type's own PARAMS dict (validated via
    # renderer.Params.model_validate(definition) at the API layer -- see
    # api/router_presets.py), NOT a full LabelDefinition (type+tape+params).
    # `label_type` says which renderer's Params it must satisfy;
    # `tape_width_mm`/`tape_family` (0002_preset_tape_family.sql) are an
    # OPTIONAL tape hint tracked as their own columns instead of nested
    # inside `definition` -- `tape_width_mm` is nullable ("any tape");
    # `tape_family` is NOT nullable (every preset has SOME family, "tze" by
    # default -- see that migration). This module never stores this data
    # as a full LabelDefinition, so 0001_init.sql's column comment
    # ("LabelDefinition JSON", written for print_jobs.definition and
    # reused verbatim for presets.definition) does not describe this
    # table's own `definition` column; this docstring is the authoritative
    # shape for it.

    async def create_preset(
        self,
        name: str,
        label_type: str,
        definition: dict,
        tape_width_mm: float | None = None,
        tape_family: str = "tze",
        favorite: bool = False,
    ) -> dict:
        preset_id = uuid.uuid4().hex
        now = _utcnow()
        await self._conn.execute(
            "INSERT INTO presets "
            "(id, name, label_type, definition, tape_width_mm, tape_family, favorite, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                preset_id,
                name,
                label_type,
                json.dumps(definition),
                tape_width_mm,
                tape_family,
                int(favorite),
                now,
                now,
            ),
        )
        return {
            "id": preset_id,
            "name": name,
            "label_type": label_type,
            "definition": definition,
            "tape_width_mm": tape_width_mm,
            "tape_family": tape_family,
            "favorite": bool(favorite),
            "created_at": now,
            "updated_at": now,
        }

    async def get_preset(self, preset_id: str) -> dict | None:
        cur = await self._conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,))
        row = await cur.fetchone()
        return self._preset_row_to_dict(row) if row is not None else None

    async def list_presets(self, label_type: str | None = None, q: str | None = None) -> list[dict]:
        """`label_type` and `q` combine with AND when both are given. `q` is
        a substring match against `name` -- SQLite's LIKE is already
        case-insensitive for ASCII by default (no COLLATE/LOWER() needed).
        LIKE's own `%`/`_` wildcard characters are escaped in `q` itself
        first (via `_escape_like`) so a literal '%' or '_' typed by the
        user searches for that literal character, not an unintended
        wildcard.
        """
        clauses = []
        params: list[Any] = []
        if label_type is not None:
            clauses.append("label_type = ?")
            params.append(label_type)
        if q is not None:
            clauses.append("name LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(q)}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        cur = await self._conn.execute(
            f"SELECT * FROM presets {where} "
            "ORDER BY favorite DESC, updated_at DESC, rowid DESC",
            params,
        )
        rows = await cur.fetchall()
        return [self._preset_row_to_dict(row) for row in rows]

    async def update_preset(self, preset_id: str, **fields: Any) -> dict | None:
        disallowed = set(fields) - _UPDATABLE_PRESET_FIELDS
        if disallowed:
            raise ValueError(f"invalid field(s) for update_preset: {sorted(disallowed)}")

        set_clauses = []
        params: list[Any] = []
        for key, value in fields.items():
            if key == "definition":
                value = json.dumps(value)
            elif key == "favorite":
                value = int(bool(value))
            set_clauses.append(f"{key} = ?")
            params.append(value)
        set_clauses.append("updated_at = ?")
        params.append(_utcnow())
        params.append(preset_id)

        cur = await self._conn.execute(
            f"UPDATE presets SET {', '.join(set_clauses)} WHERE id = ?", params
        )
        if cur.rowcount == 0:
            return None
        return await self.get_preset(preset_id)

    async def delete_preset(self, preset_id: str) -> bool:
        cur = await self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        return cur.rowcount > 0

    @staticmethod
    def _preset_row_to_dict(row: aiosqlite.Row) -> dict:
        d = dict(row)
        d["definition"] = json.loads(d["definition"])
        d["favorite"] = bool(d["favorite"])
        return d

    # -- print jobs ----------------------------------------------------

    async def create_print_job(
        self,
        definition: dict,
        label_count: int,
        chain_mode: str,
        strategy: str | None = None,
        tape_width_mm: float | None = None,
        media_raw_byte: int | None = None,
        tape_used_mm: float | None = None,
        preview_png: bytes | None = None,
        kind: str = "print",
    ) -> dict:
        """`kind` (0003_print_jobs_kind.sql, feed & cut trigger): 'print'
        (the default -- every pre-existing caller of this method is
        creating a real print job) or 'feed_cut' -- a queued feed-and-cut
        trigger job, api/router_printer.py's own only caller. Not
        validated here (mirrors this method's existing `chain_mode`/
        `strategy` string params, which are similarly unchecked at this
        layer) -- the two literal values above are the only ones anything
        in this codebase ever writes.
        """
        job_id = uuid.uuid4().hex
        now = _utcnow()
        status = "queued"
        await self._conn.execute(
            "INSERT INTO print_jobs "
            "(id, created_at, status, error, definition, label_count, chain_mode, strategy, "
            "tape_width_mm, media_raw_byte, tape_used_mm, preview_png, kind) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                now,
                status,
                json.dumps(definition),
                label_count,
                chain_mode,
                strategy,
                tape_width_mm,
                media_raw_byte,
                tape_used_mm,
                preview_png,
                kind,
            ),
        )
        return {
            "id": job_id,
            "created_at": now,
            "status": status,
            "error": None,
            "definition": definition,
            "label_count": label_count,
            "chain_mode": chain_mode,
            "strategy": strategy,
            "tape_width_mm": tape_width_mm,
            "media_raw_byte": media_raw_byte,
            "tape_used_mm": tape_used_mm,
            "preview_png": preview_png,
            "kind": kind,
        }

    async def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        clear_error: bool = False,
        strategy: str | None = None,
        tape_width_mm: float | None = None,
        media_raw_byte: int | None = None,
        tape_used_mm: float | None = None,
        preview_png: bytes | None = None,
    ) -> dict | None:
        """Partial update: every column argument left at its default (None,
        or False for `clear_error`) is left untouched -- this method never
        overwrites a column the caller didn't explicitly ask to change.

        `strategy`/`tape_width_mm`/`media_raw_byte` (task 2.8) are the
        worker's post-print backfill columns (see jobs/worker.py) -- set
        once a job has actually printed, from what was really used, not
        what the request declared.

        `clear_error`: `error=None` already means "leave `error` as-is"
        (the same convention every other column here follows), so it can't
        ALSO mean "set it to NULL" without becoming ambiguous at the call
        site. A dedicated bool keeps that convention intact for `error` too,
        instead of a magic sentinel value or a second "NOT_SET" object --
        simplest option that says exactly what it does. Passing both `error`
        and `clear_error=True` is almost certainly a caller bug (which one
        wins?), so it's rejected outright rather than silently picking one.
        """
        if status is not None and status not in _VALID_JOB_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        if error is not None and clear_error:
            raise ValueError("update_job: pass at most one of `error` and `clear_error=True`")

        fields: dict[str, Any] = {}
        if status is not None:
            fields["status"] = status
        if clear_error:
            fields["error"] = None
        elif error is not None:
            fields["error"] = error
        if strategy is not None:
            fields["strategy"] = strategy
        if tape_width_mm is not None:
            fields["tape_width_mm"] = tape_width_mm
        if media_raw_byte is not None:
            fields["media_raw_byte"] = media_raw_byte
        if tape_used_mm is not None:
            fields["tape_used_mm"] = tape_used_mm
        if preview_png is not None:
            fields["preview_png"] = preview_png

        if not fields:
            return await self.get_job(job_id)

        set_clauses = ", ".join(f"{key} = ?" for key in fields)
        params = [*fields.values(), job_id]
        cur = await self._conn.execute(
            f"UPDATE print_jobs SET {set_clauses} WHERE id = ?", params
        )
        if cur.rowcount == 0:
            return None
        return await self.get_job(job_id)

    async def cancel_job_if_queued(self, job_id: str) -> bool:
        """Atomic compare-and-swap cancel (task 2.9 carry-forward): a single
        `UPDATE ... WHERE id = ? AND status = 'queued'`, returning whether
        THIS call was the one that made the change (`rowcount == 1`).

        This is the sole race-free way to cancel: a plain
        get_job()-then-update_job("canceled") pair (the pre-2.9 router
        implementation) has a window between the read and the write where
        the worker could dequeue and start printing the job -- the cancel
        would then silently stomp a "printing" (or "done"/"failed") row
        back to "canceled" with no error. Folding the status check into the
        UPDATE's WHERE clause makes the whole read-check-write atomic at
        the database level: if another writer (the worker's own
        `status="printing"` update) already changed the row's status away
        from "queued", this UPDATE matches zero rows and rowcount is 0, no
        matter how the two calls interleave. The caller (api/router_print.py)
        uses the False case to distinguish "unknown id" (404) from "known
        but not cancelable" (409, naming the current status) via a follow-up
        get_job() -- see that router for the exact mapping.
        """
        cur = await self._conn.execute(
            "UPDATE print_jobs SET status = 'canceled' WHERE id = ? AND status = 'queued'",
            (job_id,),
        )
        return cur.rowcount == 1

    async def get_job(self, job_id: str) -> dict | None:
        cur = await self._conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        return self._job_row_to_dict(row) if row is not None else None

    async def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        q: str | None = None,
    ) -> dict:
        """`status`/`q` (task 2.8, backing GET /api/history's own filters --
        see api/router_history.py) combine with AND when both are given.
        `q` is deliberately unfancy: a raw, case-insensitive substring
        match against the serialized `definition` JSON TEXT column, not a
        field-aware search -- the simple option the brief allowed as an
        alternative to skipping `q` entirely.
        """
        # Phase-1 review triage: page_size=-1 previously reached the SQL
        # LIMIT clause unvalidated -- SQLite treats `LIMIT -1` as "no limit
        # at all", turning one malformed query param into an unbounded
        # query. Both bounds are enforced here, before any SQL runs, so the
        # API layer can map a ValueError straight to 422 (see
        # api/router_history.py).
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        if not (1 <= page_size <= 100):
            raise ValueError(f"page_size must be between 1 and 100, got {page_size}")
        if status is not None and status not in _VALID_JOB_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        # M1 (2026-08 review): page has no upper bound above, so a large
        # enough `page` pushes `offset` past 2**63-1 and sqlite3 raises
        # OverflowError (not ValueError) trying to bind it into `LIMIT ?
        # OFFSET ?` below -- router_history.py's `except ValueError -> 422`
        # never sees that, so it escaped to Starlette as an uncaught 500.
        # Rejecting a clearly-pathological offset here, before any SQL
        # runs, keeps this failure mode a ValueError like every other
        # malformed-pagination case above, well under sqlite3's real limit.
        offset = (page - 1) * page_size
        if offset > 10**9:
            raise ValueError(
                f"page {page} with page_size {page_size} is out of range "
                f"(offset {offset} exceeds the 10**9 cap)"
            )

        clauses = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if q is not None:
            clauses.append("definition LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(q)}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        cur = await self._conn.execute(f"SELECT COUNT(*) FROM print_jobs {where}", params)
        row = await cur.fetchone()
        total = row[0]

        cur = await self._conn.execute(
            "SELECT id, created_at, status, error, definition, label_count, chain_mode, "
            "strategy, tape_width_mm, media_raw_byte, tape_used_mm, kind, "
            # review fix-up: derive thumbnail presence from the BLOB column
            # itself (`preview_png IS NOT NULL`), not from `status == "done"`
            # -- the caller (api/router_history.py's light list items) used
            # to infer it from status, which is only correct as long as
            # "sets preview_png" and "sets status=done" never drift apart in
            # jobs/worker.py. Selecting the real fact directly removes that
            # coupling without fetching the (comparatively large) BLOB
            # itself for every row on every listing.
            "(preview_png IS NOT NULL) AS has_thumbnail "
            f"FROM print_jobs {where} "
            "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        )
        rows = await cur.fetchall()
        items = []
        for row in rows:
            d = dict(row)
            d["definition"] = json.loads(d["definition"])
            d["has_thumbnail"] = bool(d["has_thumbnail"])
            items.append(d)
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    async def delete_job(self, job_id: str) -> bool:
        """Atomic compare-and-swap delete (review L2), mirroring
        `cancel_job_if_queued` above: a single `DELETE ... WHERE id = ? AND
        status NOT IN ('queued', 'printing')`, returning whether THIS call
        was the one that removed the row (`rowcount == 1`).

        Deleting a job the worker is currently printing (or has queued to
        print) would orphan the on-disk stream .bin file jobs/worker.py
        writes AFTER the print completes (data_dir/jobs/{id}.bin) -- this
        module never touches the filesystem outside the sqlite file itself,
        so nothing would ever clean that file up once its row is gone. A
        plain get_job()-then-delete pair has the same race
        cancel_job_if_queued's docstring describes (the worker could start
        printing between the read and the write); folding the status check
        into the DELETE's WHERE clause makes the whole read-check-write
        atomic at the database level instead. The caller
        (api/router_history.py) uses the False case to distinguish "unknown
        id" (404) from "known but in flight" (409) via a follow-up
        get_job() -- see that router for the exact mapping.

        On success, the row's `preview_png` thumbnail BLOB is gone the
        instant this DELETE commits (no separate file); the caller still
        removes the on-disk stream .bin file separately."""
        cur = await self._conn.execute(
            "DELETE FROM print_jobs WHERE id = ? AND status NOT IN ('queued', 'printing')",
            (job_id,),
        )
        return cur.rowcount == 1

    async def fail_orphaned_jobs(self) -> int:
        """Startup reconciliation (review L2 follow-up): meant to be called
        once, from main.py's lifespan, right after the db opens and BEFORE
        the worker starts.

        The print queue (`asyncio.Queue`, main.py) is created fresh in
        memory on every boot -- nothing persists it -- so any row still
        'queued' or 'printing' when this runs is dead by construction: no
        worker will ever dequeue or finish it, no matter how long the
        process stays up. Left alone, such a row is worse than merely
        stuck -- `delete_job`'s CAS above (`WHERE status NOT IN ('queued',
        'printing')`) permanently refuses to remove it too, so an
        interrupted job (container restart, `kill -9` mid-print) becomes an
        undeletable dead end with no path back to a terminal status.

        Marking both statuses 'failed' here makes the row terminal again --
        deletable via the CAS on the very next request, and honest in
        `error` about why. Calling this BEFORE the worker task is created
        (see main.py) guarantees it can never race a legitimately in-flight
        job: nothing can be 'printing' yet at this point in a fresh boot.

        Returns the number of rows repaired, so the caller can log it.
        """
        cur = await self._conn.execute(
            "UPDATE print_jobs SET status = 'failed', error = ? "
            "WHERE status IN ('queued', 'printing')",
            ("interrupted by restart",),
        )
        return cur.rowcount

    @staticmethod
    def _job_row_to_dict(row: aiosqlite.Row) -> dict:
        d = dict(row)
        d["definition"] = json.loads(d["definition"])
        return d

    # -- media observations ----------------------------------------------

    async def add_media_observation(
        self,
        raw_status: bytes,
        media_byte: int,
        width_mm: int,
        user_note: str | None = None,
    ) -> dict:
        now = _utcnow()
        cur = await self._conn.execute(
            "INSERT INTO media_observations "
            "(observed_at, raw_status, media_byte, width_mm, user_note) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, raw_status, media_byte, width_mm, user_note),
        )
        return {
            "id": cur.lastrowid,
            "observed_at": now,
            "raw_status": raw_status,
            "media_byte": media_byte,
            "width_mm": width_mm,
            "user_note": user_note,
        }

    async def list_media_observations(self) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT * FROM media_observations ORDER BY observed_at DESC, id DESC"
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]
