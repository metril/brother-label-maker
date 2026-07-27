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
