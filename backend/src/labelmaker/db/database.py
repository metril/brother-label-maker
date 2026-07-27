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
_UPDATABLE_PRESET_FIELDS = {"name", "definition", "tape_width_mm", "favorite", "label_type"}


def _utcnow() -> str:
    """Current UTC time as ISO-8601 with a literal 'Z' suffix and fixed-width
    microseconds, so consecutive calls remain lexically sortable as TEXT."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


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

        cur = await self._conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        row = await cur.fetchone()
        current_version = row[0]

        for version, path in self._discover_migrations(migrations_dir):
            if version <= current_version:
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
        found = []
        for path in migrations_dir.glob("*.sql"):
            match = _MIGRATION_FILE_RE.match(path.name)
            if not match:
                continue
            found.append((int(match.group(1)), path))
        found.sort(key=lambda item: item[0])
        return found

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

    async def all_settings(self) -> dict[str, Any]:
        cur = await self._conn.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    # -- presets -------------------------------------------------------

    async def create_preset(
        self,
        name: str,
        label_type: str,
        definition: dict,
        tape_width_mm: float | None = None,
        favorite: bool = False,
    ) -> dict:
        preset_id = uuid.uuid4().hex
        now = _utcnow()
        await self._conn.execute(
            "INSERT INTO presets "
            "(id, name, label_type, definition, tape_width_mm, favorite, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                preset_id,
                name,
                label_type,
                json.dumps(definition),
                tape_width_mm,
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
            "favorite": bool(favorite),
            "created_at": now,
            "updated_at": now,
        }

    async def get_preset(self, preset_id: str) -> dict | None:
        cur = await self._conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,))
        row = await cur.fetchone()
        return self._preset_row_to_dict(row) if row is not None else None

    async def list_presets(self, label_type: str | None = None) -> list[dict]:
        if label_type is not None:
            cur = await self._conn.execute(
                "SELECT * FROM presets WHERE label_type = ? "
                "ORDER BY favorite DESC, updated_at DESC, rowid DESC",
                (label_type,),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM presets ORDER BY favorite DESC, updated_at DESC, rowid DESC"
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
    ) -> dict:
        job_id = uuid.uuid4().hex
        now = _utcnow()
        status = "queued"
        await self._conn.execute(
            "INSERT INTO print_jobs "
            "(id, created_at, status, error, definition, label_count, chain_mode, strategy, "
            "tape_width_mm, media_raw_byte, tape_used_mm, preview_png) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        }

    async def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        tape_used_mm: float | None = None,
        preview_png: bytes | None = None,
    ) -> dict | None:
        if status is not None and status not in _VALID_JOB_STATUSES:
            raise ValueError(f"invalid status: {status!r}")

        fields: dict[str, Any] = {}
        if status is not None:
            fields["status"] = status
        if error is not None:
            fields["error"] = error
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

    async def get_job(self, job_id: str) -> dict | None:
        cur = await self._conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        return self._job_row_to_dict(row) if row is not None else None

    async def list_jobs(self, page: int = 1, page_size: int = 20) -> dict:
        cur = await self._conn.execute("SELECT COUNT(*) FROM print_jobs")
        row = await cur.fetchone()
        total = row[0]

        offset = (page - 1) * page_size
        cur = await self._conn.execute(
            "SELECT id, created_at, status, error, definition, label_count, chain_mode, "
            "strategy, tape_width_mm, media_raw_byte, tape_used_mm "
            "FROM print_jobs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = await cur.fetchall()
        items = []
        for row in rows:
            d = dict(row)
            d["definition"] = json.loads(d["definition"])
            items.append(d)
        return {"items": items, "page": page, "page_size": page_size, "total": total}

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
