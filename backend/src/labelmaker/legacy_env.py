"""One-time import of env vars that used to configure Settings-page fields.

Those fields are now edited on the Settings page only (DB overlay). If an
operator upgraded with the old env vars still in their compose file, silently
ignoring them would drop the app into mock mode and print jobs would
"succeed" without printing. So at startup each legacy var that is set and has
no stored override is validated and stored as an override, and one WARNING
names the var (never its value -- HOMEBOX_API_KEY is a secret) asking the
operator to delete it. A stored override always wins. Idempotent: once
stored, later starts only repeat the delete-it warning.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from pydantic import ValidationError

from labelmaker.settings_overlay import SettingsConflictError, SettingsOverlay, SettingsOverrides

logger = logging.getLogger(__name__)

LEGACY_ENV_FIELDS: dict[str, str] = {
    "PRINTER_MODE": "printer_mode",
    "PRINTER_BRIDGE_ADDRESS": "printer_bridge_address",
    "PRINTER_BRIDGE_CERT": "printer_bridge_cert",
    "PRINTER_INIT_STRATEGY": "printer_init_strategy",
    "PRINTER_BIT_ORDER": "printer_bit_order",
    "PRINTER_FLIP_PINS": "printer_flip_pins",
    "HOMEBOX_URL": "homebox_url",
    "HOMEBOX_API_KEY": "homebox_api_key",
    "HOMEBOX_WRITES_ENABLED": "homebox_writes_enabled",
    "ELS_ENABLED": "els_enabled",
    "ELS_TAPE_MM": "els_tape_mm",
}


async def import_legacy_env(
    settings: SettingsOverlay, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Imports legacy env vars; returns the env var names actually stored."""
    env = os.environ if environ is None else environ
    to_store: dict[str, object] = {}
    var_of: dict[str, str] = {}
    for var, field in LEGACY_ENV_FIELDS.items():
        raw = env.get(var)
        if raw is None or not raw.strip():
            continue
        if settings.provenance(field) == "db":
            logger.warning(
                "%s is set but %s is already stored on the Settings page; the env var is "
                "ignored -- delete it from your environment.",
                var,
                field,
            )
            continue
        try:
            value = getattr(SettingsOverrides.model_validate({field: raw}), field)
        except ValidationError:
            logger.warning("%s has an invalid value and was ignored (not imported).", var)
            continue
        to_store[field] = value
        var_of[field] = var

    async def store(updates: dict[str, object]) -> bool:
        try:
            await settings.set_many(updates)
        except (ValidationError, SettingsConflictError):
            return False
        return True

    if to_store and not await store(dict(to_store)):
        # Incomplete remote config: only the mode can conflict. Keep the rest
        # (address/cert alone are harmless) and warn about the mode.
        if "printer_mode" in to_store:
            logger.warning(
                "PRINTER_MODE was not imported: remote printer mode needs both the bridge "
                "address and certificate. Configure it on the Settings page.",
            )
            del to_store["printer_mode"]
        if to_store and not await store(dict(to_store)):
            for field in to_store:
                logger.warning("%s could not be imported.", var_of[field])
            to_store.clear()

    imported = [var_of[f] for f in to_store]
    for var in imported:
        logger.warning(
            "%s was imported once into the Settings page (stored in the DB). "
            "Delete this env var; it is no longer read.",
            var,
        )
    return imported
