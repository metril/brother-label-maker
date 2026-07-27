"""WS /api/ws: register the connection with the app's EventBus for its
lifetime, so it receives every print-job lifecycle broadcast (job.queued/
job.started/job.done/job.failed -- see jobs/worker.py and router_print.py).

The client never needs to send anything; `receive_text()` is only how
Starlette/FastAPI's WebSocket API detects a client-initiated close
(`WebSocketDisconnect`) -- broadcasts are pushed independently by
EventBus.broadcast() calling `send_json` on this same connection from
elsewhere (the worker task), which is safe to interleave with an in-flight
receive on the same socket.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    bus = websocket.app.state.bus
    await websocket.accept()
    bus.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        bus.unregister(websocket)
