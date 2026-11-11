"""Runtime-swappable auth/session/CORS state.

Auth mode, OIDC client, session settings and CORS origins are edited on the
Settings page, so the middleware stack cannot be decided once at startup.
Session, auth gate and CORS are always installed as thin wrappers that read
`app.state.auth_rt` (an immutable snapshot) on every request;
`rebuild_runtime` replaces the snapshot after any settings change.

Assumes a single server worker (the supported deployment): a second worker
would keep serving its own stale snapshot until restarted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from labelmaker.api.router_auth import build_oauth_client

SESSION_COOKIE_NAME = "lm_session"


@dataclass(frozen=True)
class AuthRuntime:
    auth_mode: str
    session_secret: str
    max_age_s: int
    https_only: bool
    cors_origins: tuple[str, ...]
    oauth: Any = None


def rebuild_runtime(app: FastAPI) -> None:
    settings = app.state.settings
    e = settings.effective()
    oauth = None
    if e.auth_mode == "oidc":
        oauth = build_oauth_client(
            e.oidc_issuer, e.oidc_client_id, e.oidc_client_secret, e.oidc_scopes
        )
    app.state.auth_rt = AuthRuntime(
        auth_mode=e.auth_mode,
        session_secret=settings.session_secret,
        max_age_s=e.session_max_age_s,
        https_only=e.session_cookie_secure,
        cors_origins=tuple(e.cors_origins),
        oauth=oauth,
    )
    app.state.oauth = oauth


class _Cached:
    """Builds the wrapped Starlette middleware once per distinct parameter tuple."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._key: tuple | None = None
        self._inner: ASGIApp | None = None

    def _get(self, key: tuple, factory: Any) -> ASGIApp:
        if key != self._key or self._inner is None:
            self._inner = factory()
            self._key = key
        return self._inner


class DynamicSessionMiddleware(_Cached):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rt: AuthRuntime | None = getattr(scope["app"].state, "auth_rt", None) if scope[
            "type"
        ] in ("http", "websocket") else None
        if rt is None:
            await self.app(scope, receive, send)
            return
        inner = self._get(
            (rt.session_secret, rt.max_age_s, rt.https_only),
            lambda: SessionMiddleware(
                self.app,
                secret_key=rt.session_secret,
                session_cookie=SESSION_COOKIE_NAME,
                max_age=rt.max_age_s,
                https_only=rt.https_only,
                same_site="lax",
            ),
        )
        await inner(scope, receive, send)


class DynamicCORSMiddleware(_Cached):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rt: AuthRuntime | None = getattr(scope["app"].state, "auth_rt", None) if scope[
            "type"
        ] in ("http", "websocket") else None
        if rt is None:
            await self.app(scope, receive, send)
            return
        inner = self._get(
            rt.cors_origins,
            lambda: CORSMiddleware(
                self.app,
                allow_origins=list(rt.cors_origins),
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        )
        await inner(scope, receive, send)
