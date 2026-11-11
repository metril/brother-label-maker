"""Optional OIDC authentication (task 4.1): standard authorization-code flow
via authlib, gating this otherwise zero-auth, LAN-first app's `/api/*`
surface behind a session cookie when an operator opts into
`auth_mode=oidc` on the Settings page (see settings_overlay.py).

-- Why opt-in, and what "none" mode looks like here --

This app's whole design point is a LAN-only appliance sitting next to a
physical label printer. `auth_mode=none` (the default) preserves that
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
     `SessionMiddleware`, itsdangerous-signed, installed by
     main.py in every mode; there's no reason this app's own session needs to hold
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

import secrets
import time
from typing import Any
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, ValidationError

from labelmaker.api.auth_gate import get_session_user
from labelmaker.api.deps import SettingsDep
from labelmaker.api.errors import ApiError, err
from labelmaker.api.schemas import AuthMeOut, AuthUserOut, OidcTestOut
from labelmaker.settings_overlay import SettingsOverlay, SettingsOverrides

router = APIRouter(tags=["auth"])

SESSION_USER_KEY = "user"


def build_oauth_client(
    issuer: str | None, client_id: str | None, client_secret: str | None, scopes: str
) -> OAuth:
    """Builds the authlib registry for the single "oidc" provider this app
    supports (rebuilt by auth_runtime.rebuild_runtime on every settings
    change).

    Discovery (`{issuer}/.well-known/openid-configuration`) is fetched
    LAZILY by authlib itself on first actual use (login/callback), so this
    never makes a network call. A misconfigured/unreachable issuer surfaces
    the first time a browser hits `/auth/login`, as that route's own error.
    """
    oauth = OAuth()
    oauth.register(
        name="oidc",
        server_metadata_url=f"{(issuer or '').rstrip('/')}/.well-known/openid-configuration",
        client_id=client_id,
        client_secret=client_secret,
        client_kwargs={"scope": scopes},
    )
    return oauth


def oidc_redirect_uri(request: Request) -> str:
    """This app's callback URL, the one to register with the IdP. Pinned to
    the legacy unversioned path: operators registered `/api/auth/callback`
    with their IdP before /api/v1 existed (both mounts serve it), and
    url_for would otherwise resolve to the v1 one."""
    return str(request.url_for("auth_callback")).replace("/api/v1/auth/", "/api/auth/")


def _require_oidc_mode(settings: SettingsOverlay) -> None:
    """login/logout only make sense with oidc active -- 404 (the route
    doesn't exist) otherwise, mirroring router_els.py's disabled-feature
    convention."""
    if settings.effective().auth_mode != "oidc":
        raise ApiError(404, "not_found", "not found")


def require_admin(request: Request, settings: SettingsOverlay) -> None:
    """Auth-config actions (test login, secret rotation): open in none mode,
    session users only in oidc mode (the auth gate exempts /api/auth/*, so
    this is enforced here)."""
    if settings.effective().auth_mode != "oidc":
        return
    if get_session_user(request.session) is not None:
        return
    if request.headers.get("authorization", "").lower().startswith("bearer lm_"):
        raise ApiError(403, "forbidden", "API keys cannot change authentication settings")
    raise ApiError(401, "auth_required", "authentication required")


# Pending test logins: id -> (expiry, candidate config, temp OAuth). In
# memory only -- the candidate secret never goes into the (client-readable)
# signed session cookie, just this opaque id.
TEST_SESSION_KEY = "oidc_test_id"
_TEST_TTL_S = 600


def _pending(request: Request) -> dict[str, tuple[float, dict[str, str], OAuth]]:
    state = request.app.state
    if not hasattr(state, "oidc_tests"):
        state.oidc_tests = {}
    now = time.monotonic()
    for key in [k for k, v in state.oidc_tests.items() if v[0] < now]:
        del state.oidc_tests[key]
    return state.oidc_tests


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


@router.get(
    "/auth/login",
    status_code=302,
    response_class=RedirectResponse,
    summary="Start OIDC sign-in",
    responses={
        302: {"description": "Redirect to the identity provider"},
        **err(404, 422, 502),
    },
)
async def login(
    request: Request, settings: SettingsDep, next: str | None = None
) -> RedirectResponse:
    """Redirect the browser to the IdP. `next` is a same-origin path to return to."""
    _require_oidc_mode(settings)
    request.session[SESSION_NEXT_KEY] = safe_next_path(next)
    oauth: OAuth = request.app.state.oauth
    redirect_uri = oidc_redirect_uri(request)
    try:
        # First hit triggers authlib's lazy discovery fetch -- a typo'd or
        # unreachable issuer surfaces HERE, as this route's own
        # readable error, not an unhandled 500 (review).
        return await oauth.oidc.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        raise ApiError(
            502,
            "idp_unavailable",
            f"identity provider unreachable or misconfigured (OIDC issuer): {exc}",
        ) from exc


@router.get(
    "/auth/callback",
    name="auth_callback",
    status_code=302,
    response_class=RedirectResponse,
    summary="Complete OIDC sign-in",
    responses={
        302: {"description": "Redirect to the originally requested page"},
        **err(401, 404),
    },
)
async def callback(request: Request, settings: SettingsDep) -> RedirectResponse:
    """IdP redirect target: exchanges the code, stores the session, redirects on.

    Also completes a Settings-page "test login" (a pending test id in the
    session): verifies the id_token against the candidate config, saves it
    with its verified marker, signs the browser in, and redirects to
    `/settings?oidc_test=ok|error[&message=...]`.
    """
    test_id = request.session.pop(TEST_SESSION_KEY, None)
    if test_id is not None:
        return await _finish_test_login(request, settings, test_id)
    _require_oidc_mode(settings)
    oauth: OAuth = request.app.state.oauth
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:
        raise ApiError(401, "auth_required", f"sign-in failed: {exc}") from exc

    userinfo: dict[str, Any] = dict(token.get("userinfo") or {})
    if not userinfo.get("sub"):
        # No verified id_token subject means authlib never ran (or never
        # completed) id_token verification -- writing a subject-less session
        # and 302ing would read as success while sign-in is actually broken
        # (review; reachable e.g. via a scope set missing "openid", which
        # the settings validator rejects that scope set).
        raise ApiError(
            401,
            "auth_required",
            "sign-in failed: the provider returned no verified id_token subject",
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
        # max_age (auth_runtime wires both from the same setting).
        "exp": int(time.time()) + settings.effective().session_max_age_s,
    }
    # Explicit 302 -- `RedirectResponse`'s own default (307) is meant to
    # preserve the ORIGINAL request method/body on redirect, which matters
    # for nothing here (this is a plain browser-navigable GET, same as
    # `authorize_redirect`'s own explicit 302 in the login route above) and
    # would otherwise read as an odd inconsistency between the two.
    return RedirectResponse(url=next_path, status_code=302)


@router.post(
    "/auth/logout",
    status_code=204,
    response_class=Response,
    summary="Sign out",
    responses=err(404),
)
async def logout(request: Request, settings: SettingsDep) -> Response:
    """Clear the session cookie. OIDC mode only."""
    _require_oidc_mode(settings)
    request.session.clear()
    return Response(status_code=204)


@router.get(
    "/auth/me",
    response_model=AuthMeOut,
    summary="Get the current session",
    responses=err(500),
)
async def me(request: Request, settings: SettingsDep) -> AuthMeOut:
    """Auth mode and the signed-in user. Always 200, even when signed out."""
    if settings.effective().auth_mode == "none":
        return AuthMeOut(auth_mode="none", authenticated=True, user=None)
    user = get_session_user(request.session)
    return AuthMeOut(
        auth_mode="oidc",
        authenticated=user is not None,
        user=AuthUserOut.model_validate(user) if user is not None else None,
    )


class OidcTestIn(BaseModel):
    """Candidate OIDC config to verify. A omitted secret/scopes falls back to
    the stored/default value, so re-testing needn't re-enter the secret."""

    model_config = ConfigDict(extra="forbid")

    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str | None = None
    oidc_scopes: str | None = None


@router.post(
    "/auth/oidc-test",
    response_model=OidcTestOut,
    summary="Start an OIDC test login",
    responses=err(401, 403, 422, 502),
)
async def oidc_test(body: OidcTestIn, request: Request, settings: SettingsDep) -> OidcTestOut:
    """Validate a candidate config and return the IdP authorize URL to open.

    The browser then returns to `/api/auth/callback`, which verifies the
    id_token, saves the config as verified, signs this browser in and
    redirects to `/settings?oidc_test=ok` (or `error` with a `message`).
    """
    require_admin(request, settings)
    effective = settings.effective()
    fields = body.model_dump(exclude_none=True)
    try:
        cand = SettingsOverrides.model_validate(fields)
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors()
        )
        raise ApiError(422, "invalid_setting", detail) from exc
    candidate = {
        "oidc_issuer": cand.oidc_issuer or "",
        "oidc_client_id": cand.oidc_client_id or "",
        "oidc_client_secret": cand.oidc_client_secret or effective.oidc_client_secret or "",
        "oidc_scopes": cand.oidc_scopes or effective.oidc_scopes,
    }
    if not candidate["oidc_client_secret"]:
        raise ApiError(422, "invalid_setting", "oidc_client_secret: a client secret is required")
    oauth = build_oauth_client(
        candidate["oidc_issuer"],
        candidate["oidc_client_id"],
        candidate["oidc_client_secret"],
        candidate["oidc_scopes"],
    )
    redirect_uri = oidc_redirect_uri(request)
    try:
        response = await oauth.oidc.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        raise ApiError(
            502, "idp_unavailable", f"identity provider unreachable or misconfigured: {exc}"
        ) from exc
    test_id = secrets.token_urlsafe(16)
    _pending(request)[test_id] = (time.monotonic() + _TEST_TTL_S, candidate, oauth)
    request.session[TEST_SESSION_KEY] = test_id
    return OidcTestOut(authorize_url=response.headers["location"], redirect_uri=redirect_uri)


def _test_result(ok: bool, message: str | None = None) -> RedirectResponse:
    query = {"oidc_test": "ok" if ok else "error"}
    if message:
        query["message"] = message[:200]
    return RedirectResponse(url=f"/settings?{urlencode(query)}", status_code=302)


async def _finish_test_login(
    request: Request, settings: SettingsOverlay, test_id: str
) -> RedirectResponse:
    entry = _pending(request).pop(test_id, None)
    if entry is None:
        return _test_result(False, "test login expired; start it again")
    _, cand, oauth = entry
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:
        return _test_result(False, f"sign-in failed: {exc}")
    userinfo: dict[str, Any] = dict(token.get("userinfo") or {})
    if not userinfo.get("sub"):
        return _test_result(False, "the provider returned no verified id_token subject")
    await settings.save_verified_oidc(
        cand["oidc_issuer"],
        cand["oidc_client_id"],
        cand["oidc_client_secret"],
        cand["oidc_scopes"],
    )
    # Sign this browser in, so switching to oidc mode doesn't lock the
    # operator out of the very page they are using.
    request.session[SESSION_USER_KEY] = {
        "sub": userinfo["sub"],
        "name": userinfo.get("name"),
        "email": userinfo.get("email"),
        "exp": int(time.time()) + settings.effective().session_max_age_s,
    }
    return _test_result(True)


@router.post(
    "/auth/rotate-session-secret",
    status_code=204,
    response_class=Response,
    summary="Rotate the session signing secret",
    responses=err(401, 403),
)
async def rotate_session_secret(request: Request, settings: SettingsDep) -> Response:
    """Invalidate every signed-in session (including the caller's, in oidc mode)."""
    require_admin(request, settings)
    await settings.rotate_session_secret()
    return Response(status_code=204)
