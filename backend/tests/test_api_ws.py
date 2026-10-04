"""Tests for WS /api/ws: connect, POST /api/print, observe the
job.queued -> job.started -> job.done event sequence.

Uses starlette.testclient.TestClient rather than the httpx.ASGITransport +
manual-lifespan fixtures the rest of test_api_*.py use: httpx has no
WebSocket support, and TestClient's portal-based `with` block already drives
the ASGI lifespan (startup/shutdown) on its own, so no manual
`app.router.lifespan_context` is needed here either. This is the only file
in the suite that imports starlette.testclient; the resulting
StarletteDeprecationWarning ("install httpx2 instead") is a test-
infrastructure detail upstream of this task (this backend depends on httpx,
per the task brief), suppressed via the scoped pyproject.toml
`filterwarnings` entry rather than adding an undocumented extra dependency.

`WebSocketTestSession.receive_json()` has no built-in timeout -- a stuck
event loop would hang the test forever. `_receive_json_bounded` runs each
receive in a daemon thread with `.join(timeout)` so a broken broadcast fails
the test in a few seconds instead of hanging the suite.
"""

from __future__ import annotations

import threading

import pytest
from starlette.testclient import TestClient

from labelmaker.config import AppConfig
from labelmaker.main import create_app

_RECEIVE_TIMEOUT_S = 2.0
_MAX_EVENTS = 10


def _receive_json_bounded(ws, timeout: float = _RECEIVE_TIMEOUT_S) -> dict:
    outcome: dict = {}

    def _target() -> None:
        try:
            outcome["value"] = ws.receive_json()
        except Exception as exc:  # pragma: no cover - surfaced via outcome, not raised here
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail(f"WS receive_json timed out after {timeout}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def test_ws_observes_job_queued_started_done_in_order(tmp_path):
    config = AppConfig(printer_mode="mock", data_dir=tmp_path / "data")
    app = create_app(config)

    with TestClient(app) as client, client.websocket_connect("/api/ws") as ws:
        resp = client.post(
            "/api/print",
            json={
                "labels": [
                    {
                        "type": "text",
                        "tape": {"width_mm": 24, "family": "tze"},
                        "params": {"lines": ["HELLO"]},
                    }
                ],
                "options": {"chain_mode": "cut_each"},
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        events = []
        for _ in range(_MAX_EVENTS):
            event = _receive_json_bounded(ws)
            events.append(event)
            if event.get("event") == "job.done":
                break
        else:
            pytest.fail(f"never observed job.done within {_MAX_EVENTS} events: {events}")

    names = [e["event"] for e in events]
    assert "job.queued" in names
    assert "job.started" in names
    assert "job.done" in names
    assert names.index("job.queued") < names.index("job.started") < names.index("job.done")

    queued_event = next(e for e in events if e["event"] == "job.queued")
    assert queued_event["job_id"] == job_id


# --- I6: a binary frame from the client must not kill the connection ---


def test_ws_tolerates_a_binary_frame_and_still_delivers_a_later_event(tmp_path):
    config = AppConfig(printer_mode="mock", data_dir=tmp_path / "data")
    app = create_app(config)

    with TestClient(app) as client, client.websocket_connect("/api/ws") as ws:
        # A stray binary frame -- ws.py's old `receive_text()` loop would
        # raise on this (unexpected message type) and tear the connection
        # down; the fixed `receive()` loop must just ignore it.
        ws.send_bytes(b"\x00\x01\x02\xff")

        resp = client.post(
            "/api/print",
            json={
                "labels": [
                    {
                        "type": "text",
                        "tape": {"width_mm": 24, "family": "tze"},
                        "params": {"lines": ["HELLO"]},
                    }
                ],
                "options": {"chain_mode": "cut_each"},
            },
        )
        assert resp.status_code == 202

        # The connection must still be alive and still receive broadcasts --
        # this would time out (test_ws_receive_json_bounded's pytest.fail)
        # if the binary frame had killed it.
        event = _receive_json_bounded(ws)
        assert event["event"] == "job.queued"


async def test_broadcast_drops_a_hung_client_without_stalling_others(monkeypatch):
    import asyncio

    from labelmaker.jobs import events
    from labelmaker.jobs.events import EventBus

    monkeypatch.setattr(events, "_SEND_TIMEOUT_S", 0.05)

    class _Hung:
        closed = False

        async def send_json(self, data):
            await asyncio.sleep(3600)

        async def close(self):
            self.closed = True

    class _Ok:
        def __init__(self):
            self.got = []

        async def send_json(self, data):
            self.got.append(data)

    bus, hung, ok = EventBus(), _Hung(), _Ok()
    bus.register(hung)
    bus.register(ok)

    await asyncio.wait_for(bus.broadcast({"event": "x"}), timeout=2)

    assert ok.got == [{"event": "x"}]
    assert hung not in bus._clients and ok in bus._clients
    await asyncio.sleep(0)  # let the scheduled close() run
    assert hung.closed is True
