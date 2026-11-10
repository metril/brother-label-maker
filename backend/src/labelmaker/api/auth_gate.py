"""ASGI middleware enforcing the optional OIDC session gate (task 4.1).

Only ever instantiated when `AppConfig.auth_mode == "oidc"` -- main.py adds
this middleware (and `starlette.middleware.sessions.SessionMiddleware`,
which it depends on) ONLY in that mode, so the default `auth_mode == "none"`
zero-auth path never even imports/constructs this class, let alone runs it.

-- Middleware ordering (why this matters) --

main.py registers middleware in the order AuthGateMiddleware, then
SessionMiddleware, then CORSMiddleware -- deliberately, and in that exact
order. Starlette's `add_middleware` is LIFO (the LAST-added middleware ends
up OUTERMOST, i.e. runs FIRST on every request -- see
`Starlette.build_middleware_stack`), so that registration order produces
this actual request flow:

    CORS -> Session -> AuthGate -> (routing) -> the endpoint

Two consequences that would break if this order were "simplified":

  1. CORS outermost means a 401 this middleware manufactures still gets
     `Access-Control-Allow-*` headers attached on the way back out --
     without that, a cross-origin dev frontend (a Vite dev server on a
     different port, say) couldn't even READ the 401 body; the browser
     would report an opaque network/CORS error instead.
  2. Session runs BEFORE this middleware, so `scope["session"]` (a plain
     dict Starlette's own SessionMiddleware decodes from the signed cookie)
     is already populated -- for BOTH "http" and "websocket" ASGI scope
     types, since SessionMiddleware treats them identically (see its own
     `scope["type"] not in ("http", "websocket")` early-out) -- by the time
     this middleware reads it. Reversing the two would mean reading a
     session that was never decoded.

-- What's exempt (never gated, regardless of session state) --

  - Anything outside `/api/*` -- the SPA's static files and the
    index.html catch-all (main.py's own `spa_fallback`) must stay
    reachable by a signed-out browser, or it could never load enough JS to
    show its own sign-in button in the first place.
  - `/api/health` -- container/load-balancer liveness probes carry no
    session cookie at all.
  - `/api/auth/*` -- the login/callback/logout/me routes THEMSELVES
    (api/router_auth.py). Gating these would make it impossible to ever
    sign in, and `/auth/me` is deliberately the frontend's one
    always-reachable probe in both auth modes.
  - `/api/els/*` -- loudly flagged since it's easy to "fix" this into a
    401 loop by mistake: HomeBox's External Label Service caller
    (backend/pkgs/labelmaker/labelmaker.go's `fetchLabelFromURL`) sends NO
    credentials of any kind, by design, and is not part of this app's own
    browser-facing session at all -- it already has its own independent
    opt-in gate (`AppConfig.els_enabled`, see router_els.py). Requiring an
    OIDC session on top of that would just break every HomeBox "print
    label" button in an oidc-mode deployment for no security benefit
    (HomeBox has no way to present a browser session cookie).

API keys (task: `Authorization: Bearer lm_...`, see api/api_keys.py) are an
alternative to the session cookie, and a single-use `?ticket=` (POST
/ws-ticket) authenticates the websocket. `read`-scoped keys get 403 on any
non-GET/HEAD/OPTIONS request. Handlers see `scope["auth_kind"] == "api_key"`.

Every other `/api/*` route requires a valid session or API key: a request without one
gets a 401 JSON body (never a redirect -- this is an API surface the SPA's
own `fetch()` calls consume, and a redirect there is invisible to
application code, see frontend/src/api/client.ts's `request()`). A
websocket connection without one is refused at the raw ASGI level
(`websocket.close`, code 4401, sent WITHOUT first accepting the
connection -- the same pattern Starlette's own
`starlette.middleware.authentication.AuthenticationMiddleware` uses for
exactly this case) before `api/ws.py`'s handler ever runs `.accept()`, so
an unauthenticated client is never registered with the EventBus at all.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

from labelmaker.api import api_keys

_EXEMPT_EXACT = {"/api/health"}
_EXEMPT_PREFIXES = ("/api/auth/", "/api/els/")
# FastAPI's interactive docs and schema: gated in oidc mode like the API itself.
_DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _envelope_body(code: str, message: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": message, "details": None}}).encode()


_UNAUTHENTICATED_BODY = _envelope_body("auth_required", "authentication required")
_READ_ONLY_BODY = _envelope_body("forbidden", "this API key is read-only")


def _bearer_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and token.strip().startswith(api_keys.KEY_PREFIX):
                return token.strip()
            return None
    return None


async def _send_json(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _normalize(path: str) -> str:
    """Map `/api/v1/...` onto `/api/...` so the exempt list applies
    identically under both the canonical and the legacy prefix."""
    if path == "/api/v1" or path.startswith("/api/v1/"):
        return "/api" + path[len("/api/v1") :]
    return path


def requires_auth(path: str) -> bool:
    """True for every `/api/*` path except the exemptions documented in this
    module's own docstring; always False for anything outside `/api/*`."""
    if path in _DOC_PATHS:
        return True
    path = _normalize(path)
    if not path.startswith("/api/"):
        return False
    if path in _EXEMPT_EXACT or path.startswith(_EXEMPT_PREFIXES):
        return False
    return True


