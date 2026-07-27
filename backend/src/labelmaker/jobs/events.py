"""In-process pub/sub for print-job lifecycle events: every connected
`/api/ws` WebSocket gets every broadcast event as JSON, in real time.

Deliberately duck-typed rather than importing `fastapi.WebSocket` for the
registered-client type: `broadcast()` only ever calls `await client.send_json`
on what's registered, so anything satisfying that (a real WebSocket, or a
test double) works -- see test_api_print.py's `_RecordingSocket`.
"""

from __future__ import annotations

from typing import Any, Protocol


class _JsonSendable(Protocol):
    async def send_json(self, data: Any) -> None: ...


class EventBus:
    def __init__(self) -> None:
        self._clients: set[_JsonSendable] = set()

    def register(self, client: _JsonSendable) -> None:
        self._clients.add(client)

    def unregister(self, client: _JsonSendable) -> None:
        self._clients.discard(client)

    async def broadcast(self, event: dict) -> None:
        """Send `event` to every registered client, dropping (unregistering)
        any that error out (e.g. an already-closed WebSocket) instead of
        letting one dead connection break the broadcast for everyone else."""
        dead: list[_JsonSendable] = []
        for client in list(self._clients):
            try:
                await client.send_json(event)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)
