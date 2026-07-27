"""WS /api/ws: register the connection with the app's EventBus for its
lifetime, so it receives every print-job lifecycle broadcast (job.queued/
job.started/job.done/job.failed -- see jobs/worker.py and router_print.py).

The client never needs to send anything; the receive loop below is only how
Starlette/FastAPI's WebSocket API detects a client-initiated close --
broadcasts are pushed independently by EventBus.broadcast() calling
`send_json` on this same connection from elsewhere (the worker task), which
is safe to interleave with an in-flight receive on the same socket.

I6: uses the raw `receive()` (not `receive_text()`) so a stray non-text
(binary) frame from the client doesn't kill the connection. `receive_text()`
would raise on anything that isn't a text message -- an unexpected error
that has nothing to do with a real disconnect -- so a binary frame would
look identical to a protocol violation and tear the socket down, losing
every future broadcast to that client for no real reason. The raw
`receive()` never raises on message *type*; it only ever raises if called
again after a disconnect has already been observed (see Starlette's
WebSocket.receive()), which the `break` below prevents.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    bus = websocket.app.state.bus
    await websocket.accept()
    bus.register(websocket)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            # Anything else (a text frame, a binary frame, ...) is ignored --
            # this socket only exists to detect the client-initiated close;
            # it never expects the client to send anything meaningful.
    finally:
        bus.unregister(websocket)
