"""Tests for optional OIDC authentication (task 4.1): api/router_auth.py's
routes and api/auth_gate.py's middleware, exercised through the REAL app
(the `client`/`app_and_client` fixtures, same convention as
test_api_homebox.py), not authlib or the middleware in isolation.

-- Mode "none" vs mode "oidc" --

The suite is split by the SAME `app_config` indirect-parametrize pattern
test_api_homebox.py's `_CONFIGURED` uses: most tests need `_OIDC_CONFIGURED`
(a real issuer/client id/secret/session secret); a handful deliberately use
the plain, unparametrized `app_config` (auth_mode="none", conftest.py's own
`_DEFAULT_APP_CONFIG_KWARGS`) to pin down that the zero-auth default is
untouched by this task -- not by re-testing the whole existing suite (the
brief is explicit that the EXISTING suite passing is the real proof of
that), just the one new shared surface (`/api/auth/me`) plus one ordinary
route as a canary.

-- Mocking the IdP --

No real IdP -- `idp_mock` (respx, same "patches httpcore, never touches an
explicit ASGITransport" mechanism as test_api_homebox.py's `hb_mock`, see
that file's own fixture note) stands in for one, pre-loaded with a fixed
discovery document + JWKS. `_sign_id_token` mints a REAL RS256-signed
id_token with a generated-once-per-module RSA key (via authlib's own
bundled `joserfc`, not an extra dev dependency) so authlib validates the
signature for real, the same code path a genuine IdP round trip exercises
-- only the network calls (discovery/jwks/token) are faked, never the
cryptography.

-- Why the full round trip needs a real `login` first --

`authorize_access_token` (authlib) rejects a `state`/`nonce` it doesn't
recognize (`MismatchingStateError`) -- both are generated and stashed in
the SESSION by `GET /auth/login` itself, not something a test can fabricate
independently. So every round-trip test calls `/auth/login` first, reads
`state`/`nonce` back out of the 302's `Location` query string (both are
plain query params on the authorize URL, not secret), and feeds `nonce`
into the id_token it then has the mocked token endpoint return -- exactly
mirroring what a real IdP would echo back.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from labelmaker.api import auth_gate
from labelmaker.config import AppConfig
from labelmaker.main import create_app

ISSUER = "https://idp.test"
CLIENT_ID = "client-abc"
CLIENT_SECRET = "client-secret-xyz"
SESSION_SECRET = "unit-test-session-secret-do-not-reuse"

DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
AUTHORIZE_URL = f"{ISSUER}/authorize"
TOKEN_URL = f"{ISSUER}/token"
JWKS_URL = f"{ISSUER}/jwks"

_KID = "test-kid"
_RSA_KEY = RSAKey.generate_key(2048, parameters={"kid": _KID}, private=True)
_JWKS_PUBLIC = KeySet([_RSA_KEY]).as_dict(private=False)

_OIDC_APP_CONFIG_OVERRIDES = {
    "auth_mode": "oidc",
    "oidc_issuer": ISSUER,
    "oidc_client_id": CLIENT_ID,
    "oidc_client_secret": CLIENT_SECRET,
    "session_secret": SESSION_SECRET,
}

_OIDC_CONFIGURED = pytest.mark.parametrize(
    "app_config", [_OIDC_APP_CONFIG_OVERRIDES], indirect=True
)
_OIDC_WITH_ELS = pytest.mark.parametrize(
    "app_config", [{**_OIDC_APP_CONFIG_OVERRIDES, "els_enabled": True}], indirect=True
)


def _discovery_document() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": AUTHORIZE_URL,
        "token_endpoint": TOKEN_URL,
        "jwks_uri": JWKS_URL,
        "userinfo_endpoint": f"{ISSUER}/userinfo",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def _sign_id_token(
    *,
    nonce: str,
    sub: str = "user-1",
    name: str | None = "Test User",
    email: str | None = "test@example.com",
    exp_delta: int = 300,
) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": sub,
        "iat": now,
        "exp": now + exp_delta,
        "nonce": nonce,
    }
    if name is not None:
        claims["name"] = name
    if email is not None:
        claims["email"] = email
    return jwt.encode({"alg": "RS256", "kid": _KID}, claims, _RSA_KEY)


@pytest.fixture
def idp_mock():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=_discovery_document()))
        mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_JWKS_PUBLIC))
        yield mock


def _mock_token_response(idp_mock, id_token: str) -> None:
    idp_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at-1",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": id_token,
            },
        )
    )


async def _complete_login(
    client: httpx.AsyncClient,
    idp_mock,
    next_path: str | None = None,
    expect_location: str = "/",
    **id_token_kwargs,
) -> None:
    """login -> callback, using the real state/nonce `/auth/login` hands
    back on its own 302 (see module docstring's "-- Why the full round trip
    needs a real login first --")."""
    login_params = {"next": next_path} if next_path is not None else None
    login_resp = await client.get("/api/auth/login", params=login_params)
    assert login_resp.status_code == 302
    params = httpx.URL(login_resp.headers["location"]).params

    _mock_token_response(idp_mock, _sign_id_token(nonce=params["nonce"], **id_token_kwargs))

    callback_resp = await client.get(
        "/api/auth/callback", params={"code": "auth-code-1", "state": params["state"]}
    )
    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"] == expect_location


# -- mode "none": the zero-auth default is untouched -----------------------


async def test_me_mode_none_shape_and_existing_routes_still_open(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"auth_mode": "none", "authenticated": True, "user": None}

    # The real proof this task didn't touch the default path: an ordinary
    # route still answers normally with no session cookie involved at all.
    tapes_resp = await client.get("/api/tapes")
    assert tapes_resp.status_code == 200


async def test_login_callback_logout_404_in_none_mode(client):
    """login/callback/logout only make sense with a real IdP configured --
    404 (the route doesn't exist), never a 500 from a missing
    app.state.oauth."""
    assert (await client.get("/api/auth/login")).status_code == 404
    assert (await client.get("/api/auth/callback")).status_code == 404
    assert (await client.post("/api/auth/logout")).status_code == 404


# -- fast-fail config validation --------------------------------------------


def _oidc_config(tmp_path, **overrides) -> AppConfig:
    """AppConfig with EVERY env-read field explicit (the conftest
    hermeticity rule -- a dev shell exporting OIDC_ISSUER must not leak in
    here), oidc mode, missing-by-default credentials."""
    kwargs = {
        "printer_init_strategy": "classic",
        "printer_bit_order": "msb_first",
        "printer_flip_pins": False,
        "homebox_url": None,
        "homebox_api_key": None,
        "els_enabled": False,
        "els_tape_mm": 24.0,
        "auth_mode": "oidc",
        "oidc_issuer": None,
        "oidc_client_id": None,
        "oidc_client_secret": None,
        "oidc_scopes": "openid profile email",
        "session_secret": None,
        **overrides,
    }
    return AppConfig(printer_mode="mock", data_dir=tmp_path / "data", **kwargs)


def test_create_app_fails_fast_when_oidc_config_incomplete(tmp_path):
    with pytest.raises(ValueError) as exc_info:
        create_app(_oidc_config(tmp_path))
    message = str(exc_info.value)
    for missing_name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "SESSION_SECRET"):
        assert missing_name in message


