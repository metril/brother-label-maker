"""GET/PUT /api/settings (task 4.5): the in-app-editable settings surface.

Replaces the old read-only GET /api/settings/runtime allowlist with a
generic view over `settings_overlay.SettingsOverlay` -- every field
`SettingsOverrides` (settings_overlay.py) declares is listed here as one
editable row (`{key, value, source, editable: true}`), PLUS a handful of
read-only, informational rows sourced straight from `AppConfig` (`editable:
false`) so an operator can still see what an env-only setting is set to.

Still an ALLOWLIST, not a config dump: `_READONLY_FIELDS` below is a
short, explicit, reviewed list -- never oidc_*, session_*, or the RAW
`homebox_api_key` value (the api key NEVER appears as a `value` under any
circumstance, editable row or not; see `homebox_api_key`'s special-cased
`set: bool` row below). `homebox_url` is a normal editable row like any
other -- its actual value IS returned, since a URL by itself isn't a
secret. `test_api_settings.py` asserts the full response key set with `==`
(not just "contains"), so adding a field here later is a conscious,
reviewed decision, not an accidental leak.

PUT /api/settings accepts a partial `{field: value | null}` map, applies it
via `SettingsOverlay.set_many` (422 on an unknown key or an invalid value --
built from pydantic's own per-field `exc.errors()`, NOT the shared
`error_message()` helper other routes use, because that helper's message
embeds the rejected `input_value` -- a malformed `homebox_api_key` would
otherwise echo the secret straight back into the 422 body), and returns the
SAME shape GET returns. When the update touches `homebox_url`/`homebox_api_key`,
`app.state.homebox` is rebuilt from the new effective values (mirrors
main.py's own lifespan construction) so the change takes effect
immediately, with no restart -- the OLD client (if any) is closed only
AFTER the new one is in place, so `app.state.homebox` never observes a gap
with no client at all. That ordering does NOT make the swap seamless for a
request already in flight against the old client, though -- closing it
tears down its connection pool, so a concurrent in-flight HomeBox request
may fail once during the swap (see put_settings' own comment). Acceptable
for this single-operator app.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from labelmaker.api.deps import AppConfigDep, SettingsDep
from labelmaker.config import AppConfig
from labelmaker.homebox import build_client
from labelmaker.settings_overlay import SettingsOverlay, SettingsOverrides

router = APIRouter(prefix="/settings", tags=["settings"])

# Declaration order of SettingsOverrides' own fields (a plain dict, so this
# is insertion-ordered and stable -- unlike the `OVERRIDABLE_FIELDS`
# frozenset those fields are also collected into) -- used only to give the
# GET listing a fixed, human-friendly row order.
_FIELD_ORDER = tuple(SettingsOverrides.model_fields)

# Read-only, informational rows: env-derived AppConfig fields an operator
# should be able to SEE without shelling into the container, but that
# aren't (yet, or ever) safe/sensible to flip from this UI. `printer_mode`
# is deliberately NOT here -- it's one of the editable overridable fields
# above (see settings_overlay.SettingsOverrides). Nothing that could double
# as a credential ever belongs in this tuple. `els_enabled` is ALSO
# deliberately not here (task 4.5 Track A) -- it's a plain bool, not a
# secret, and now flows through the normal editable-row path above like
# `els_tape_mm` already did.
_READONLY_FIELDS = ("auth_mode", "data_dir", "cors_origins")


def _cfg_source(config: AppConfig, field: str) -> str:
    """`"env"` when AppConfig itself resolved `field` from an explicitly
    provided value (env var/dotenv/constructor kwarg -- see
    `model_fields_set` on a pydantic-settings model); `"default"`
    otherwise (the class's own hardcoded default)."""
    return "env" if field in config.model_fields_set else "default"


def _settings_payload(config: AppConfig, settings: SettingsOverlay) -> dict:
    effective = settings.effective()
    rows: list[dict[str, Any]] = []

    for field in _FIELD_ORDER:
        source = settings.provenance(field)
        if field == "homebox_api_key":
            # NEVER a `value` key here, under any provenance -- only
            # whether one is currently set (db override OR env), so the
            # Settings page can render "Key set"/"Not set" without this
            # route ever echoing the secret itself back to the browser.
            rows.append({"key": field, "set": bool(effective.homebox_api_key),
                         "source": source, "editable": True})
        else:
            rows.append({"key": field, "value": getattr(effective, field),
                         "source": source, "editable": True})

    for field in _READONLY_FIELDS:
        value = str(config.data_dir) if field == "data_dir" else getattr(config, field)
        rows.append({"key": field, "value": value,
                     "source": _cfg_source(config, field), "editable": False})

    return {"settings": rows}


@router.get("")
async def get_settings(config: AppConfigDep, settings: SettingsDep) -> dict:
    return _settings_payload(config, settings)


@router.put("")
async def put_settings(
    body: dict[str, Any], config: AppConfigDep, settings: SettingsDep, request: Request
) -> dict:
    try:
        await settings.set_many(body)
    except ValidationError as exc:
        # Built from `exc.errors()` (`e["msg"]` only) rather than the
        # shared `error_message()` helper -- that helper's str(exc) form
        # embeds pydantic's own `input_value=...` for each error, which for
        # a malformed `homebox_api_key` submission means the secret itself
        # would come straight back in this 422 body (and the frontend
        # renders `detail` verbatim). `e["msg"]` carries no input value.
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors()
        )
        raise HTTPException(status_code=422, detail=detail) from exc

    if "homebox_url" in body or "homebox_api_key" in body:
        # Build the new client BEFORE closing the old one, so
        # `app.state.homebox` never observes a moment with no client at all
        # when one side of the pair is genuinely still configured. This
        # does NOT make the swap seamless for a request already in flight
        # against `old_client`, though: `old_client.close()` calls
        # `httpx.AsyncClient.aclose()`, which tears down that client's own
        # connection pool -- a concurrent in-flight HomeBox request racing
        # this PUT may fail once (its connection torn out from under it)
        # rather than complete against the old client. Acceptable for this
        # single-operator app: settings changes are rare, deliberate
        # actions, not a hot path some other request is likely to be
        # racing.
        old_client = request.app.state.homebox
        effective = settings.effective()
        request.app.state.homebox = build_client(effective.homebox_url, effective.homebox_api_key)
        if old_client is not None:
            await old_client.close()

    return _settings_payload(config, settings)
