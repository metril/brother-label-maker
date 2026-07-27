"""FastAPI dependency accessors: pull the shared objects lifespan put on
`app.state` (config/db/bus/queue -- see main.create_app) into route handlers
via `Depends()`, instead of every route reaching into `request.app.state`
directly.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, Request

from labelmaker.config import AppConfig
from labelmaker.db.database import Database
from labelmaker.jobs.events import EventBus


def get_app_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_queue(request: Request) -> asyncio.Queue[str]:
    return request.app.state.queue


AppConfigDep = Annotated[AppConfig, Depends(get_app_config)]
DbDep = Annotated[Database, Depends(get_db)]
BusDep = Annotated[EventBus, Depends(get_bus)]
QueueDep = Annotated["asyncio.Queue[str]", Depends(get_queue)]


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
