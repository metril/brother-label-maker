"""Shared fixtures for the API test suite (test_api_*.py).

Every API test runs in mock printer mode against a tmp_path data_dir, wired
directly to the ASGI app via httpx.ASGITransport -- no real socket/port.
ASGITransport does not drive the ASGI lifespan protocol on its own, so the
`app_and_client` fixture drives it explicitly via
`app.router.lifespan_context(app)` (the same async context manager
`create_app`'s `lifespan=` callable becomes), which starts the db/bus/worker
exactly as a real server boot would and tears them down on fixture exit.
"""

from __future__ import annotations

import httpx
import pytest

from labelmaker.config import AppConfig
from labelmaker.main import create_app


@pytest.fixture
def app_config(tmp_path):
    return AppConfig(printer_mode="mock", data_dir=tmp_path / "data")


@pytest.fixture
async def app_and_client(app_config):
    app = create_app(app_config)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


@pytest.fixture
async def client(app_and_client):
    return app_and_client[1]