@pytest.mark.parametrize(
    "missing_field, env_name",
    [
        ("oidc_issuer", "OIDC_ISSUER"),
        ("oidc_client_id", "OIDC_CLIENT_ID"),
        ("oidc_client_secret", "OIDC_CLIENT_SECRET"),
        ("session_secret", "SESSION_SECRET"),
    ],
)
def test_fails_fast_names_each_individually_missing_field(tmp_path, missing_field, env_name):
    """Review gap: all-four-missing never proves the per-field list is
    right. One at a time, each absence must be named."""
    complete = {
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": CLIENT_SECRET,
        "session_secret": SESSION_SECRET,
    }
    complete[missing_field] = None
    with pytest.raises(ValueError, match=env_name):
        create_app(_oidc_config(tmp_path, **complete))


def test_fails_fast_when_scopes_lack_openid(tmp_path):
    """Without "openid" authlib silently skips ALL id_token verification
    (review) -- must be a startup error, not a mystery sign-in loop."""
    with pytest.raises(ValueError, match="openid"):
        create_app(
            _oidc_config(
                tmp_path,
                oidc_issuer=ISSUER,
                oidc_client_id=CLIENT_ID,
                oidc_client_secret=CLIENT_SECRET,
                session_secret=SESSION_SECRET,
                oidc_scopes="profile email",
            )
        )


