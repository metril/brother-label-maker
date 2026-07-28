"""Shared fixtures for the whole test suite.

Every API test (test_api_*.py) runs in mock printer mode against a tmp_path
data_dir, wired directly to the ASGI app via httpx.ASGITransport -- no real
socket/port. ASGITransport does not drive the ASGI lifespan protocol on its
own, so the `app_and_client` fixture drives it explicitly via
`app.router.lifespan_context(app)` (the same async context manager
`create_app`'s `lifespan=` callable becomes), which starts the db/bus/worker
exactly as a real server boot would and tears them down on fixture exit.

`_isolated_render_registry` below is unrelated to the API-test fixtures
above -- it applies to every test in the whole session (this is the only
conftest.py under tests/), not just test_api_*.py.
"""

from __future__ import annotations

import httpx
import pytest

from labelmaker.config import AppConfig
from labelmaker.main import create_app
from labelmaker.render.types.base import _REGISTRY


@pytest.fixture(autouse=True)
def _isolated_render_registry():
    """Registry test pollution (deferred from 1.2): labelmaker.render.types.
    base._REGISTRY is a bare module-level dict, mutated in place by every
    @register(...) class decorator. A type registered at TEST-MODULE import
    time (decorator on a class body, e.g. a "dummy" test-only renderer)
    would otherwise stay registered for the rest of the whole pytest
    session -- Python only imports/decorates a module once -- silently
    changing what list_types()/get_renderer() return for every other test
    file that happens to run afterward (e.g. an assertion like "exactly 4
    types" would flake depending on collection/run order).

    Snapshotting a shallow copy of the registry before each test and
    restoring it after undoes any register() a test performed (directly, or
    via its own autouse fixture -- see test_render_registry.py's
    `_register_dummy`, which relies on this fixture for cleanup rather than
    registering at import time). Fixture teardown order is LIFO, and this
    conftest-level fixture is requested before same-scope fixtures declared
    in a test module, so the snapshot taken here never includes a test-local
    registration, and the restore here always runs after that
    registration's own (no-op) teardown -- see test_render_registry.py.
    """
    snapshot = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)

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
# the suite builds makes the whole suite hermetic against that. The same
# applies to homebox_url/homebox_api_key: an ambient HOMEBOX_URL/
# HOMEBOX_API_KEY in a dev shell or CI runner must not silently enable the
# HomeBox integration (and its outbound calls) in tests unrelated to it.
_DEFAULT_APP_CONFIG_KWARGS = {
    "printer_init_strategy": "classic",
    "printer_bit_order": "msb_first",
    "printer_flip_pins": False,
    "homebox_url": None,
    "homebox_api_key": None,
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