def get_session_user(session: dict[str, Any] | None) -> dict[str, Any] | None:
    """The session's stored `user` dict (api/router_auth.py's callback is
    the only writer: `{sub, name, email, exp}`) IFF it's still valid -- None
    otherwise, whether because there's no user in the session at all (never
    signed in, or already signed out) or because it has expired.

    `exp` here is the id_token's OWN expiry (stored verbatim at callback
    time), re-checked on every single call rather than trusted once: the
    signed session cookie's own `max_age` (SessionMiddleware, main.py) is
    deliberately long-lived, so without this check a session would keep
    reading as "authenticated" long after the IdP's own token said it
    shouldn't -- this is what actually forces re-authentication once it
    passes. Both api/router_auth.py's `/auth/me` and this middleware call
    this SAME function so the two can never disagree about what "signed
    in" means.
    """
    if not isinstance(session, dict):
        return None
    user = session.get("user")
    if not isinstance(user, dict) or not user.get("sub"):
        return None
    exp = user.get("exp")
    if exp is not None and time.time() >= exp:
        return None
    return user


class AuthGateMiddleware:
    """Raw ASGI middleware (not `BaseHTTPMiddleware`, which never sees
    websocket scopes at all -- see Starlette's own source) so ONE class
    gates both the HTTP `/api/*` surface and the `/api/ws` websocket.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not requires_auth(scope["path"]):
            await self.app(scope, receive, send)
            return

        if get_session_user(scope.get("session")) is not None:
            await self.app(scope, receive, send)
            return

        app_state = scope["app"].state
        is_ws = scope["type"] == "websocket"

        # Machine clients: `Authorization: Bearer lm_...` (never a query param).
        token = _bearer_token(scope)
        if token is not None:
            row = await api_keys.verify_key(app_state.db, token)
            if row is None:
                # Never log the key itself; the prefix is the lookup handle only.
                logger.info("rejected API key: prefix=%s", api_keys.lookup_prefix(token))
            elif (
                not is_ws
                and row["scope"] == "read"
                and scope["method"] not in _SAFE_METHODS
                and _normalize(scope["path"]) != "/api/ws-ticket"  # read keys may watch events
            ):
                await _send_json(send, 403, _READ_ONLY_BODY)
                return
            else:
                await api_keys.touch(app_state.db, row["id"])
                scope["auth_kind"] = "api_key"
                await self.app(scope, receive, send)
                return

        # WebSocket ticket from POST /ws-ticket: single use, 60 s.
        if is_ws and _normalize(scope["path"]) == "/api/ws":
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            ticket = (query.get("ticket") or [""])[0]
            if ticket and app_state.ws_tickets.consume(ticket):
                scope["auth_kind"] = "api_key"
                await self.app(scope, receive, send)
                return

        if is_ws:
            # Sent WITHOUT ever calling `receive()`/accepting first -- the
            # same "reject before accept" pattern Starlette's own
            # AuthenticationMiddleware uses. 4401 is a private-use close code
            # (4000-4999 is reserved for applications) reading as "401 for ws".
            await send({"type": "websocket.close", "code": 4401})
            return

        await _send_json(send, 401, _UNAUTHENTICATED_BODY)
