"""Uniform error envelope: {"error": {"code", "message", "details"}}."""

from __future__ import annotations

SENTINEL = "s3cret-input-value"


def _add_first(app, path, fn):
    # Ahead of the SPA catch-all (when a built frontend exists).
    app.add_api_route(path, fn, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


def _assert_envelope(body: dict, code: str) -> dict:
    assert set(body) == {"error"}
    err = body["error"]
    assert set(err) == {"code", "message", "details"}
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    return err


async def test_404_unknown_job(client):
    resp = await client.get("/api/v1/history/nope")
    assert resp.status_code == 404
    _assert_envelope(resp.json(), "not_found")


async def test_404_unknown_api_path(client):
    resp = await client.get("/api/v1/definitely-not-a-route")
    assert resp.status_code == 404
    _assert_envelope(resp.json(), "not_found")


async def test_405_method_not_allowed(client):
    resp = await client.post("/api/v1/health")
    assert resp.status_code == 405
    _assert_envelope(resp.json(), "method_not_allowed")


async def test_409_conflict_envelope(app_and_client):
    app, client = app_and_client
    from labelmaker.api.errors import ApiError

    async def _conflict():
        raise ApiError(409, "conflict", "already exists", [{"loc": ["x"], "msg": "m", "type": "t"}])

    _add_first(app, "/api/v1/_boom_conflict", _conflict)

    resp = await client.get("/api/v1/_boom_conflict")
    assert resp.status_code == 409
    err = _assert_envelope(resp.json(), "conflict")
    assert err["details"] == [{"loc": ["x"], "msg": "m", "type": "t"}]


async def test_422_validation_has_details_and_no_input_echo(client):
    resp = await client.post("/api/v1/render/preview", json={"labels": SENTINEL, "extra": SENTINEL})
    assert resp.status_code == 422
    err = _assert_envelope(resp.json(), "validation_error")
    assert err["details"]
    for d in err["details"]:
        assert set(d) == {"loc", "msg", "type"}
    assert SENTINEL not in resp.text


async def test_500_does_not_leak(app_and_client):
    app, client = app_and_client

    async def _boom():
        raise RuntimeError(f"internal detail {SENTINEL}")

    _add_first(app, "/api/v1/_boom", _boom)

    from httpx import ASGITransport, AsyncClient

    # The shared client re-raises server exceptions; use one that returns the 500.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        resp = await c.get("/api/v1/_boom")
    assert resp.status_code == 500
    err = _assert_envelope(resp.json(), "internal_error")
    assert SENTINEL not in resp.text
    assert err["message"] == "internal server error"
