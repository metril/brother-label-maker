"""HomeBox proxy routes + integration settings (task 3.2).

The browser never talks to HomeBox directly: the hb_ API key lives only in
this process (config.homebox_api_key), and HomeBox has no reason to allow
this app's origin via CORS. So every read the frontend needs is proxied
1:1 here through the read-only HomeBoxClient, with the client's error
taxonomy mapped onto our HTTP surface:

- integration unconfigured           -> 503 (deps.get_homebox's hint)
- entity/asset genuinely absent      -> 404
- HomeBox unreachable / 5xx / bad key / pre-0.26 server -> 502, with the
  client's own actionable message as the detail (these are deployment
  problems, not browser-user problems -- a gateway error is honest).

GET /api/homebox/status is the one route that answers 200 regardless, so
the frontend can decide whether to show HomeBox UI at all without a
try/except dance.

Settings: `qr_base_url` (db settings table, key "homebox_qr_base_url") is
the base URL embedded in label QR codes -- following HomeBox's own URL
scheme (base/item/{uuid}, base/a/{assetId}) but NEVER HomeBox's own
fragile base-URL resolution chain (research doc: Hostname setting ->
X-Forwarded-Host -> Referer -> fallback, easily wrong behind a proxy).
When unset it falls back to config.homebox_url, which is right whenever
the app reaches HomeBox by its public URL; deployments that reach HomeBox
by an internal address set this to the public one so printed QR codes
still resolve for phones.
"""

from __future__ import annotations

from collections.abc import Awaitable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from labelmaker.api.deps import AppConfigDep, DbDep, HomeBoxDep
from labelmaker.homebox import (
    Entity,
    EntityPage,
    EntitySummary,
    HomeBoxError,
    HomeBoxNotFoundError,
    HomeBoxVersionError,
    PathSegment,
    TreeItem,
)

router = APIRouter(tags=["homebox"])

QR_BASE_URL_KEY = "homebox_qr_base_url"


async def _proxy[T](call: Awaitable[T]) -> T:
    """Shared error mapping for every proxied HomeBox call.

    - HomeBoxNotFoundError -> 404 (the entity/asset genuinely isn't there).
    - Any other HomeBoxError (auth, version, unavailable) -> 502: the app
      is fine, the HomeBox side of the bridge is not.
    - ValueError -> 502 too: whatever answered at HOMEBOX_URL replied with
      non-JSON (json.JSONDecodeError) or a non-HomeBox shape
      (pydantic.ValidationError subclasses ValueError) -- e.g. an SSO
      proxy's login page or a typo'd host serving HTML. Without this, the
      client's model_validate(resp.json()) would surface as a 500.
    """
    try:
        return await call
    except HomeBoxNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HomeBoxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HomeBox returned a response this app could not parse: {exc}",
        ) from exc


@router.get("/homebox/status")
async def homebox_status(config: AppConfigDep) -> dict:
    """Always 200 -- the frontend's show-or-hide signal for HomeBox UI.

    Beyond reachability this also runs the client's generation probe, so a
    pre-v0.26 HomeBox reports as reachable-but-unhealthy with the upgrade
    instructions in `error` (plan risk #4) instead of looking healthy here
    and then 502ing on every browse call.
    """
    if not (config.homebox_url and config.homebox_api_key):
        return {"configured": False, "reachable": None, "healthy": None, "version": None,
                "error": None}
    from labelmaker.homebox import HomeBoxClient  # narrow import for monkeypatching in tests

    version: str | None = None
    try:
        # A fresh short-timeout client rather than app.state's: a hung
        # HomeBox shouldn't hold this endpoint for the full default timeout.
        probe_client = HomeBoxClient(config.homebox_url, config.homebox_api_key, timeout=5.0)
        try:
            status = await probe_client.status()
            version = status.build.version or None
            await probe_client.probe()
        finally:
            await probe_client.close()
    except HomeBoxVersionError as exc:
        # Server answers but speaks the pre-merge API generation.
        return {"configured": True, "reachable": True, "healthy": False, "version": version,
                "error": str(exc)}
    except HomeBoxError as exc:
        return {"configured": True, "reachable": False, "healthy": None, "version": None,
                "error": str(exc)}
    except Exception as exc:  # noqa: B902 -- non-JSON / non-HomeBox response shape
        # Whatever answered at HOMEBOX_URL is not a HomeBox API (SSO login
        # page, default vhost, ...). This endpoint's contract is "always
        # 200"; a 500 here would read as "the app is broken" instead of
        # "HomeBox is misconfigured".
        return {"configured": True, "reachable": False, "healthy": None, "version": None,
                "error": f"HomeBox URL answered, but not with a HomeBox API response: {exc}"}
    return {
        "configured": True,
        "reachable": True,
        "healthy": status.health,
        "version": version,
        "error": None,
    }


