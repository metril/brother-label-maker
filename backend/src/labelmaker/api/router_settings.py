"""GET /api/settings/runtime (task 4.2): a read-only view of the
env-derived config an operator can actually SEE from the Settings page,
without shelling into the container to read `docker compose config` or the
process environment directly.

This is an ALLOWLIST, not a config dump -- exactly the fields named in the
task brief (printer_mode, printer_init_strategy, printer_bit_order,
printer_flip_pins, els_enabled, els_tape_mm, auth_mode, homebox_configured)
and NOTHING that could double as a credential: never homebox_api_key,
oidc_client_secret, or session_secret (see config.py's AppConfig for what
each of those actually guards). test_api_settings.py asserts the full
response key set with `==` (not just "contains"), so adding a new field
here later is a conscious, reviewed decision, not an accidental leak.

`homebox_configured` is deliberately a bool, not the URL/key themselves --
mirrors router_homebox.py's own `configured` flag in GET /api/homebox/status,
just derived from config directly rather than round-tripping through that
route.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from labelmaker.api.deps import AppConfigDep

router = APIRouter(prefix="/settings", tags=["settings"])


class RuntimeSettings(BaseModel):
    printer_mode: Literal["mock", "usb"]
    printer_init_strategy: Literal["classic", "e310bt"]
    printer_bit_order: Literal["msb_first", "lsb_first"]
    printer_flip_pins: bool
    els_enabled: bool
    els_tape_mm: float
    auth_mode: Literal["none", "oidc"]
    homebox_configured: bool


@router.get("/runtime")
async def runtime_settings(config: AppConfigDep) -> RuntimeSettings:
    return RuntimeSettings(
        printer_mode=config.printer_mode,
        printer_init_strategy=config.printer_init_strategy,
        printer_bit_order=config.printer_bit_order,
        printer_flip_pins=config.printer_flip_pins,
        els_enabled=config.els_enabled,
        els_tape_mm=config.els_tape_mm,
        auth_mode=config.auth_mode,
        homebox_configured=bool(config.homebox_url and config.homebox_api_key),
    )
