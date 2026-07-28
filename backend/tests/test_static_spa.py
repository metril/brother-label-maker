"""Tests for main.py's backend-side SPA fallback (task 2.13 review fix-up).

Verified LIVE against a real `frontend/dist` first (curl against a running
uvicorn with the frontend actually built) -- these tests build their OWN
tiny static directory instead of depending on `frontend/dist` existing at
test time (STATIC_DIR is monkeypatched per test, same "isolated tmp_path,
not incidental repo state" convention as conftest.py's own `app_config`
fixture), so the suite stays hermetic regardless of whether `npm run
build` has been run in this checkout.

Covers: a deep link (e.g. /presets, /history -- no file on disk at that
path, react-router's BrowserRouter routes it client-side once the SPA has
booted) gets index.html instead of a 404; a real static file (the JS/CSS
bundle, a font, ...) is still served as itself; an unmatched /api/* path
still 404s as JSON, never silently falling through to index.html; and a
REAL /api/* endpoint still wins over the catch-all (registration order).
"""

from __future__ import annotations

import httpx
import pytest

from labelmaker.config import AppConfig
from labelmaker.main import create_app


@pytest.fixture
async def spa_client(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Label Studio</title>")
    assets_dir = static_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('hi');")

    monkeypatch.setenv("STATIC_DIR", str(static_dir))

    app_config = AppConfig(
        printer_mode="mock",
        data_dir=tmp_path / "data",
        # I4 (conftest.py's own _DEFAULT_APP_CONFIG_KWARGS): pinned
        # explicitly so this fixture is hermetic against whatever the
        # ambient environment happens to say, same reasoning as that one.
        printer_init_strategy="classic",
        printer_bit_order="msb_first",
        printer_flip_pins=False,
    )
    app = create_app(app_config)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_root_serves_index_html(spa_client):
    resp = await spa_client.get("/")
    assert resp.status_code == 200
    assert "Label Studio" in resp.text
    assert resp.headers["content-type"].startswith("text/html")


async def test_deep_link_serves_spa_index_html(spa_client):
    """The actual review finding: GET /presets and /history used to 404
    (StaticFiles(html=True)'s own mount only special-cased the root path),
    breaking a hard refresh/bookmark/shared link on either new page."""
    for path in ("/presets", "/history"):
        resp = await spa_client.get(path)
        assert resp.status_code == 200, path
        assert "Label Studio" in resp.text
        assert resp.headers["content-type"].startswith("text/html")


async def test_unknown_api_path_still_404s_json(spa_client):
    resp = await spa_client.get("/api/nonexistent")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"detail": "not found"}


async def test_real_static_asset_still_served(spa_client):
    resp = await spa_client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('hi');"
    assert "javascript" in resp.headers["content-type"]


async def test_real_api_endpoint_still_wins_over_the_catch_all(spa_client):
    """Registration order: routers are added before the catch-all, so a
    genuinely-real endpoint like /api/health is never shadowed by it."""
    resp = await spa_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["printer_mode"] == "mock"


async def test_nul_byte_path_falls_back_to_index_html_not_a_500(spa_client):
    """Review fix-up (2nd round), confirmed live via an A/B probe harness:
    `(static_dir / full_path).resolve()` raises `ValueError` ("embedded
    null character") for a path containing a NUL byte -- an unauthenticated
    one-request 500 (with the old StaticFiles mount, this 404'd). Caught
    and treated as "not a real file", same as any other nonexistent path."""
    resp = await spa_client.get("/%00")
    assert resp.status_code == 200
    assert "Label Studio" in resp.text


async def test_overlong_path_segment_falls_back_to_index_html_not_a_500(spa_client):
    """Review fix-up (2nd round), confirmed live: a >255-byte path segment
    (any directory-brute-force scanner's own wordlist eventually produces
    one) raises `OSError` (ENAMETOOLONG) out of `Path.is_file()` -- also
    caught and treated as "not a real file" instead of a 500."""
    resp = await spa_client.get(f"/{'a' * 5000}")
    assert resp.status_code == 200
    assert "Label Studio" in resp.text


async def test_head_root_and_head_real_asset_still_200(spa_client):
    """Review fix-up (2nd round): `@app.get` only ever registered GET --
    Starlette's StaticFiles mount it replaced auto-added HEAD, so `HEAD /`
    and `HEAD` on a real asset had regressed to 405 (confirmed live),
    breaking any uptime monitor/reverse proxy that HEADs before GETing."""
    root = await spa_client.head("/")
    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")

    asset = await spa_client.head("/assets/app.js")
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    # A HEAD response carries no body -- Content-Length/headers only.
    assert asset.content == b""


async def test_no_static_dir_leaves_app_bootable_and_unmatched_paths_404(tmp_path, monkeypatch):
    """`_resolve_static_dir()`'s own contract: no dist yet (or STATIC_DIR
    pointing nowhere) -- the API must still boot standalone, and since no
    catch-all route is registered at all in that case, an arbitrary path
    404s the plain FastAPI way (not index.html, nothing to fall back to)."""
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "does-not-exist"))
    app_config = AppConfig(
        printer_mode="mock",
        data_dir=tmp_path / "data",
        printer_init_strategy="classic",
        printer_bit_order="msb_first",
        printer_flip_pins=False,
    )
    app = create_app(app_config)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health")
            assert health.status_code == 200

            resp = await client.get("/presets")
            assert resp.status_code == 404
