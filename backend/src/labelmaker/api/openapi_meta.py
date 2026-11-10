"""OpenAPI metadata: tag descriptions, security schemes and per-route auth.

Applied once by `install(app)` after the error-envelope wrapper. Every
operation gets an explicit `security` list: `[]` for the routes the auth gate
exempts (health, auth/*, els/*), bearer-or-cookie for the rest. Each
operation also carries `x-required-scope` (`none`, `read`, `write` or
`session`) which the generated API.md reads.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from labelmaker.api.auth_gate import requires_auth

DESCRIPTION = (
    "HTTP API of the Brother P-touch Cube label maker: render and print labels, "
    "manage presets, history, images and HomeBox integration. Canonical prefix "
    "`/api/v1`; the unversioned `/api` alias is deprecated. Errors use a uniform "
    "`{error: {code, message, details}}` envelope. See API.md for guides."
)

TAGS: list[dict[str, str]] = [
    {"name": "health", "description": "Liveness probe; no authentication."},
    {"name": "auth", "description": "OIDC login flow and current-session probe."},
    {"name": "api-keys", "description": "Create, list and revoke API keys (browser session only)."},
    {"name": "settings", "description": "Runtime settings stored in the database overlay."},
    {
        "name": "labels",
        "description": "Label types, fonts, tapes, symbols, rendering and CSV expansion.",
    },
    {"name": "images", "description": "Uploaded images usable as label icons."},
    {"name": "gallery", "description": "Gallery of saved label artwork."},
    {
        "name": "print",
        "description": "Queue print jobs, estimate tape use, preview chains, stream raster.",
    },
    {"name": "printer", "description": "Printer status, bridge identity and cutter control."},
    {
        "name": "presets",
        "description": "Saved label presets; list supports X-Total-Count pagination.",
    },
    {"name": "history", "description": "Print history, thumbnails and reprint."},
    {
        "name": "homebox",
        "description": "Proxy to a configured HomeBox server (entities, tags, bulk create).",
    },
    {
        "name": "els",
        "description": "HomeBox External Label Service endpoint; unauthenticated by design.",
    },
    {"name": "ws", "description": "WebSocket event stream and single-use ticket issuing."},
]

SECURITY_SCHEMES: dict[str, dict[str, Any]] = {
    "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "lm_ API key",
        "description": "API key created on the Settings page: `Authorization: Bearer lm_...`.",
    },
    "cookieAuth": {
        "type": "apiKey",
        "in": "cookie",
        "name": "lm_session",
        "description": "Browser session cookie set by the OIDC login flow.",
    },
}

_SAFE = {"get", "head", "options"}
_METHODS = ("get", "put", "post", "delete", "options", "head", "patch")


def _scope_for(path: str, method: str) -> str:
    if not requires_auth(path):
        return "none"
    if path.startswith("/api/v1/api-keys"):
        return "session"
    if path == "/api/v1/ws-ticket":
        return "read"
    return "read" if method in _SAFE else "write"


def install(app: FastAPI) -> None:
    original = app.openapi
    done = False

    def openapi() -> dict[str, Any]:
        nonlocal done
        schema = original()
        if not done:
            schema["info"]["description"] = DESCRIPTION
            schema["tags"] = TAGS
            schema.setdefault("components", {})["securitySchemes"] = SECURITY_SCHEMES
            for path, item in schema["paths"].items():
                for method in _METHODS:
                    op = item.get(method)
                    if op is None:
                        continue
                    scope = _scope_for(path, method)
                    op["security"] = (
                        []
                        if scope == "none"
                        else [{"bearerAuth": []}, {"cookieAuth": []}]
                        if scope != "session"
                        else [{"cookieAuth": []}]
                    )
                    op["x-required-scope"] = scope
            done = True
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
