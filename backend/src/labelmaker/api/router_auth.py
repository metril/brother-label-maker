"""Optional OIDC authentication (task 4.1): standard authorization-code flow
via authlib, gating this otherwise zero-auth, LAN-first app's `/api/*`
surface behind a session cookie when an operator opts into
`AUTH_MODE=oidc` (see config.py's `AppConfig.auth_mode`).

-- Why opt-in, and what "none" mode looks like here --

This app's whole design point is a LAN-only appliance sitting next to a
physical label printer. `AUTH_MODE=none` (the default) preserves that
exactly -- `GET /auth/me` below still exists and still answers 200, but as
a CONSTANT `{"auth_mode": "none", "authenticated": True, "user": None}`,
and login/callback/logout all 404 (`_require_oidc_mode`) rather than
attempt anything against an IdP that was never configured. This is
deliberate: the frontend's `useAuth` hook (frontend/src/hooks/useAuth.ts)
always calls this SAME endpoint regardless of mode, so it never has to
know which mode it's running in ahead of time -- only branch on the shape
of what comes back.

-- The flow (oidc mode) --

  1. `GET /auth/login`: builds the IdP's authorize URL (state + a nonce,
     both authlib-managed -- `client_kwargs={"scope": ...}` including
     "openid" is what makes authlib generate+persist the nonce at all, see
     `authlib.integrations.base_client.sync_app.
     _create_oauth2_authorization_url`) and 302s the browser there. The
     redirect_uri is THIS app's own `/api/auth/callback`, computed via
     `request.url_for` rather than hand-built, so it's always correct
     relative to however this app is actually being reached.
  2. The IdP authenticates the user and redirects back to
     `GET /auth/callback?code=...&state=...`.
  3. This app exchanges `code` for a token at the IdP's token endpoint and
     validates the returned `id_token`'s signature against the IdP's own
     JWKS (fetched from the discovery document's `jwks_uri`, cached by
     authlib after the first fetch) -- authlib's `parse_id_token` does the
     actual RS256 verification plus the `iss`/`aud`/`exp`/`nonce` claim
     checks (`authlib.integrations.base_client.async_openid.
     AsyncOpenIDMixin.parse_id_token`). ANY failure there (bad signature,
     replayed/mismatched state or nonce, expired token, wrong issuer, the
     IdP itself erroring or unreachable) surfaces as this route's own 401,
     not a 500 -- a failed sign-in attempt is not this app's bug.
  4. On success, only `{sub, name, email, exp}` -- never the raw
     access/id token -- is written into the session (Starlette's
     `SessionMiddleware`, itsdangerous-signed, added by main.py only in
     oidc mode; there's no reason this app's own session needs to hold
     either token past this one request), and the browser is redirected
     to "/".
  5. `POST /auth/logout` clears the session; 204 (no body -- the frontend
     just reloads itself after this call, see AppShell's sign-out button).
  6. `GET /auth/me` is the frontend's one probe, exempted from the auth
     gate itself (api/auth_gate.py's exemption list) so a signed-out
     browser can always ask "am I signed in?": `{auth_mode, authenticated,
     user}`.

`get_session_user` (api/auth_gate.py) is the SAME helper both this
module's `/auth/me` and the gate middleware call to decide "signed in" --
including re-checking the stored `exp` on every call, so a session that
has outlived its id_token stops reading as authenticated immediately,
without waiting for the signed cookie's own much-longer `max_age` to
expire. See that module's docstring for the full rationale.
"""

from __future__ import annotations

import time
from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from labelmaker.api.auth_gate import get_session_user
from labelmaker.api.deps import AppConfigDep
from labelmaker.config import AppConfig

router = APIRouter(tags=["auth"])

SESSION_USER_KEY = "user"


def build_oauth_client(config: AppConfig) -> OAuth:
    """Builds the authlib registry for the single "oidc" provider this app
    supports, called once from main.create_app (oidc mode only) and stashed
    on `app.state.oauth`.

    Discovery (`{oidc_issuer}/.well-known/openid-configuration`) is fetched
    LAZILY by authlib itself on first actual use (login/callback), not
    here -- so this is safe to call unconditionally at create_app time
    without making a network call (or being able to fail) during startup.
    A misconfigured/unreachable issuer instead surfaces the first time a
    real browser hits `/auth/login`, as that route's own error.
    """
    issuer = (config.oidc_issuer or "").rstrip("/")
    oauth = OAuth()
    oauth.register(
        name="oidc",
        server_metadata_url=f"{issuer}/.well-known/openid-configuration",
        client_id=config.oidc_client_id,
        client_secret=config.oidc_client_secret,
        client_kwargs={"scope": config.oidc_scopes},
    )
    return oauth


