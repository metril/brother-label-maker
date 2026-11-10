"""Every /api/v1 route is documented: summary, tag, success response and errors."""

from __future__ import annotations

import pytest

_METHODS = ("get", "post", "put", "patch", "delete")


@pytest.fixture
async def spec(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    return resp.json()


def _operations(spec):
    for path, item in spec["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method in _METHODS:
            if method in item:
                yield f"{method.upper()} {path}", item[method]


def _has_schema_or_binary(content: dict) -> bool:
    return any(
        media != "application/json" or bool(body.get("schema")) for media, body in content.items()
    )


async def test_every_v1_route_is_documented(spec):
    problems: list[str] = []
    ops = list(_operations(spec))
    assert len(ops) > 30
    for name, op in ops:
        if not op.get("summary"):
            problems.append(f"{name}: no summary")
        if not op.get("tags"):
            problems.append(f"{name}: no tags")
        responses = op.get("responses", {})
        # Redirects and 204s legitimately have no body.
        success = [c for c in responses if c.isdigit() and int(c) < 400]
        if not success:
            problems.append(f"{name}: no success response")
        for code in success:
            if code.startswith("3") or code == "204":
                continue
            content = responses[code].get("content")
            if code == "200" and not content:
                problems.append(f"{name}: 200 without schema or media type")
            elif content and not _has_schema_or_binary(content):
                problems.append(f"{name}: {code} without a schema")
        if not any(c.isdigit() and int(c) >= 400 for c in responses):
            problems.append(f"{name}: declares no error responses")
    assert not problems, "\n".join(problems)


async def test_error_responses_use_the_envelope(spec):
    for name, op in _operations(spec):
        for code, resp in op["responses"].items():
            if code.isdigit() and int(code) >= 400:
                ref = resp["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorResponse"), f"{name} {code}: {ref}"


async def test_binary_routes_declare_media_types(spec):
    expect = {
        "GET /api/v1/images/{image_id}": "image/png",
        "GET /api/v1/images/{image_id}/thumb": "image/png",
        "GET /api/v1/history/{job_id}/thumbnail": "image/png",
        "GET /api/v1/print/jobs/{job_id}/stream": "application/octet-stream",
        "GET /api/v1/els/label": "image/png",
        "GET /api/v1/symbols/{symbol_id}": "image/svg+xml",
    }
    ops = dict(_operations(spec))
    for name, media in expect.items():
        assert media in ops[name]["responses"]["200"]["content"], name
    assert "304" in ops["GET /api/v1/symbols/{symbol_id}"]["responses"]
    assert "304" in ops["GET /api/v1/symbols"]["responses"]
