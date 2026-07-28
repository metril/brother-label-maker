"""FastAPI app factory: lifespan (db/event bus/print worker), CORS, routers,
and an optional SPA static mount. Boots for real via
`uv run uvicorn labelmaker.main:app` (module-level `app` below).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from labelmaker.api import (
    router_gallery,
    router_history,
    router_homebox,
    router_images,
    router_labels,
    router_presets,
    router_print,
    router_printer,
    ws,
)
from labelmaker.config import AppConfig, get_config
from labelmaker.db.database import Database
from labelmaker.homebox import HomeBoxClient
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
        # None when unconfigured -- deps.get_homebox turns that into a 503
        # with a setup hint instead of a crash at startup.
        app.state.homebox = (
            HomeBoxClient(cfg.homebox_url, cfg.homebox_api_key)
            if cfg.homebox_url and cfg.homebox_api_key
            else None
        )

        worker_task = asyncio.create_task(run_worker(app.state))
        try:
            yield
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
            if app.state.homebox is not None:
                await app.state.homebox.close()
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
    app.include_router(router_gallery.router, prefix="/api")
    app.include_router(router_images.router, prefix="/api")
    app.include_router(router_print.router, prefix="/api")
    app.include_router(router_printer.router, prefix="/api")
    app.include_router(router_presets.router, prefix="/api")
    app.include_router(router_history.router, prefix="/api")
    app.include_router(router_homebox.router, prefix="/api")
    app.include_router(ws.router, prefix="/api")

    # Registered last (after every /api/* route above) so it only ever
    # catches paths none of the API routers matched -- Starlette tries
    # routes in registration order and stops at the first match, so a real
    # API endpoint always wins first.
    #
    # task 2.13 review fix-up: this used to be `app.mount("/",
    # StaticFiles(..., html=True))`, which -- confirmed live against a real
    # `frontend/dist` -- only special-cases the exact root path ("/") and a
    # directory-with-index.html; it does NOT fall back to index.html for an
    # arbitrary deep link with no file on disk (e.g. `/presets`, `/history`
    # -- react-router's BrowserRouter routes these client-side, but only
    # once the SPA has actually booted). Those 404'd instead, meaning a
    # hard refresh (or a bookmarked/shared link, or the Dockerfile's
    # shipped container shape -- STATIC_DIR=/app/static, docker/Dockerfile)
    # landing anywhere but "/" was broken. A `Mount("/")` also can't be
    # "layered" with a route registered after it -- once a path matches a
    # mount's prefix (and "/" is a prefix of everything), Starlette
    # delegates the ENTIRE response to that sub-app and never tries any
    # later route even if the sub-app 404s -- so the fix has to be this one
    # catch-all route instead of a second mount/route pair.
    #
    # `full_path` covers three cases: (1) `/api/...` that didn't match any
    # real router above -- explicitly re-raised as a 404 HTTPException
    # (FastAPI's normal JSON `{"detail": ...}` shape) so an unknown API
    # path never silently returns the SPA's index.html; (2) a real static
    # file that exists on disk (the JS/CSS bundle under `/assets`, the four
    # TTFs under `/fonts`, `/favicon.svg`, ...) -- served as itself; (3)
    # everything else (a client-side route, or the root path itself, where
    # `full_path` is "") -- served `index.html` so the SPA boots and its
    # OWN router (react-router) takes over from there.
    #
    # The resolved-path containment check (`static_dir.resolve() in
    # candidate.parents`) is a directory-traversal guard: `full_path` is
    # attacker-controlled request text, and `(static_dir / full_path)`
    # alone would follow a `..` segment right out of `static_dir` onto the
    # rest of the filesystem.
    #
    # Review fix-up (2nd round): `full_path` is entirely attacker-supplied
    # text, and `Path.resolve()`/`Path.is_file()` are NOT pure string
    # operations -- both make real filesystem/OS calls that can raise for
    # input that's syntactically fine as a URL path but not as a filesystem
    # path. Confirmed live (an A/B probe harness against both the old
    # StaticFiles mount and this route): `GET /%00` (an embedded NUL byte)
    # raised `ValueError` ("embedded null character") out of `.resolve()`,
    # and a >255-byte path segment (any scanner's own directory-brute-force
    # wordlist will eventually produce one) raised `OSError`
    # (`ENAMETOOLONG`) out of `.is_file()` -- both surfaced as an
    # unhandled-exception 500 with a stack trace, where the OLD mount (and
    # every genuinely nonexistent path here) 404/200-index.html'd instead.
    # Caught broadly and treated the SAME as "not a real file" -- fall
    # through to `index.html` -- rather than distinguishing the reason: the
    # SPA itself is the right place to render a "not found" for a path this
    # malformed, not a 500.
    static_dir = _resolve_static_dir()
    if static_dir is not None:
        static_root = static_dir.resolve()

        # Review fix-up (2nd round): `@app.get` only registers GET --
        # Starlette's StaticFiles mount it replaced auto-added HEAD (its
        # own `Route(..., methods=["GET", "HEAD"])`), so `HEAD /`,
        # `HEAD /favicon.svg`, `HEAD /assets/*.js` had regressed from 200
        # to 405 (confirmed live) -- breaking any uptime monitor or reverse
        # proxy that HEADs before GETing. `api_route` with both methods
        # restores that.
        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")

            try:
                candidate = (static_dir / full_path).resolve()
                is_real_file = candidate.is_file() and static_root in candidate.parents
            except (ValueError, OSError):
                is_real_file = False

            if is_real_file:
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
