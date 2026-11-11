"""A DB-backed overlay over `AppConfig` (task 4.5): lets an operator change a
small, curated set of settings from the running app (Settings page ->
GET/PUT /api/settings, api/router_settings.py) without restarting the container.

`AppConfig` (config.py) stays the single source of hardcoded defaults (these
fields are not read from the environment) and is never mutated -- this module
adds a second, DB-backed layer ON TOP of it.
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

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
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


class SettingsConflictError(ValueError):
    """The update is valid field by field but inconsistent as a whole
    (remote mode without a bridge address/certificate). The settings router
    maps it to a 422, like a ValidationError."""


class OidcNotVerifiedError(SettingsConflictError):
    """auth_mode=oidc requested (or kept) with an OIDC config that has not
    passed a test login. The settings router maps it to a 409."""


# Own DB keys (outside the `cfg.` overlay namespace; never exposed by GET).
SESSION_SECRET_KEY = "auth.session_secret"
OIDC_VERIFIED_KEY = "auth.oidc_verified"
_OIDC_FIELDS = ("oidc_issuer", "oidc_client_id", "oidc_client_secret", "oidc_scopes")
# Fields that only a session user may change while oidc is active.
PROTECTED_FIELDS = frozenset({"auth_mode", "cors_origins", *_OIDC_FIELDS})
_ORIGIN_RE = re.compile(r"^https?://[^/\s?#]+$")


def oidc_config_hash(issuer: object, client_id: object, secret: object, scopes: object) -> str:
    """Digest of the OIDC config a test login verified (marker value)."""
    raw = json.dumps([issuer, client_id, secret, scopes])
    return hashlib.sha256(raw.encode()).hexdigest()


_REMOTE_FIELDS = frozenset({"printer_mode", "printer_bridge_address", "printer_bridge_cert"})


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

    printer_mode: Literal["mock", "usb", "remote"] | None = Field(
        default=None,
        description="Transport: mock, usb, or remote (Raspberry Pi bridge)",
    )
    printer_bridge_address: str | None = Field(
        default=None,
        max_length=255,
        description="Bridge host or host:port (remote mode)",
    )
    printer_bridge_cert: str | None = Field(
        default=None,
        max_length=8000,
        description="Pinned bridge public certificate, PEM (remote mode)",
    )
    printer_init_strategy: Literal["classic", "e310bt"] | None = Field(
        default=None,
        description="Printer init sequence: classic or e310bt",
    )
    printer_bit_order: Literal["msb_first", "lsb_first"] | None = Field(
        default=None,
        description="Raster bit order: msb_first or lsb_first",
    )
    printer_flip_pins: bool | None = Field(
        default=None,
        description="Mirror the print-head pin order",
    )
    # task 4.5 Track A: was a startup-only AppConfig field (main.py used to
    # decide whether to even register router_els's routes from it once, at
    # process start) -- now DB-editable like everything else here, checked
    # per-request instead (router_els.py's get_els_label), so flipping it
    # from the Settings page takes effect without a restart.
    els_enabled: bool | None = Field(
        default=None,
        description="Serve the unauthenticated ELS label endpoint",
    )
    els_tape_mm: float | None = Field(
        default=None,
        ge=3.5,
        le=36,
        description="Tape width (mm) ELS labels are rendered for",
    )
    # max_length mirrors router_homebox.py's own HomeBoxSettingsUpdate.qr_base_url bound.
    homebox_url: str | None = Field(
        default=None,
        max_length=255,
        description="HomeBox base URL (http/https)",
    )
    homebox_api_key: str | None = Field(
        default=None,
        max_length=500,
        description="HomeBox API key (write-only; never returned)",
    )
    homebox_writes_enabled: bool | None = Field(
        default=None,
        description="Allow creating HomeBox entities/attachments",
    )
    auth_mode: Literal["none", "oidc"] | None = Field(
        default=None,
        description="Authentication: none, or oidc (requires a successful test login first)",
    )
    oidc_issuer: str | None = Field(
        default=None, max_length=255, description="OIDC issuer URL (http/https)"
    )
    oidc_client_id: str | None = Field(default=None, max_length=255, description="OIDC client id")
    oidc_client_secret: str | None = Field(
        default=None,
        max_length=500,
        description="OIDC client secret (write-only; never returned)",
    )
    oidc_scopes: str | None = Field(
        default=None, max_length=255, description="Space-separated OIDC scopes; must include openid"
    )
    session_max_age_s: int | None = Field(
        default=None, ge=300, le=30 * 24 * 3600, description="Session lifetime in seconds"
    )
    session_cookie_secure: bool | None = Field(
        default=None, description="Mark the session cookie Secure (serve over HTTPS)"
    )
    cors_origins: list[str] | None = Field(
        default=None, max_length=50, description="Allowed browser origins (scheme://host[:port])"
    )
    keep_printer_awake: bool | None = Field(
        default=None,
        description="Periodically poll the printer to keep it awake",
    )
    keep_awake_interval_min: int | None = Field(
        default=None,
        ge=1,
        le=60,
        description="Keep-awake poll interval in minutes",
    )

    @field_validator("homebox_url")
    @classmethod
    def _validate_homebox_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _http_url_no_trailing_slash(value, field_name="homebox_url")

    @field_validator("printer_bridge_address")
    @classmethod
    def _validate_bridge_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from labelmaker.driver.bridge_protocol import parse_address

        value = value.strip()
        parse_address(value)  # raises ValueError with a clear message
        return value

    @field_validator("printer_bridge_cert")
    @classmethod
    def _validate_bridge_cert(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from labelmaker.driver.bridge_identity import cert_pem_to_der

        cert_pem_to_der(value)  # exactly one X.509 cert, never a private key
        return value.strip() + "\n"

    @field_validator("oidc_issuer")
    @classmethod
    def _validate_oidc_issuer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _http_url_no_trailing_slash(value, field_name="oidc_issuer")

    @field_validator("oidc_client_id", "oidc_client_secret")
    @classmethod
    def _validate_oidc_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("oidc_scopes")
    @classmethod
    def _validate_oidc_scopes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if "openid" not in value.split():
            raise ValueError("oidc_scopes must include 'openid'")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [v.strip().rstrip("/") for v in value]
        for origin in cleaned:
            if not _ORIGIN_RE.match(origin):
                raise ValueError(
                    "cors_origins entries must be http(s) origins like https://labels.example.com"
                )
        return list(dict.fromkeys(cleaned))

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

    printer_mode: Literal["mock", "usb", "remote"]
    printer_bridge_address: str | None
    printer_bridge_cert: str | None
    printer_init_strategy: Literal["classic", "e310bt"]
    printer_bit_order: Literal["msb_first", "lsb_first"]
    printer_flip_pins: bool
    els_enabled: bool
    els_tape_mm: float
    homebox_url: str | None
    homebox_api_key: str | None
    homebox_writes_enabled: bool
    auth_mode: Literal["none", "oidc"]
    oidc_issuer: str | None
    oidc_client_id: str | None
    oidc_client_secret: str | None
    oidc_scopes: str
    session_max_age_s: int
    session_cookie_secure: bool
    cors_origins: list[str]
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
        self.session_secret: str = ""
        self._oidc_verified: str | None = None
        # Awaited after every successful change (main.py rebuilds the
        # runtime auth/CORS snapshot here).
        self.on_change: Callable[[], Awaitable[None]] | None = None

    @classmethod
    async def create(cls, cfg: AppConfig, db: Database) -> SettingsOverlay:
        overlay = cls(cfg, db)
        await overlay._reload()
        secret = await db.get_setting(SESSION_SECRET_KEY)
        if not isinstance(secret, str) or len(secret) < 32:
            secret = secrets.token_hex(32)
            await db.set_setting(SESSION_SECRET_KEY, secret)
        overlay.session_secret = secret
        overlay._oidc_verified = await db.get_setting(OIDC_VERIFIED_KEY)
        return overlay

    def oidc_verified(self) -> bool:
        """True iff the marker matches the CURRENT effective OIDC config."""
        e = self.effective()
        return self._oidc_verified == oidc_config_hash(
            e.oidc_issuer, e.oidc_client_id, e.oidc_client_secret, e.oidc_scopes
        )

    async def rotate_session_secret(self) -> None:
        """New signing secret: every existing session cookie stops verifying."""
        self.session_secret = secrets.token_hex(32)
        await self._db.set_setting(SESSION_SECRET_KEY, self.session_secret)
        if self.on_change:
            await self.on_change()

    async def save_verified_oidc(
        self, issuer: str, client_id: str, secret: str, scopes: str
    ) -> None:
        """Persist an OIDC config that just passed a test login, plus its marker."""
        validated = SettingsOverrides(
            oidc_issuer=issuer,
            oidc_client_id=client_id,
            oidc_client_secret=secret,
            oidc_scopes=scopes,
        )
        for field in _OIDC_FIELDS:
            value = getattr(validated, field)
            await self._db.set_setting(f"{_DB_KEY_PREFIX}{field}", value)
            self._overrides[field] = value
        e = self.effective()
        self._oidc_verified = oidc_config_hash(
            e.oidc_issuer, e.oidc_client_id, e.oidc_client_secret, e.oidc_scopes
        )
        await self._db.set_setting(OIDC_VERIFIED_KEY, self._oidc_verified)
        if self.on_change:
            await self.on_change()

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
        if validated.model_fields_set & _REMOTE_FIELDS:
            # Validate the merged result, not just the request, so changing
            # one field can't leave remote mode half-configured.
            merged = self.effective().model_dump()
            for field in validated.model_fields_set & _REMOTE_FIELDS:
                value = getattr(validated, field)
                if value is None:
                    value = getattr(self._cfg, field)  # null reverts to env/default
                merged[field] = value
            if merged["printer_mode"] == "remote" and not (
                merged["printer_bridge_address"] and merged["printer_bridge_cert"]
            ):
                raise SettingsConflictError(
                    "remote printer mode needs both printer_bridge_address and "
                    "printer_bridge_cert"
                )
        sent = validated.model_fields_set
        if sent & (PROTECTED_FIELDS - {"cors_origins"}):
            merged = self.effective().model_dump()
            for field in sent & PROTECTED_FIELDS:
                value = getattr(validated, field)
                merged[field] = getattr(self._cfg, field) if value is None else value
            if merged["auth_mode"] == "oidc":
                if not (
                    merged["oidc_issuer"]
                    and merged["oidc_client_id"]
                    and merged["oidc_client_secret"]
                ):
                    raise OidcNotVerifiedError(
                        "oidc needs issuer, client id and client secret, then a test login"
                    )
                digest = oidc_config_hash(
                    merged["oidc_issuer"],
                    merged["oidc_client_id"],
                    merged["oidc_client_secret"],
                    merged["oidc_scopes"],
                )
                if digest != self._oidc_verified:
                    raise OidcNotVerifiedError(
                        "the OIDC settings have not passed a test login; run Test login first"
                    )
        for field in sent:
            value = getattr(validated, field)
            key = f"{_DB_KEY_PREFIX}{field}"
            if value is None:
                await self._db.delete_setting(key)
                self._overrides.pop(field, None)
            else:
                await self._db.set_setting(key, value)
                self._overrides[field] = value
        if sent & set(_OIDC_FIELDS) and not self.oidc_verified():
            self._oidc_verified = None
            await self._db.delete_setting(OIDC_VERIFIED_KEY)
        if self.on_change:
            await self.on_change()

    def provenance(self, field: str) -> Literal["db", "default"]:
        """`"db"` when an override is currently stored; else `"default"`.
        Overridable fields have no env tier any more (config.py's
        ENV_FIELDS), so AppConfig's value for them is always a hardcoded
        default -- or, in tests only, a constructor kwarg."""
        if field not in OVERRIDABLE_FIELDS:
            raise ValueError(f"unknown settings field: {field!r}")
        return "db" if field in self._overrides else "default"
