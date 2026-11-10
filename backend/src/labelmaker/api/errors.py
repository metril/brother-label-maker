"""Uniform API error envelope: ``{"error": {"code", "message", "details"}}``.

Every error the API emits -- explicit `ApiError`s, framework `HTTPException`s
(404 for unknown routes, 405, ...), request-validation failures and
unhandled exceptions -- goes through the handlers registered by
`register_error_handlers`. `details` for validation errors carries only
`loc`/`msg`/`type`, never the submitted input (it may hold secrets).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "auth_required",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
    507: "insufficient_storage",
}


def code_for_status(status: int) -> str:
    return _STATUS_CODES.get(status, "http_error")


class ApiError(HTTPException):
    """Raise from a route to emit the error envelope with a stable `code`."""

    def __init__(
        self, status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(status_code=status, detail=message)
        self.code = code
        self.message = message
        self.details = details


class ErrorBody(BaseModel):
    code: str = Field(description="Stable snake_case error code")
    message: str = Field(description="Human-readable message")
    details: list[dict[str, Any]] | None = Field(
        default=None, description="Optional structured details (validation: loc/msg/type)"
    )


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"error": {"code": "not_found", "message": "preset not found", "details": None}}
            ]
        }
    )

    error: ErrorBody


def err(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` dict documenting the envelope for each status."""
    return {s: {"model": ErrorResponse, "description": code_for_status(s)} for s in statuses}


def envelope(
    status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def _use_envelope_for_422(app: FastAPI) -> None:
    """FastAPI documents its automatic 422 as `HTTPValidationError`, but the
    validation handler below emits the envelope; point the schema at the
    envelope and drop the unused built-in schemas."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = original()
            ref = {"$ref": "#/components/schemas/ErrorResponse"}
            for item in schema.get("paths", {}).values():
                for op in item.values():
                    if not isinstance(op, dict):
                        continue
                    content = op.get("responses", {}).get("422", {}).get("content", {})
                    body = content.get("application/json")
                    if body and body.get("schema", {}).get("$ref", "").endswith(
                        "/HTTPValidationError"
                    ):
                        body["schema"] = ref
            components = schema.get("components", {}).get("schemas", {})
            components.pop("HTTPValidationError", None)
            components.pop("ValidationError", None)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def _validation_message(details: list[dict[str, Any]]) -> str:
    """Names the offending fields (from `loc`) -- never the submitted values."""
    fields: list[str] = []
    for d in details:
        loc = [str(p) for p in d["loc"]]
        if loc and loc[0] in ("body", "query", "path", "header", "cookie"):
            loc = loc[1:]
        name = ".".join(loc)[:80]
        if name and name not in fields:
            fields.append(name)
    if not fields:
        return "request validation failed"
    label = "invalid field" if len(fields) == 1 else "invalid fields"
    return f"{label}: {', '.join(fields[:5])}" + (", ..." if len(fields) > 5 else "")


def register_error_handlers(app: FastAPI) -> None:
    _use_envelope_for_422(app)
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else code_for_status(exc.status_code)
        response = envelope(exc.status_code, code_for_status(exc.status_code), message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return envelope(422, "validation_error", _validation_message(details), details)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return envelope(500, "internal_error", "internal server error")
