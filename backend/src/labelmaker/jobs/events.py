"""In-process pub/sub for print-job lifecycle events: every connected
`/api/ws` WebSocket gets every broadcast event as JSON, in real time.

Deliberately duck-typed rather than importing `fastapi.WebSocket` for the
registered-client type: `broadcast()` only ever calls `await client.send_json`
on what's registered, so anything satisfying that (a real WebSocket, or a
test double) works -- see test_api_print.py's `_RecordingSocket`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

# Per-client send timeout: one half-open client must not stall every broadcast
# (the progress callback runs from the USB thread, under USB_LOCK).
_SEND_TIMEOUT_S = 1.0


class _JsonSendable(Protocol):
    async def send_json(self, data: Any) -> None: ...


async def _close_quietly(close) -> None:
    try:
        await close()
    except Exception:
        pass


class EventBus:
    def __init__(self) -> None:
        self._clients: set[_JsonSendable] = set()
        self._close_tasks: set[asyncio.Task] = set()  # strong refs until done

    def register(self, client: _JsonSendable) -> None:
        self._clients.add(client)

    def unregister(self, client: _JsonSendable) -> None:
        self._clients.discard(client)

    async def broadcast(self, event: dict) -> None:
        """Send `event` to every registered client, dropping (unregistering)
        any that error out or time out (e.g. an already-closed or half-open WebSocket) instead of
        letting one dead connection break the broadcast for everyone else."""
        dead: list[_JsonSendable] = []
        for client in list(self._clients):
            try:
                await asyncio.wait_for(client.send_json(event), timeout=_SEND_TIMEOUT_S)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)
            # Also close the socket: otherwise it stays open but silently stops
            # receiving (and a cancelled send may have left a partial frame), so
            # the frontend would never notice it needs to reconnect.
            close = getattr(client, "close", None)
            if close is not None:
                task = asyncio.ensure_future(_close_quietly(close))
                self._close_tasks.add(task)
                task.add_done_callback(self._close_tasks.discard)
