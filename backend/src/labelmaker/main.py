"""FastAPI app factory: lifespan (db/event bus/print worker), CORS, routers,
and an optional SPA static mount. Boots for real via
`uv run uvicorn labelmaker.main:app` (module-level `app` below).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from labelmaker.api import (
    router_auth,
    router_els,
    router_gallery,
    router_history,
    router_homebox,
    router_images,
    router_labels,
    router_presets,
    router_print,
    router_printer,
    router_settings,
    ws,
)
from labelmaker.api.auth_gate import AuthGateMiddleware
from labelmaker.config import AppConfig, get_config
from labelmaker.db.database import Database
from labelmaker.homebox import HomeBoxClient
from labelmaker.jobs.events import EventBus
from labelmaker.jobs.worker import run_worker

# The session cookie's own name -- distinct from Starlette's generic
# "session" default so it reads unambiguously in browser devtools/a proxy
# log as belonging to this app specifically.
_SESSION_COOKIE_NAME = "lm_session"

# Task 4.2 (diagnostics page's "App" section): the installed package
# version, read from this project's own pyproject.toml via importlib
# metadata rather than a hand-duplicated string constant that could drift
# from it. Computed once at import time (static for the life of the
# process) -- PackageNotFoundError only happens if labelmaker somehow isn't
# installed at all (shouldn't happen for `uv run`, which installs the
# project in editable mode), and "0.0.0-dev" says so honestly rather than
# guessing a real-looking version number.
try:
    APP_VERSION = _pkg_version("labelmaker")
except PackageNotFoundError:
    APP_VERSION = "0.0.0-dev"


def _require_oidc_config(cfg: AppConfig) -> None:
    """Fails FAST -- at create_app time, i.e. at process startup for the
    real server entry point below, never on the first browser hit to
    `/api/auth/login` -- when `AUTH_MODE=oidc` is missing any setting the
    flow cannot function without. See config.py's `AppConfig` for what each
    of these actually configures.
    """
    missing = [
        env_name
        for env_name, value in (
            ("OIDC_ISSUER", cfg.oidc_issuer),
            ("OIDC_CLIENT_ID", cfg.oidc_client_id),
            ("OIDC_CLIENT_SECRET", cfg.oidc_client_secret),
            ("SESSION_SECRET", cfg.session_secret),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "AUTH_MODE=oidc requires the following environment variable(s) to be "
            f"set: {', '.join(missing)} (see config.py's AppConfig for what each one "
            "configures; SESSION_SECRET wants >=32 random chars, e.g. "
            "`openssl rand -hex 32`)"
        )
    # Without "openid" authlib treats this as plain OAuth2: no nonce, and --
    # far worse -- NO id_token signature/iss/aud/exp verification at all,
    # while the callback still 302s like a success (review). Fail here, at
    # startup, with the reason spelled out.
    if "openid" not in (cfg.oidc_scopes or "").split():
        raise ValueError(
            f"OIDC_SCOPES must include 'openid' (got {cfg.oidc_scopes!r}) -- without "
            "it the id_token is never verified and sign-in cannot complete"
        )


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
    if cfg.auth_mode == "oidc":
        _require_oidc_config(cfg)

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

    # In oidc mode the interactive API docs are withheld entirely (review):
    # the gate only covers /api/*, and FastAPI's own /docs + /openapi.json
    # would otherwise hand an unauthenticated caller the complete API
    # surface in a locked-down deployment.
    if cfg.auth_mode == "oidc":
        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    else:
        app = FastAPI(lifespan=lifespan)

    # Auth (task 4.1) -- ONLY added in oidc mode, so `auth_mode == "none"`
    # (the default) never runs a byte of this: no SessionMiddleware, no
    # gate, request/response behavior identical to every pre-4.1 release.
    #
    # Registration order matters: Starlette's `add_middleware` is LIFO (the
    # LAST-added ends up OUTERMOST -- see Starlette.build_middleware_stack),
    # so registering AuthGateMiddleware, then SessionMiddleware, THEN
    # CORSMiddleware last produces this actual per-request order:
    #
    #     CORS -> Session -> AuthGate -> routing -> the endpoint
    #
    # CORS outermost means a 401 the gate manufactures still gets
    # Access-Control-* headers on the way back out (otherwise a
    # cross-origin dev frontend couldn't even read the 401 body). Session
    # running before AuthGate means `scope["session"]` is already decoded
    # by the time the gate reads it, for both "http" and "websocket" scopes
    # (see auth_gate.py's own docstring for the full reasoning).
    if cfg.auth_mode == "oidc":
        app.state.oauth = router_auth.build_oauth_client(cfg)
        app.add_middleware(AuthGateMiddleware)
        app.add_middleware(
            SessionMiddleware,
            secret_key=cfg.session_secret,
            session_cookie=_SESSION_COOKIE_NAME,
            # Cookie max_age and the server-side deadline router_auth stores
            # come from the SAME config field, so they can't disagree.
            max_age=cfg.session_max_age_s,
            https_only=cfg.session_cookie_secure,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict:
        # `version` (task 4.2): additive field -- this app's own installed
        # version, so the diagnostics page can show it next to backend
        # reachability without a separate build-info endpoint.
        return {"status": "ok", "printer_mode": cfg.printer_mode, "version": APP_VERSION}

    # Registered in every mode -- /api/auth/me must answer 200 even in
    # "none" mode (see router_auth.py's own docstring), and the auth gate
    # itself exempts the whole /api/auth/* prefix so login/callback/logout
    # stay reachable by a not-yet-signed-in session.
    app.include_router(router_auth.router, prefix="/api")
    app.include_router(router_labels.router, prefix="/api")
    app.include_router(router_gallery.router, prefix="/api")
    app.include_router(router_images.router, prefix="/api")
    app.include_router(router_print.router, prefix="/api")
    app.include_router(router_printer.router, prefix="/api")
    app.include_router(router_presets.router, prefix="/api")
    app.include_router(router_history.router, prefix="/api")
    app.include_router(router_homebox.router, prefix="/api")
    app.include_router(router_settings.router, prefix="/api")
    # Unauthenticated by design (HomeBox's ELS caller sends no auth, see
    # router_els.py's module docstring) -- registered only when an operator
    # opts in, so a disabled deployment 404s (the route doesn't exist) not
    # 503s (the route exists but refuses).
    if cfg.els_enabled:
        app.include_router(router_els.router, prefix="/api")
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
