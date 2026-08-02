"""A DB-backed overlay over `AppConfig` (task 4.5): lets an operator change a
small, curated set of settings from the running app (Settings page ->
GET/PUT /api/settings, api/router_settings.py) without editing the
environment and restarting the container.

`AppConfig` (config.py) stays the single source of env-derived defaults and
is never mutated -- this module adds a second, DB-backed layer ON TOP of it.
Every overridable field lives in the generic `settings` KV table
(db/database.py's get_setting/set_setting/all_settings/delete_setting) under
the key `"cfg.<field>"`, so no new migration is needed. `SettingsOverrides`
below is BOTH the request-validation model for PUT /api/settings AND (via
`OVERRIDABLE_FIELDS = set(SettingsOverrides.model_fields)`) the single
source of truth for exactly which fields can be overridden at all -- adding
a new overridable setting later means touching this one model, not hunting
down every place a field list might have been hand-duplicated.

Two fields (`keep_printer_awake`, `keep_awake_interval_min`) have no
`AppConfig` twin at all -- they are DB-only settings with a hardcoded
fallback default (`_DB_ONLY_DEFAULTS`) instead of an env-derived one.

-- Thread safety --

`SettingsOverlay` is mutated ONLY from the event loop (`set_many`, awaited
from api/router_settings.py's PUT handler, which FastAPI always runs on the
loop). `effective()` returns an immutable (`frozen=True`) snapshot,
`EffectiveSettings` -- jobs/worker.py's `_process_job` calls `effective()`
once, on the event loop, BEFORE handing any of that snapshot's fields into
`anyio.to_thread.run_sync` (exactly the same pattern it already used for
`state.config`, itself just an immutable pydantic-settings instance). A
worker thread therefore only ever sees a frozen dataclass-like snapshot
taken at one instant, never this object's own live, mutable `_overrides`
dict -- so a PUT racing a print job can change what the *next* job sees,
never what a job already dispatched to a thread sees mid-print.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from labelmaker.config import AppConfig
from labelmaker.db.database import Database

logger = logging.getLogger(__name__)

# settings-table key prefix: an override for field `foo` lives under
# `"cfg.foo"`, so this KV table could hold other, unrelated keys (e.g.
# router_homebox.py's own "homebox_qr_base_url") without collision.
_DB_KEY_PREFIX = "cfg."

# DB-only fields (no AppConfig twin) and the value `effective()` reports
# when no override is stored -- there is no "env" tier for these, only
# "db" or "default" (see `provenance` below).
_DB_ONLY_DEFAULTS: dict[str, object] = {
    "keep_printer_awake": False,
    "keep_awake_interval_min": 5,
}


def _http_url_no_trailing_slash(value: str, *, field_name: str) -> str:
    """Shared with router_homebox.py's HomeBoxSettingsUpdate.qr_base_url
    validator (kept as a separate copy, not an import, so this module
    doesn't reach into an api/ router module -- but the rule is
    deliberately identical: http(s) only, trailing slash stripped, no
    embedded whitespace)."""
    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")) or value in ("http://", "https://"):
        raise ValueError(f"{field_name} must be an http(s) URL, e.g. https://homebox.example.com")
    if any(ch.isspace() for ch in value):
        raise ValueError(f"{field_name} must not contain whitespace")
    return value


class SettingsOverrides(BaseModel):
    """PUT /api/settings' request body: a partial map of `{field: value}`
    (every field optional) plus, via `model_fields_set`, the record of
    WHICH fields a caller actually touched -- `SettingsOverlay.set_many`
    reads that (not `is not None`) to tell "omitted, leave alone" apart
    from "explicitly sent null, clear the override". `extra="forbid"`
    turns an unknown key into a pydantic ValidationError (surfaced as a
    422 by the router) instead of being silently ignored.

    Field types mirror `AppConfig`'s own Literals/constraints exactly,
    with two deliberate additions: `els_tape_mm` gets real bounds here
    (AppConfig's own field has none) since this is the one place a human
    types the number directly, and the two DB-only fields
    (`keep_printer_awake`/`keep_awake_interval_min`) have no `AppConfig`
    counterpart at all.
    """

    model_config = ConfigDict(extra="forbid")

    printer_mode: Literal["mock", "usb"] | None = None
    printer_init_strategy: Literal["classic", "e310bt"] | None = None
    printer_bit_order: Literal["msb_first", "lsb_first"] | None = None
    printer_flip_pins: bool | None = None
    els_tape_mm: float | None = Field(default=None, ge=3.5, le=36)
    # max_length mirrors router_homebox.py's own HomeBoxSettingsUpdate.qr_base_url bound.
    homebox_url: str | None = Field(default=None, max_length=255)
    homebox_api_key: str | None = Field(default=None, max_length=500)
    keep_printer_awake: bool | None = None
    keep_awake_interval_min: int | None = Field(default=None, ge=1, le=60)

    @field_validator("homebox_url")
    @classmethod
    def _validate_homebox_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _http_url_no_trailing_slash(value, field_name="homebox_url")

    @field_validator("homebox_api_key")
    @classmethod
    def _validate_homebox_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("homebox_api_key must not be empty")
        return value


# The single source of truth for "which fields can be overridden at all" --
# api/router_settings.py's GET listing, PUT's unknown-key rejection (via
# SettingsOverrides itself), and this module's own effective()/provenance()
# all key off this same set, so a future field addition only ever means
# adding one line to SettingsOverrides above.
OVERRIDABLE_FIELDS: frozenset[str] = frozenset(SettingsOverrides.model_fields)


class EffectiveSettings(BaseModel):
    """An immutable (`frozen=True`) snapshot of every overridable field's
    CURRENT effective value -- override if set, else the AppConfig/env
    value, else (DB-only fields only) `_DB_ONLY_DEFAULTS`. See this
    module's docstring for why "frozen" matters (a worker thread must
    never observe a value changing mid-print)."""

    model_config = ConfigDict(frozen=True)

    printer_mode: Literal["mock", "usb"]
    printer_init_strategy: Literal["classic", "e310bt"]
    printer_bit_order: Literal["msb_first", "lsb_first"]
    printer_flip_pins: bool
    els_tape_mm: float
    homebox_url: str | None
    homebox_api_key: str | None
    keep_printer_awake: bool
    keep_awake_interval_min: int


class SettingsOverlay:
    """Construct via `await SettingsOverlay.create(cfg, db)` (main.py's
    lifespan, stored on `app.state.settings`) -- a plain `__init__` can't
    itself await the DB load this needs, so `create` is the real
    constructor; the bare `__init__` below only sets up empty state.
    """

    def __init__(self, cfg: AppConfig, db: Database) -> None:
        self._cfg = cfg
        self._db = db
        self._overrides: dict[str, object] = {}

    @classmethod
    async def create(cls, cfg: AppConfig, db: Database) -> SettingsOverlay:
        overlay = cls(cfg, db)
        await overlay._reload()
        return overlay

    async def _reload(self) -> None:
        """Loads stored overrides from `db`, re-validating each row against
        `SettingsOverrides`' field definition for it before trusting it.

        A row can go stale without ever going through `set_many` (and
        therefore without ever being validated against the CURRENT rules):
        hand-edited DB content, a downgrade to an older build after a
        newer one relaxed/tightened a field's constraints, or a future
        code change to `SettingsOverrides` itself (e.g. narrowing
        `printer_mode`'s Literal). Without this check, one bad row would
        make `effective()` raise `pydantic.ValidationError` on every
        request from process startup onward -- a single corrupt override
        bricking the whole app instead of just that one setting. A row
        that fails validation is dropped (logged as a warning) and that
        field silently falls back to its env/default value instead, same
        as if the row had never been stored at all.
        """
        rows = await self._db.all_settings()
        overrides: dict[str, object] = {}
        for key, value in rows.items():
            if not key.startswith(_DB_KEY_PREFIX):
                continue  # some other feature's own settings-table row (e.g. homebox_qr_base_url)
            field = key[len(_DB_KEY_PREFIX) :]
            if field not in OVERRIDABLE_FIELDS:
                continue
            try:
                validated = SettingsOverrides.model_validate({field: value})
            except ValidationError:
                logger.warning(
                    "settings_overlay: dropping invalid stored override %r=%r for field "
                    "%r (no longer a valid value) -- falling back to its env/default value",
                    key, value, field,
                )
                continue
            overrides[field] = getattr(validated, field)
        self._overrides = overrides

    def effective(self) -> EffectiveSettings:
        values: dict[str, object] = {}
        for field in OVERRIDABLE_FIELDS:
            if field in self._overrides:
                values[field] = self._overrides[field]
            elif field in _DB_ONLY_DEFAULTS:
                values[field] = _DB_ONLY_DEFAULTS[field]
            else:
                values[field] = getattr(self._cfg, field)
        return EffectiveSettings(**values)

    async def set_many(self, updates: dict[str, object]) -> None:
        """Validates the WHOLE update as one `SettingsOverrides` (unknown
        key or an invalid value for ANY field raises pydantic
        ValidationError -- the caller, api/router_settings.py's PUT
        handler, maps that to a 422 -- before touching the DB or the
        in-memory dict at all, so a batch that fails VALIDATION never
        applies partially). That atomicity guarantee covers validation
        only, though: once validation passes, each touched field below is
        written with its own separate `set_setting`/`delete_setting` call,
        not inside one DB transaction, so a multi-field batch is NOT
        atomic against a crash or process death mid-loop -- some fields
        could end up written and others not. Then, for each field the
        caller actually SENT (per `model_fields_set`, not `is not None`):
        `None` deletes the DB row and the in-memory override (reverts to
        env/default); any other value upserts both.
        """
        validated = SettingsOverrides.model_validate(updates)
        for field in validated.model_fields_set:
            value = getattr(validated, field)
            key = f"{_DB_KEY_PREFIX}{field}"
            if value is None:
                await self._db.delete_setting(key)
                self._overrides.pop(field, None)
            else:
                await self._db.set_setting(key, value)
                self._overrides[field] = value

    def provenance(self, field: str) -> Literal["db", "env", "default"]:
        """`"db"` when an override is currently stored; else `"env"` when
        `AppConfig` itself resolved that field from an explicitly-provided
        value (env var, dotenv, or an explicit constructor kwarg -- see
        `model_fields_set` on a pydantic-settings model); else
        `"default"` (the class's own hardcoded default, or -- for the two
        DB-only fields, which have no `AppConfig` field at all --
        `_DB_ONLY_DEFAULTS`)."""
        if field not in OVERRIDABLE_FIELDS:
            raise ValueError(f"unknown settings field: {field!r}")
        if field in self._overrides:
            return "db"
        if field in _DB_ONLY_DEFAULTS:
            return "default"
        if field in self._cfg.model_fields_set:
            return "env"
        return "default"