def test_short_session_secret_is_rejected_at_config_time(tmp_path):
    """A guessable SESSION_SECRET is a full auth bypass (the cookie HMAC is
    the gate) -- the Field(min_length=32) bound must hold."""
    with pytest.raises(Exception, match="session_secret"):
        _oidc_config(tmp_path, session_secret="changeme")


@_OIDC_CONFIGURED
async def test_docs_and_openapi_are_withheld_in_oidc_mode(client):
    """The auth gate only covers /api/* -- FastAPI's own /docs and
    /openapi.json must not hand an anonymous caller the API surface
    (review). With docs_url=None these paths fall through to the SPA
    catch-all (a 200 serving index.html is fine) -- the assertion is that
    no schema/console CONTENT leaks, not any particular status code."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = await client.get(path)
        # Without a built frontend/dist (CI) there is no SPA catch-all, so
        # the path 404s with FastAPI's generic JSON {"detail": "Not Found"};
        # with one it is index.html. Either is fine -- only a 200 JSON body
        # (the schema itself) would be a leak.
        assert not (
            resp.status_code == 200 and "application/json" in resp.headers.get("content-type", "")
        ), path
        assert "swagger" not in resp.text.lower(), path
        assert '"openapi"' not in resp.text, path


# -- gating -----------------------------------------------------------------


@_OIDC_CONFIGURED
async def test_unauthenticated_api_route_returns_401_json(client):
    resp = await client.get("/api/tapes")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "authentication required"}


@_OIDC_WITH_ELS
async def test_health_and_els_stay_open_when_oidc_unauthenticated(app_and_client):
    """The two loudly-documented exemptions (api/auth_gate.py): health
    checks and HomeBox's own ELS caller, which sends no credentials of any
    kind by design (see router_els.py)."""
    _, client = app_and_client

    health_resp = await client.get("/api/health")
    assert health_resp.status_code == 200

    els_resp = await client.get(
        "/api/els/label",
        params={"TitleText": "Garage", "URL": "https://homebox.example.com/location/1"},
    )
    assert els_resp.status_code == 200
    assert els_resp.headers["content-type"] == "image/png"


@_OIDC_CONFIGURED
async def test_me_unauthenticated_in_oidc_mode(client):
    """/auth/me itself is exempt from the gate (must always answer, so a
    signed-out browser can ask "am I signed in?" at all)."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"auth_mode": "oidc", "authenticated": False, "user": None}


# -- login -------------------------------------------------------------------


@_OIDC_CONFIGURED
async def test_login_redirects_to_authorize_url_with_state_and_nonce(app_and_client, idp_mock):
    _, client = app_and_client
    resp = await client.get("/api/auth/login")
    assert resp.status_code == 302

    location = httpx.URL(resp.headers["location"])
    assert str(location).startswith(AUTHORIZE_URL)
    assert location.params["client_id"] == CLIENT_ID
    assert location.params["response_type"] == "code"
    assert location.params["redirect_uri"] == "http://test/api/auth/callback"
    assert location.params["state"]
    assert location.params["nonce"]


@_OIDC_CONFIGURED
async def test_callback_rejects_mismatched_state(client, idp_mock):
    """A `state` this app never issued (or already consumed) -- authlib's
    own MismatchingStateError, mapped to this route's 401."""
    resp = await client.get("/api/auth/callback", params={"code": "x", "state": "not-a-real-state"})
    assert resp.status_code == 401


# -- full round trip ---------------------------------------------------------


@_OIDC_CONFIGURED
async def test_full_callback_round_trip_sets_session_and_me_flips_authenticated(
    app_and_client, idp_mock
):
    _, client = app_and_client
    await _complete_login(client, idp_mock)

    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["auth_mode"] == "oidc"
    assert body["authenticated"] is True
    assert body["user"]["sub"] == "user-1"
    assert body["user"]["name"] == "Test User"
    assert body["user"]["email"] == "test@example.com"
    assert isinstance(body["user"]["exp"], int)

    # The session cookie now lets a previously-401'd route through.
    tapes_resp = await client.get("/api/tapes")
    assert tapes_resp.status_code == 200


