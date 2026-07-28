"""App configuration: a pydantic-settings model read from the process
environment, field names matching the planned docker-compose service's env
vars exactly -- no prefix (`PRINTER_MODE`, not e.g. `LABELMAKER_PRINTER_MODE`).

`get_config()` is a process-wide cached accessor for the real server entry
point (`main.app = create_app()`); tests never use it -- they build their own
`AppConfig(...)` with a tmp `data_dir` and pass it straight to `create_app()`,
so cached env-derived state never leaks between tests.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    printer_mode: Literal["mock", "usb"] = "mock"
    data_dir: Path = Path("./data")
    # Verified 2026-07-28 (first physical print, browser path, 24mm TZe):
    # classic printed successfully; e310bt remains untested.
    printer_init_strategy: Literal["classic", "e310bt"] = "classic"
    # Verified 2026-07-28: msb_first printed clean glyphs (a wrong bit order
    # scrambles within each 8-pin byte -- see docs/protocol-notes.md RESULTS).
    printer_bit_order: Literal["msb_first", "lsb_first"] = "msb_first"
    # Verified 2026-07-28: flip_pins=False printed mirrored across the tape
    # width; True is correct for this printer. RasterConfig's dataclass
    # default stays False (library-neutral; driver goldens pin it) -- this
    # AppConfig default is the policy layer every real print goes through.
    printer_flip_pins: bool = True
    # HomeBox integration (Phase 3) -- enabled iff BOTH are set. The URL is
    # the instance root (https://homebox.example.com); the key is an
    # hb_-prefixed static API key (HomeBox v0.26+ user settings). The key
    # stays server-side: the browser only ever talks to this app's
    # /api/homebox/* proxy routes.
    homebox_url: str | None = None
    homebox_api_key: str | None = None
    # M3: pydantic-settings parses list-typed fields as JSON, not a bare
    # comma-separated string -- the env var value must be a JSON array,
    # quoted so the shell/compose file passes the brackets/quotes through
    # literally, e.g.: CORS_ORIGINS='["https://labels.example.com"]'
    # (multiple origins: '["https://a.example.com","https://b.example.com"]').
    cors_origins: list[str] = ["http://localhost:5173"]
    # HomeBox External Label Service (ELS, task 3.5) -- HomeBox's
    # HBOX_LABEL_MAKER_LABEL_SERVICE_URL delegates its own label PNG
    # rendering to a GET endpoint this app exposes. That endpoint is
    # unauthenticated by design (HomeBox sends no credentials -- see
    # backend/pkgs/labelmaker/labelmaker.go's fetchLabelFromURL, verified
    # 2026-07-28), so it must be OFF unless an operator opts in explicitly:
    # main.create_app only registers router_els's routes when this is True
    # (disabled -> a plain 404, not a 503, since the routes don't exist at
    # all rather than existing-but-refusing).
    els_enabled: bool = False
    # The tze tape width (mm) ELS labels render at -- HomeBox's own
    # Width/Height/Dpi query params describe ITS internal generator's
    # canvas at 72dpi and are not enforced on whatever image a configured
    # LabelServiceUrl returns (fetchLabelFromURL copies the response bytes
    # through verbatim, no resize/dimension check), so this is the one
    # knob that actually decides the returned PNG's pixel geometry -- see
    # router_els.py's module docstring for the full contract.
    els_tape_mm: float = 24.0
    # Optional OIDC auth (task 4.1) -- this app is LAN-first and auth is
    # opt-in: "none" (the default) is exactly today's zero-auth behavior,
    # byte-for-byte (main.py adds no session/gate middleware at all in this
    # mode). "oidc" gates every /api/* route (except /api/health,
    # /api/auth/*, and /api/els/* -- see api/auth_gate.py's own docstring
    # for why each is exempt) behind a signed session cookie, populated via
    # a standard authorization-code round trip through the IdP named below
    # (api/router_auth.py). main.create_app fails FAST (raises, at startup,
    # not a 500 on the first login attempt) if auth_mode is "oidc" but any
    # of the four fields below is left unset -- see main.py's
    # `_require_oidc_config`.
    auth_mode: Literal["none", "oidc"] = "none"
    # The IdP's issuer URL, e.g. https://auth.example.com/realms/labelmaker
    # -- authlib discovers the rest (authorize/token/jwks endpoints) from
    # `{oidc_issuer}/.well-known/openid-configuration` lazily, on first use,
    # not at startup (so a briefly-unreachable IdP doesn't block this app's
    # own boot).
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    # Confidential client secret -- stays server-side, exchanged for tokens
    # only in api/router_auth.py's callback handler, never sent to the
    # browser.
    oidc_client_secret: str | None = None
    # Space-separated, passed to the IdP's authorize endpoint verbatim
    # (authlib's own `client_kwargs={"scope": ...}` convention) -- "openid"
    # must stay in this list (it's what makes authlib treat the flow as
    # OIDC at all, e.g. generating+checking the nonce; see
    # authlib.integrations.base_client.sync_app._create_oauth2_authorization_url).
    oidc_scopes: str = "openid profile email"
    # Signs/verifies the session cookie (starlette.middleware.sessions.
    # SessionMiddleware, itsdangerous under the hood) -- a long random
    # string (e.g. `openssl rand -hex 32`), operator-supplied so restarting
    # the container doesn't silently invalidate every signed-in session
    # against a freshly-generated one. min_length is a hard floor (review):
    # a guessable secret lets anyone on the network FORGE the cookie and
    # bypass auth entirely -- the HMAC is the whole gate.
    session_secret: str | None = Field(default=None, min_length=32)
    # THIS APP'S OWN session lifetime, seconds (default 8h). Deliberately
    # NOT the id_token's `exp` claim (review): that is an authentication-
    # freshness claim most IdPs cap at minutes (Keycloak: 5m), and reusing
    # it as the session clock would force a full re-login mid-print job.
    # authlib already validates the id_token's exp once, at callback time.
    session_max_age_s: int = Field(default=8 * 3600, ge=300)
    # Set true when serving over TLS (any real OIDC deployment): stamps
    # `Secure` on the session cookie so it never rides plain http. Default
    # false only because plain-HTTP LAN is this app's documented baseline.
    session_cookie_secure: bool = False


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
