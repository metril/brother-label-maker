"""App configuration: a plain pydantic model of hardcoded defaults. The app
reads NO environment variables; every operator-facing setting is edited on the
Settings page and stored in the DB overlay (settings_overlay.py). Tests pass
constructor kwargs to override defaults.

`get_config()` is a process-wide cached accessor for the real server entry
point (`main.app = create_app()`); tests never use it -- they build their own
`AppConfig(...)` with a tmp `data_dir` and pass it straight to `create_app()`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from labelmaker.paths import default_data_dir


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # printer_* , homebox_* and els_* below are Settings-page fields: plain
    # defaults here (not read from the environment), overridden by the DB overlay.
    printer_mode: Literal["mock", "usb", "remote"] = "mock"
    # printer_mode=remote: a Pi running driver/bridge.py owns the USB printer.
    # Address is host[:port] (default 9177); the cert is the bridge's PUBLIC
    # certificate (PEM, from `bridge show-cert`). This app's own key lives
    # only under <data_dir>/bridge/, never in the DB.
    printer_bridge_address: str | None = None
    printer_bridge_cert: str | None = None
    data_dir: Path = Field(default_factory=default_data_dir)
    # Verified 2026-07-28 (first physical print, browser path, 24mm TZe):
    # classic printed successfully; e310bt remains untested.
    printer_init_strategy: Literal["classic", "e310bt"] = "classic"
    # Verified 2026-07-28: msb_first printed clean glyphs (a wrong bit order
    # scrambles within each 8-pin byte -- see the protocol notes RESULTS).
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
    # Opt-in: lets this app create items and upload photos in HomeBox
    # (router_homebox.py's write routes answer 403 while this is False).
    # The API key must ALSO have write access on HomeBox's side.
    homebox_writes_enabled: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    # HomeBox External Label Service (ELS, task 3.5) -- HomeBox's
    # HBOX_LABEL_MAKER_LABEL_SERVICE_URL delegates its own label PNG
    # rendering to a GET endpoint this app exposes. That endpoint is
    # unauthenticated by design (HomeBox sends no credentials -- see
    # backend/pkgs/labelmaker/labelmaker.go's fetchLabelFromURL, verified
    # 2026-07-28), so it must be OFF unless an operator opts in explicitly.
    # L10 (2026-08 review): this field is now DB-editable from the Settings
    # page (see settings_overlay.py's OVERRIDABLE_FIELDS) rather than a
    # startup-only env knob, so main.create_app registers router_els's
    # routes UNCONDITIONALLY -- the gate is a router-level dependency
    # (router_els._require_els_enabled) that reads the settings overlay's
    # EFFECTIVE els_enabled on every request instead, ahead of even this
    # route's own param binding (see that function's own docstring), and
    # 404s when it's off (disabled -> a plain 404, not a 503, same "the
    # route doesn't exist" contract as before -- just enforced per-request
    # rather than by conditional registration).
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
    # (api/router_auth.py). the settings overlay refuses to switch
    # to "oidc" until the fields below have passed a test login.
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
    # (The session-signing secret is auto-generated and kept in the DB.)
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