def _require_oidc_mode(config: AppConfig) -> None:
    """login/callback/logout only make sense with a real IdP configured --
    404 (the route doesn't exist), not e.g. a 500 from a missing
    `app.state.oauth`, mirroring router_els.py's own disabled-feature
    convention (a plain 404 beats a 503 when there's nothing to configure
    towards in the first place)."""
    if config.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="not found")


SESSION_NEXT_KEY = "login_next"


def safe_next_path(value: str | None) -> str:
    """Post-login redirect target: ONLY a same-origin relative path -- a
    single leading "/", never "//" (protocol-relative), a backslash (some
    browsers treat "/\\host" as "//host"), a scheme/host, or control
    characters/whitespace -- else "/". Prevents an open redirect via
    `/api/auth/login?next=...`."""
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
    ):
        return "/"
    return value


@router.get("/auth/login")
async def login(
    request: Request, config: AppConfigDep, next: str | None = None
) -> RedirectResponse:
    _require_oidc_mode(config)
    request.session[SESSION_NEXT_KEY] = safe_next_path(next)
    oauth: OAuth = request.app.state.oauth
    redirect_uri = str(request.url_for("auth_callback"))
    try:
        # First hit triggers authlib's lazy discovery fetch -- a typo'd or
        # unreachable OIDC_ISSUER surfaces HERE, as this route's own
        # readable error, not an unhandled 500 (review).
        return await oauth.oidc.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"identity provider unreachable or misconfigured (OIDC_ISSUER): {exc}",
        ) from exc


@router.get("/auth/callback", name="auth_callback")
async def callback(request: Request, config: AppConfigDep) -> RedirectResponse:
    _require_oidc_mode(config)
    oauth: OAuth = request.app.state.oauth
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"sign-in failed: {exc}") from exc

    userinfo: dict[str, Any] = dict(token.get("userinfo") or {})
    if not userinfo.get("sub"):
        # No verified id_token subject means authlib never ran (or never
        # completed) id_token verification -- writing a subject-less session
        # and 302ing would read as success while sign-in is actually broken
        # (review; reachable e.g. via a scope set missing "openid", which
        # main._require_oidc_config now rejects at startup as well).
        raise HTTPException(
            status_code=401,
            detail="sign-in failed: the provider returned no verified id_token subject",
        )
    # Re-validated on the way out too (the session is signed, but a bad
    # value here would be an open redirect, so never trust it blindly).
    next_path = safe_next_path(request.session.pop(SESSION_NEXT_KEY, None))
    request.session[SESSION_USER_KEY] = {
        "sub": userinfo["sub"],
        "name": userinfo.get("name"),
        "email": userinfo.get("email"),
        # THIS APP'S session deadline -- deliberately not the id_token's
        # own `exp`, which is an auth-freshness claim IdPs cap at minutes
        # (review). authlib already validated the token's exp above; the
        # session lives session_max_age_s from now, matching the cookie's
        # max_age (main.py wires both from the same field).
        "exp": int(time.time()) + config.session_max_age_s,
    }
    # Explicit 302 -- `RedirectResponse`'s own default (307) is meant to
    # preserve the ORIGINAL request method/body on redirect, which matters
    # for nothing here (this is a plain browser-navigable GET, same as
    # `authorize_redirect`'s own explicit 302 in the login route above) and
    # would otherwise read as an odd inconsistency between the two.
    return RedirectResponse(url=next_path, status_code=302)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, config: AppConfigDep) -> Response:
    _require_oidc_mode(config)
    request.session.clear()
    return Response(status_code=204)


@router.get("/auth/me")
async def me(request: Request, config: AppConfigDep) -> dict:
    if config.auth_mode == "none":
        return {"auth_mode": "none", "authenticated": True, "user": None}
    user = get_session_user(request.session)
    return {"auth_mode": "oidc", "authenticated": user is not None, "user": user}
