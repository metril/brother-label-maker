"""FastAPI app factory: lifespan (db/event bus/print worker), CORS, routers,
and an optional SPA static mount. Boots for real via
`uv run uvicorn labelmaker.main:app` (module-level `app` below).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from labelmaker.api import (
    router_history,
    router_images,
    router_labels,
    router_presets,
    router_print,
    router_printer,
    ws,
)
from labelmaker.config import AppConfig, get_config
from labelmaker.db.database import Database
from labelmaker.jobs.events import EventBus
from labelmaker.jobs.worker import run_worker


def _resolve_static_dir() -> Path | None:
    """`frontend/dist`, resolved relative to the repo root (not cwd) so
    `uv run uvicorn ...` works the same from any directory -- overridable via
    STATIC_DIR for deployment shapes where the built frontend doesn't sit
    next to `backend/` (e.g. a Docker image). Returns None (no mount) if
    neither exists, which is the expected state until the frontend task
    ships a build -- the API must boot standalone either way.
    """
    override = os.environ.get("STATIC_DIR")
    if override:
        candidate = Path(override)
    else:
        # backend/src/labelmaker/main.py -> parents[3] == repo root.
        repo_root = Path(__file__).resolve().parents[3]
        candidate = repo_root / "frontend" / "dist"
    return candidate if candidate.is_dir() else None


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config if config is not None else get_config()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        (cfg.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        db = await Database.open(cfg.data_dir / "labelmaker.db")
        bus = EventBus()
        queue: asyncio.Queue[str] = asyncio.Queue()

        app.state.config = cfg
        app.state.db = db
        app.state.bus = bus
        app.state.queue = queue

        worker_task = asyncio.create_task(run_worker(app.state))
        try:
            yield
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
            await db.close()

    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "printer_mode": cfg.printer_mode}

    app.include_router(router_labels.router, prefix="/api")
    app.include_router(router_images.router, prefix="/api")
    app.include_router(router_print.router, prefix="/api")
    app.include_router(router_printer.router, prefix="/api")
    app.include_router(router_presets.router, prefix="/api")
    app.include_router(router_history.router, prefix="/api")
    app.include_router(ws.router, prefix="/api")

    # Mounted last (after every /api/* route is registered) so it only ever
    # catches paths none of the API routers matched -- see StaticFiles(
    # html=True)'s own docs for what "SPA fallback" does and doesn't cover;
    # full deep-link fallback beyond that lands with the frontend task.
    static_dir = _resolve_static_dir()
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
