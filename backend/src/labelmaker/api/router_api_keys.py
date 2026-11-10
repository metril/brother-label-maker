"""Settings-managed API keys (GET/POST /api-keys, DELETE /api-keys/{id}).

Management requires a browser session, never a bearer key, so a leaked key
cannot mint more keys. Under AUTH_MODE=none there is no session concept and
the whole API is open, so these routes are open too (keys are optional and
ignored in that mode).
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from labelmaker.api import api_keys
from labelmaker.api.deps import DbDep
from labelmaker.api.errors import ApiError, err
from labelmaker.api.schemas import ApiKeyCreatedOut, ApiKeyOut

logger = logging.getLogger(__name__)


def require_session(request: Request) -> None:
    if request.scope.get("auth_kind") == "api_key":
        raise ApiError(403, "forbidden", "API keys cannot manage API keys; sign in with a session")


router = APIRouter(prefix="/api-keys", tags=["api-keys"], dependencies=[Depends(require_session)])


class ApiKeyCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100, description="Label for the key")]
    scope: Literal["read", "write"] = Field(
        default="read", description="`read` allows only GET/HEAD/OPTIONS; `write` allows all"
    )


def _public(row: dict) -> dict:
    return {k: row[k] for k in ("id", "name", "prefix", "scope", "created_at", "last_used_at")}


@router.get("", summary="List API keys", response_model=list[ApiKeyOut], responses=err(401, 403))
async def list_keys(db: DbDep) -> list[dict]:
    """Active keys, newest first. Plaintext is never returned here."""
    return [_public(r) for r in await db.list_api_keys()]


@router.post(
    "",
    status_code=201,
    summary="Create an API key",
    response_model=ApiKeyCreatedOut,
    responses=err(401, 403, 422),
)
async def create_key(body: ApiKeyCreate, db: DbDep) -> dict:
    """Returns the plaintext key once; it cannot be retrieved again."""
    name = body.name.strip()
    if not name:
        raise ApiError(422, "validation_error", "name must not be blank")
    plaintext, prefix, digest = api_keys.generate_key()
    row = await db.create_api_key(name, body.scope, prefix, digest)
    logger.info("api key created: prefix=%s scope=%s", prefix, body.scope)
    return {**_public(row), "key": plaintext}


@router.delete(
    "/{key_id}",
    status_code=204,
    summary="Revoke an API key",
    response_class=Response,
    responses=err(401, 403, 404),
)
async def revoke_key(key_id: str, db: DbDep) -> Response:
    if not await db.revoke_api_key(key_id):
        raise ApiError(404, "not_found", "API key not found")
    api_keys.forget_touch(key_id)
    return Response(status_code=204)
