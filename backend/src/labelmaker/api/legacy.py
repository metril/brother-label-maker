"""Deprecation signalling for the legacy unversioned `/api/*` alias."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# HomeBox's ELS caller is configured with the unversioned URL and cannot be
# told to migrate, so it is not flagged.
_NOT_FLAGGED = ("/api/els/",)


def is_legacy_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    if path == "/api/v1" or path.startswith("/api/v1/"):
        return False
    return not path.startswith(_NOT_FLAGGED)


class LegacyDeprecationMiddleware:
    """Adds `Deprecation: true` to HTTP responses on legacy `/api/*` paths."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_legacy_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Deprecation"] = "true"
            await send(message)

        await self.app(scope, receive, send_wrapper)
