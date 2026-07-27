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

# I4: app_config's own explicit defaults for the three checkpoint-pending
# fields (printer_init_strategy/printer_bit_order/printer_flip_pins).
# AppConfig is a pydantic-settings BaseSettings model -- ANY field not
# passed explicitly to its constructor falls back to whatever the process
# environment says (env_prefix="", so e.g. a real `PRINTER_INIT_STRATEGY`
# set in a dev's shell or a CI runner's env would silently win). Byte-parity
# tests (test_api_print.py) hand-derive expected streams assuming specific
# values for these three -- if the ambient environment disagreed with that
# assumption, those tests would fail for a reason with nothing to do with
# the code under test. Pinning them here, explicitly, on every app_config
# the suite builds makes the whole suite hermetic against that.
_DEFAULT_APP_CONFIG_KWARGS = {
    "printer_init_strategy": "classic",
    "printer_bit_order": "msb_first",
    "printer_flip_pins": False,
}


@pytest.fixture
def app_config(tmp_path, request):
    """Builds an AppConfig with every checkpoint-pending field explicit
    (see _DEFAULT_APP_CONFIG_KWARGS above). Supports indirect parametrize
    overrides -- `@pytest.mark.parametrize("app_config", [{...}], indirect=True)`
    -- for the rare test that needs a non-default combination (e.g.
    test_api_print.py's e310bt/lsb_first/flip_pins=True worker-honors-config
    case); everything else gets the explicit defaults above regardless of
    what's in the process environment.
    """
    overrides = getattr(request, "param", {})
    kwargs = {**_DEFAULT_APP_CONFIG_KWARGS, **overrides}
    return AppConfig(printer_mode="mock", data_dir=tmp_path / "data", **kwargs)


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