@pytest.mark.parametrize(
    ("next_value", "expected"),
    [
        ("/capture", "/capture"),
        ("/capture?x=1", "/capture?x=1"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
        ("https://evil.example/", "/"),
        ("javascript:alert(1)", "/"),
        ("capture", "/"),
        ("/a b", "/"),
        ("", "/"),
    ],
)
@_OIDC_CONFIGURED
async def test_login_next_is_honoured_only_for_safe_relative_paths(
    app_and_client, idp_mock, next_value, expected
):
    _, client = app_and_client
    await _complete_login(client, idp_mock, next_path=next_value, expect_location=expected)


@_OIDC_CONFIGURED
async def test_logout_clears_session_and_me_flips_back(app_and_client, idp_mock):
    _, client = app_and_client
    await _complete_login(client, idp_mock)
    assert (await client.get("/api/auth/me")).json()["authenticated"] is True

    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 204
    assert logout_resp.content == b""

    me_resp = await client.get("/api/auth/me")
    assert me_resp.json() == {"auth_mode": "oidc", "authenticated": False, "user": None}

    tapes_resp = await client.get("/api/tapes")
    assert tapes_resp.status_code == 401


@_OIDC_CONFIGURED
async def test_session_expires_after_session_max_age_passes(app_and_client, idp_mock, monkeypatch):
    """The session deadline stored at callback time is THIS APP'S OWN
    `session_max_age_s` (default 8h) -- deliberately NOT the id_token's
    `exp`, which IdPs cap at minutes and would force re-login mid-print
    (review). auth_gate re-checks the stored deadline on every request;
    once it passes, re-authentication is forced."""
    _, client = app_and_client
    await _complete_login(client, idp_mock, exp_delta=60)
    assert (await client.get("/api/auth/me")).json()["authenticated"] is True

    # Advance past the 8h session deadline (an hour past the id_token's own
    # 60s exp must NOT be enough -- that's the review fix under test).
    # `auth_gate.time` is the SAME module object as the stdlib `time`
    # module (a single import-cache entry, not a copy) -- patching its
    # `.time` attribute mutates `time.time` globally, so the replacement
    # must close over the ORIGINAL function rather than call `time.time()`
    # itself (which would now recurse into the very lambda replacing it).
    real_time = time.time
    monkeypatch.setattr(auth_gate.time, "time", lambda: real_time() + 3600)
    assert (await client.get("/api/auth/me")).json()["authenticated"] is True

    monkeypatch.setattr(auth_gate.time, "time", lambda: real_time() + 8 * 3600 + 60)

    me_resp = await client.get("/api/auth/me")
    assert me_resp.json() == {"auth_mode": "oidc", "authenticated": False, "user": None}

    tapes_resp = await client.get("/api/tapes")
    assert tapes_resp.status_code == 401


# -- websocket gating --------------------------------------------------------


@_OIDC_CONFIGURED
def test_ws_rejects_unauthenticated_then_accepts_after_login(app_config):
    """Uses starlette.testclient.TestClient, same as test_api_ws.py (httpx
    has no WebSocket support) -- built manually here (not the
    `app_and_client`/`client` fixtures, which are ASGITransport-only) so the
    SAME cookie jar carries the session from login/callback into the
    websocket handshake."""
    app = create_app(app_config)

    with respx.mock(assert_all_called=False) as idp:
        idp.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=_discovery_document()))
        idp.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_JWKS_PUBLIC))

        with TestClient(app, follow_redirects=False) as test_client:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_client.websocket_connect("/api/ws"):
                    pass
            assert exc_info.value.code == 4401

            login_resp = test_client.get("/api/auth/login")
            params = httpx.URL(login_resp.headers["location"]).params
            idp.post(TOKEN_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "at-1",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "id_token": _sign_id_token(nonce=params["nonce"]),
                    },
                )
            )
            callback_resp = test_client.get(
                "/api/auth/callback", params={"code": "auth-code-1", "state": params["state"]}
            )
            assert callback_resp.status_code == 302

            # Accepted this time -- no exception means the gate let the
            # (now-authenticated) handshake through to ws.py's own accept().
            with test_client.websocket_connect("/api/ws"):
                pass
