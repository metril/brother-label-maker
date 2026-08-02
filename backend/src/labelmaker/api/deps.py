"""FastAPI dependency accessors: pull the shared objects lifespan put on
`app.state` (config/db/bus/queue -- see main.create_app) into route handlers
via `Depends()`, instead of every route reaching into `request.app.state`
directly.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from labelmaker.config import AppConfig
from labelmaker.db.database import Database
from labelmaker.homebox import HomeBoxClient
from labelmaker.jobs.events import EventBus
from labelmaker.settings_overlay import SettingsOverlay


def get_app_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_queue(request: Request) -> asyncio.Queue[str]:
    return request.app.state.queue


def get_settings_overlay(request: Request) -> SettingsOverlay:
    return request.app.state.settings


def get_keepalive_status(request: Request) -> dict:
    """commit 6: the optional keep-awake poller's own live status dict
    (jobs/keepalive.py's `run_keepalive` mutates it in place; main.py's
    lifespan creates it before that task's first loop iteration runs) --
    surfaced additively on GET /api/printer/status (router_printer.py)."""
    return request.app.state.keepalive_status


def get_homebox(request: Request) -> HomeBoxClient:
    """503 (not 404) when unconfigured: the route exists, the deployment
    just hasn't been given HOMEBOX_URL/HOMEBOX_API_KEY -- the message says
    exactly that so the fix is obvious from the error alone. Routes that
    must answer 200 even when unconfigured (GET /api/homebox/status) skip
    this dependency and check the config themselves."""
    client = request.app.state.homebox
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "HomeBox integration is not configured -- set HOMEBOX_URL and "
                "HOMEBOX_API_KEY (an hb_-prefixed API key) in the environment"
            ),
        )
    return client


AppConfigDep = Annotated[AppConfig, Depends(get_app_config)]
DbDep = Annotated[Database, Depends(get_db)]
BusDep = Annotated[EventBus, Depends(get_bus)]
QueueDep = Annotated["asyncio.Queue[str]", Depends(get_queue)]
HomeBoxDep = Annotated[HomeBoxClient, Depends(get_homebox)]
SettingsDep = Annotated[SettingsOverlay, Depends(get_settings_overlay)]
KeepaliveStatusDep = Annotated[dict, Depends(get_keepalive_status)]


def error_message(exc: Exception) -> str:
    """A 422 detail string that's actually readable.

    `KeyError.__str__` returns `repr(args[0])` when there's exactly one arg
    (a `str.__repr__`-quoted, backslash-escaped mess for our
    "unknown X; valid: [...]" messages) -- `ValueError.__str__` (and its
    subclass `pydantic.ValidationError`) returns `args[0]` as-is. Both the
    render registry (get_renderer/render_definition) and Tape.resolve() raise
    exactly one of these two types with a single human-readable string arg,
    so unwrapping KeyError's arg directly (instead of calling `str()` on the
    exception) is what actually surfaces that message unmangled.
    """
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)
