"""FastAPI app factory: lifespan (db/event bus/print worker), CORS, routers,
and an optional SPA static mount. Boots for real via
`uv run uvicorn labelmaker.main:app` (module-level `app` below).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from labelmaker.api import (
    openapi_meta,
    router_api_keys,
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
from labelmaker.api.api_keys import WsTicketStore
from labelmaker.api.auth_gate import AuthGateMiddleware
from labelmaker.api.auth_runtime import (
    DynamicCORSMiddleware,
    DynamicSessionMiddleware,
    rebuild_runtime,
)
from labelmaker.api.errors import ApiError, err, register_error_handlers
from labelmaker.api.legacy import LegacyDeprecationMiddleware
from labelmaker.api.schemas import HealthOut
from labelmaker.config import AppConfig, get_config
from labelmaker.db.database import Database
from labelmaker.homebox import build_client
from labelmaker.jobs.events import EventBus
from labelmaker.jobs.keepalive import initial_keepalive_status, run_keepalive
from labelmaker.jobs.worker import run_worker
from labelmaker.paths import find_static_dir
from labelmaker.settings_overlay import SettingsOverlay

logger = logging.getLogger(__name__)

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


# Python's `mimetypes` table varies by platform/version (a minimal Docker
# image may have no /etc/mime.types at all), and browsers refuse
# `WebAssembly.instantiateStreaming` on anything but application/wasm (the
# QR scanner's zxing .wasm) and ignore a manifest not served as JSON-ish --
# so these two are pinned rather than guessed.
_STATIC_MEDIA_TYPES = {
    ".wasm": "application/wasm",
    ".webmanifest": "application/manifest+json",
}


_AUTO: Any = object()


def create_app(config: AppConfig | None = None, static_dir: Path | None = _AUTO) -> FastAPI:
    """`static_dir` defaults to `paths.find_static_dir()` (the built SPA);
    pass None to serve no SPA (tests, schema generation)."""
    cfg = config if config is not None else get_config()
    if static_dir is _AUTO:
        static_dir = find_static_dir()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        (cfg.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        db = await Database.open(cfg.data_dir / "labelmaker.db")
        # Review L2 follow-up: the print queue below is a fresh in-memory
        # asyncio.Queue every boot, so any row still 'queued'/'printing'
        # from a previous run (container restart or `kill -9` mid-print)
        # is dead by construction -- no worker will ever pick it up.
        # Reconciled to 'failed' HERE, before `queue`/the worker task even
        # exist, so this can never race a legitimately in-flight job (see
        # Database.fail_orphaned_jobs's own docstring for why that ordering
        # matters -- it's also what makes delete_job's status-guarded CAS
        # safe: an interrupted job becomes deletable again on next boot
        # instead of a permanent dead end).
        orphaned = await db.fail_orphaned_jobs()
        if orphaned:
            logger.info(
                "main: startup reconciliation marked %d orphaned job(s) as failed", orphaned
            )
        bus = EventBus()
        queue: asyncio.Queue[str] = asyncio.Queue()
        # task 4.5: the DB-backed settings overlay -- loads any stored
        # overrides from `db` immediately, so the very first request after
        # a restart already reflects them (see settings_overlay.py's own
        # docstring for the full contract).
        settings = await SettingsOverlay.create(cfg, db)

        app.state.config = cfg
        app.state.db = db
        app.state.bus = bus
        app.state.queue = queue
        app.state.settings = settings
        app.state.static_dir = static_dir
        rebuild_runtime(app)

        async def _on_settings_change() -> None:
            rebuild_runtime(app)

        settings.on_change = _on_settings_change
        # None when unconfigured -- deps.get_homebox turns that into a 503
        # with a setup hint instead of a crash at startup. Built from the
        # settings overlay's EFFECTIVE url/key, not `cfg` directly, so a
        # DB-stored override (api/router_settings.py's PUT handler) is
        # honored from the very first request after a restart too.
        effective = settings.effective()
        app.state.homebox = build_client(effective.homebox_url, effective.homebox_api_key)
        # commit 6: the optional keep-awake poller's own status, seeded
        # BEFORE run_keepalive's first loop iteration runs -- see
        # jobs/keepalive.py's initial_keepalive_status docstring.
        app.state.keepalive_status = initial_keepalive_status(effective.keep_printer_awake)

        worker_task = asyncio.create_task(run_worker(app.state))
        keepalive_task = asyncio.create_task(run_keepalive(app.state))
        try:
            yield
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
            keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive_task
            if app.state.homebox is not None:
                await app.state.homebox.close()
            await db.close()

    # /docs, /redoc and /openapi.json stay enabled in every mode; in oidc mode
    # the auth gate covers them (auth_gate.requires_auth), so an anonymous
    # caller cannot read the API surface.
    app = FastAPI(
        title="Label Maker API",
        version=APP_VERSION,
        description=openapi_meta.DESCRIPTION,
        openapi_tags=openapi_meta.TAGS,
        lifespan=lifespan,
    )
    register_error_handlers(app)
    openapi_meta.install(app)

    # Session, auth gate and CORS are always installed; each reads the
    # runtime snapshot (app.state.auth_rt, rebuilt on every settings change)
    # per request, so mode/origins switch without a restart. Registration
    # order is LIFO: the per-request order is
    #
    #     CORS -> GZip -> Session -> AuthGate -> routing -> the endpoint
    #
    # CORS outermost keeps Access-Control-* on a 401 the gate manufactures;
    # Session before AuthGate means `scope["session"]` is decoded when the
    # gate reads it (http and websocket alike).
    app.state.ws_tickets = WsTicketStore()
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(DynamicSessionMiddleware)

    # H5 (the 2026-08 code review): GET /api/symbols' ~1.5MB catalog (and
    # anything else this size or larger) went out uncompressed with no
    # reverse proxy in front to compensate (docker/docker-compose.yml sets
    # none). Registered here -- BEFORE the CORSMiddleware call below -- so
    # CORS stays outermost per the LIFO ordering explained above;
    # `minimum_size=1024` skips the gzip pass entirely for small responses
    # (most of this API) where compression overhead would outweigh the
    # savings.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(LegacyDeprecationMiddleware)

    app.add_middleware(DynamicCORSMiddleware)

    health_router = APIRouter()

    @health_router.get(
        "/health",
        tags=["health"],
        response_model=HealthOut,
        summary="Health check",
        responses=err(500),
    )
    async def health() -> HealthOut:
        """Liveness probe: app version and the effective printer mode."""
        # `version` (task 4.2): additive field -- this app's own installed
        # version, so the diagnostics page can show it next to backend
        # reachability without a separate build-info endpoint.
        #
        # `printer_mode` reads the settings overlay's EFFECTIVE value (via
        # `app.state.settings`, the same object router_settings.py's PUT
        # handler mutates), not `cfg.printer_mode` directly -- a DB
        # override set from the Settings page must be reflected here too,
        # not just in GET /api/printer/status, without a restart.
        printer_mode = app.state.settings.effective().printer_mode
        return HealthOut(status="ok", printer_mode=printer_mode, version=APP_VERSION)

    # Registered in every mode -- /api/auth/me must answer 200 even in
    # "none" mode (see router_auth.py's own docstring), and the auth gate
    # itself exempts the whole /api/auth/* prefix so login/callback/logout
    # stay reachable by a not-yet-signed-in session.
    def _mount_api(prefix: str, **kw: Any) -> None:
        app.include_router(router_auth.router, prefix=prefix, **kw)
        app.include_router(router_labels.router, prefix=prefix, **kw)
        app.include_router(router_gallery.router, prefix=prefix, **kw)
        app.include_router(router_images.router, prefix=prefix, **kw)
        app.include_router(router_print.router, prefix=prefix, **kw)
        app.include_router(router_printer.router, prefix=prefix, **kw)
        app.include_router(router_presets.router, prefix=prefix, **kw)
        app.include_router(router_history.router, prefix=prefix, **kw)
        app.include_router(router_homebox.router, prefix=prefix, **kw)
        app.include_router(router_settings.router, prefix=prefix, **kw)
        app.include_router(router_api_keys.router, prefix=prefix, **kw)
        # Unauthenticated by design (HomeBox's ELS caller sends no auth, see
        # router_els.py's module docstring) -- registered UNCONDITIONALLY (task
        # 4.5 Track A: els_enabled is now DB-editable from the Settings page, so
        # whether this route answers can no longer be decided once, here, at
        # process startup). The route itself checks the settings overlay's
        # EFFECTIVE els_enabled on every request instead (get_els_label's first
        # line) and 404s when it's off -- same contract as before (disabled ->
        # 404, the route "doesn't exist"; never 503, the route "exists but
        # refuses"), just enforced per-request rather than by registration.
        app.include_router(router_els.router, prefix=prefix, **kw)
        app.include_router(ws.router, prefix=prefix, **kw)
        app.include_router(health_router, prefix=prefix, **kw)

    # Canonical /api/v1; /api stays as a deprecated, schema-hidden alias.
    _mount_api("/api/v1")
    _mount_api("/api", include_in_schema=False)

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
    # shipped container shape -- /app/static, docker/Dockerfile)
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
                raise ApiError(404, "not_found", "not found")

            try:
                candidate = (static_dir / full_path).resolve()
                is_real_file = candidate.is_file() and static_root in candidate.parents
            except (ValueError, OSError):
                is_real_file = False

            if is_real_file:
                media_type = _STATIC_MEDIA_TYPES.get(candidate.suffix.lower())
                return FileResponse(candidate, media_type=media_type)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
