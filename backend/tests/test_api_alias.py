"""Legacy unversioned /api alias: still works, flagged deprecated, same gating."""

from __future__ import annotations

import re

import pytest
from test_api_auth import _OIDC_CONFIGURED


async def test_legacy_path_works_with_deprecation_header(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["deprecation"] == "true"


async def test_v1_path_has_no_deprecation_header(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "deprecation" not in resp.headers


async def test_legacy_and_v1_return_same_body(client):
    assert (await client.get("/api/tapes")).json() == (await client.get("/api/v1/tapes")).json()


async def test_legacy_els_path_not_flagged_deprecated(client):
    resp = await client.get("/api/els/label")
    assert "deprecation" not in resp.headers


def _openapi(app) -> dict:
    # OIDC mode withholds /openapi.json over HTTP; build the schema directly.
    from fastapi import FastAPI

    return FastAPI.openapi(app)


def _exempt(path: str) -> bool:
    n = re.sub(r"^/api/v1", "/api", path)
    return n == "/api/health" or n.startswith(("/api/auth/", "/api/els/"))


@_OIDC_CONFIGURED
@pytest.mark.parametrize("prefix", ["/api/v1", "/api"])
async def test_every_non_exempt_route_is_gated_under_both_prefixes(app_and_client, prefix):
    app, client = app_and_client
    checked = 0
    # The OpenAPI schema lists every /api/v1 route; the legacy alias mounts the
    # same routers, so the same (method, path) set exists under /api.
    for v1_path, ops in _openapi(app)["paths"].items():
        if _exempt(v1_path):
            continue
        path = re.sub(r"\{[^}]+\}", "x", prefix + v1_path[len("/api/v1") :])
        for method in ops:
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            resp = await client.request(method.upper(), path)
            assert resp.status_code == 401, (method, path, resp.status_code)
            assert resp.json()["error"]["code"] == "auth_required"
            checked += 1
    assert checked > 20


@_OIDC_CONFIGURED
@pytest.mark.parametrize("prefix", ["/api/v1", "/api"])
async def test_exempt_routes_stay_open_under_both_prefixes(client, prefix):
    assert (await client.get(f"{prefix}/health")).status_code == 200
    assert (await client.get(f"{prefix}/auth/me")).status_code == 200