# The homebox.client models parse HomeBox's camelCase via validation_alias
# only, so FastAPI's response serialization AND the OpenAPI schema are
# snake_case by construction -- no response_model_by_alias juggling needed
# (see _ApiModel's docstring).
@router.get("/homebox/entities")
async def list_entities(
    homebox: HomeBoxDep,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    parent_id: str | None = None,
) -> EntityPage:
    return await _proxy(
        homebox.list_entities(
            q=q, page=page, page_size=page_size,
            parent_ids=[parent_id] if parent_id else None,
        )
    )


@router.get("/homebox/entities/tree")
async def entities_tree(homebox: HomeBoxDep, with_items: bool = False) -> list[TreeItem]:
    return await _proxy(homebox.get_tree(with_items=with_items))


@router.get("/homebox/entities/{entity_id}")
async def get_entity(homebox: HomeBoxDep, entity_id: str) -> Entity:
    return await _proxy(homebox.get_entity(entity_id))


@router.get("/homebox/entities/{entity_id}/path")
async def get_entity_path(homebox: HomeBoxDep, entity_id: str) -> list[PathSegment]:
    return await _proxy(homebox.get_path(entity_id))


@router.get("/homebox/assets/{asset_id}")
async def find_by_asset_id(homebox: HomeBoxDep, asset_id: str) -> list[EntitySummary]:
    """Zero, one, or many matches -- asset ids are not unique; the caller
    replicates HomeBox's own disambiguation on the length."""
    return await _proxy(homebox.find_by_asset_id(asset_id))


class HomeBoxSettings(BaseModel):
    qr_base_url: str | None
    effective_qr_base_url: str | None


class HomeBoxSettingsUpdate(BaseModel):
    # None clears the override (fall back to config.homebox_url). The
    # max_length is a Field(...) bound (not validator-only) so it reaches
    # the schema and a settings form can pre-empt it (handoff §8).
    qr_base_url: str | None = Field(None, max_length=255)

    @field_validator("qr_base_url")
    @classmethod
    def _http_url_no_trailing_slash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")) or value in ("http://", "https://"):
            raise ValueError("qr_base_url must be an http(s) URL, e.g. https://homebox.example.com")
        if any(ch.isspace() for ch in value):
            # Embedded whitespace would be baked verbatim into printed QR
            # payloads and break every scan.
            raise ValueError("qr_base_url must not contain whitespace")
        return value


async def _settings_response(db: DbDep, config: AppConfigDep) -> HomeBoxSettings:
    stored = await db.get_setting(QR_BASE_URL_KEY)
    fallback = config.homebox_url.rstrip("/") if config.homebox_url else None
    return HomeBoxSettings(
        qr_base_url=stored,
        effective_qr_base_url=stored or fallback,
    )


@router.get("/homebox/settings")
async def get_homebox_settings(db: DbDep, config: AppConfigDep) -> HomeBoxSettings:
    return await _settings_response(db, config)


@router.put("/homebox/settings")
async def put_homebox_settings(
    body: HomeBoxSettingsUpdate, db: DbDep, config: AppConfigDep
) -> HomeBoxSettings:
    await db.set_setting(QR_BASE_URL_KEY, body.qr_base_url)
    return await _settings_response(db, config)
