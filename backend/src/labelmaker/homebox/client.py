"""Async HomeBox API client (task 3.1).

Every shape in this module was pinned against the LIVE instance's own
swagger document (Homebox v0.26.2, `GET {base}/swagger/doc.json`, fetched
2026-07-28) rather than third-party docs, per docs/research/homebox.md's
own recommendation. Where the live spec disagrees with that research doc
(written pre-0.26.2), the live spec won:

- `EntitySummary` carries NO resolved-location field in this build; the
  ancestor chain comes from `GET /v1/entities/{id}/path` (an endpoint the
  research doc predates) -- no client-side tree walking is needed for a
  breadcrumb like "Garage > Shelf B > Bin 3".
- `GET /v1/entities` accepts ONLY q/page/pageSize/tags/parentIds -- there
  is no entityType filter param. Items vs locations are distinguished by
  `entityType.isLocation` on each row; whole-hierarchy browsing uses
  `GET /v1/entities/tree`.
- `GET /v1/assets/{id}` returns a standard pagination result of
  EntitySummary -- HomeBox's zero/one/many asset-id disambiguation (asset
  ids are NOT unique) maps directly onto `len(result.items)`.

The client is read-only by design: this app treats HomeBox purely as a
data source (research doc's recommendation) and renders its own labels.
All calls carry `Authorization: Bearer <hb_ key>`; the key inherits the
creating user's permissions, so a read-only key keeps the whole
integration read-only server-side too.

Error taxonomy: transport failures and 5xx raise HomeBoxUnavailableError,
401/403 raise HomeBoxAuthError, a missing entity raises
HomeBoxNotFoundError, and a pre-entity-merge server (the /v1/items API
generation) raises HomeBoxVersionError from probe() -- this app targets
v0.26.1+ only (plan risk #4), and the probe exists to turn that hard
requirement into a clear message instead of a cascade of 404s.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field


class HomeBoxError(Exception):
    """Base for every error this module raises deliberately."""


class HomeBoxAuthError(HomeBoxError):
    pass


class HomeBoxNotFoundError(HomeBoxError):
    pass


class HomeBoxVersionError(HomeBoxError):
    pass


class HomeBoxUnavailableError(HomeBoxError):
    pass


class _ApiModel(BaseModel):
    """Field names are snake_case locally; HomeBox's camelCase wire names
    are `validation_alias`es (NOT plain `alias`), so parsing accepts the
    wire form but serialization -- including FastAPI response models and
    their OpenAPI schemas in the proxy routes -- emits snake_case by
    construction, matching every other route in this app. Unknown wire
    fields are ignored (pydantic's default), so a HomeBox point release
    adding fields can't break parsing."""

    model_config = ConfigDict(populate_by_name=True)


class EntityTypeSummary(_ApiModel):
    id: str = ""
    name: str = ""
    # The item-vs-location discriminator in the unified entities API.
    is_location: bool = Field(False, validation_alias="isLocation")


class TagSummary(_ApiModel):
    id: str = ""
    name: str = ""
    color: str = ""


class EntitySummary(_ApiModel):
    """repo.EntitySummary -- the list/search/asset-lookup row shape.
    `parent` is the immediate container (itself a summary, recursively);
    it is NOT the nearest location ancestor -- use HomeBoxClient.get_path
    for that."""

    id: str
    name: str
    description: str = ""
    asset_id: str = Field("", validation_alias="assetId")
    archived: bool = False
    quantity: float | None = None
    entity_type: EntityTypeSummary | None = Field(None, validation_alias="entityType")
    parent: EntitySummary | None = None
    tags: list[TagSummary] = []
    thumbnail_id: str | None = Field(None, validation_alias="thumbnailId")
    image_id: str | None = Field(None, validation_alias="imageId")


class Entity(EntitySummary):
    """repo.EntityOut -- the full single-entity shape (label-relevant
    subset; purchase/sold/warranty fields deliberately unmodeled)."""

    serial_number: str = Field("", validation_alias="serialNumber")
    model_number: str = Field("", validation_alias="modelNumber")
    manufacturer: str = ""
    notes: str = ""
    children: list[EntitySummary] = []


class EntityPage(_ApiModel):
    """repo.EntityListResult / repo.PaginationResult-repo_EntitySummary --
    both share this shape (the former adds totalPrice, which labels don't
    care about)."""

    items: list[EntitySummary] = []
    page: int = 1
    page_size: int = Field(0, validation_alias="pageSize")
    total: int = 0


class TreeItem(_ApiModel):
    """repo.TreeItem -- GET /v1/entities/tree node. `type` is the lowercase
    string "location" or "item" (repo.EntityPathType's vocabulary)."""

    id: str
    name: str
    type: str = ""
    children: list[TreeItem] = []


class PathSegment(_ApiModel):
    """repo.EntityPath -- one ancestor in GET /v1/entities/{id}/path's
    root-first chain (the entity itself is the last segment)."""

    id: str
    name: str
    type: str = ""


class _Build(_ApiModel):
    version: str = ""


class HomeBoxStatus(_ApiModel):
    """v1.APISummary subset -- health + version for diagnostics."""

    health: bool = False
    title: str = ""
    build: _Build = _Build()


EntitySummary.model_rebuild()
TreeItem.model_rebuild()


class HomeBoxClient:
    """One instance per app, holding one connection pool; close() on app
    shutdown. `base_url` is the instance root (e.g.
    https://homebox.example.com) -- the /api/v1 prefix is appended here,
    matching the live swagger's basePath."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url + "/api/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """GET with the shared error mapping. 404 is returned to the caller
        (its meaning is endpoint-specific); everything else that isn't 2xx
        raises."""
        try:
            resp = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise HomeBoxUnavailableError(f"HomeBox unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise HomeBoxAuthError(
                f"HomeBox rejected the API key (HTTP {resp.status_code}) -- check "
                "HOMEBOX_API_KEY (an hb_-prefixed key from HomeBox's user settings)"
            )
        if resp.status_code >= 500:
            raise HomeBoxUnavailableError(f"HomeBox server error (HTTP {resp.status_code})")
        if resp.status_code >= 400 and resp.status_code != 404:
            raise HomeBoxError(f"HomeBox request failed (HTTP {resp.status_code}): {resp.text}")
        return resp

    async def status(self) -> HomeBoxStatus:
        """GET /v1/status -- unauthenticated on HomeBox's side, but sent with
        the same client (the header is simply ignored)."""
        resp = await self._get("/status")
        return HomeBoxStatus.model_validate(resp.json())

    async def probe(self) -> None:
        """Verify this instance speaks the unified entities API (v0.26.1+).

        A 404 on /entities from a healthy server almost certainly means the
        pre-merge items/locations generation -- confirmed by /items
        answering -- which gets the clear version error the plan calls for
        (risk #4) instead of every feature 404ing individually.
        """
        resp = await self._get("/entities", params={"pageSize": 1})
        if resp.status_code == 200:
            return
        old_gen = await self._get("/items", params={"pageSize": 1})
        if old_gen.status_code == 200:
            raise HomeBoxVersionError(
                "this HomeBox instance still uses the pre-v0.26 items/locations API; "
                "the integration requires the unified entities API (HomeBox v0.26.1+) "
                "-- upgrade HomeBox (back up first; set HBOX_AUTH_API_KEY_PEPPER "
                "before upgrading or v0.26+ crash-loops)"
            )
        raise HomeBoxUnavailableError(
            "HomeBox answered but /v1/entities is missing (HTTP 404) and /v1/items "
            "is not the reason -- is HOMEBOX_URL pointing at a HomeBox instance?"
        )

    async def list_entities(
        self,
        *,
        q: str | None = None,
        page: int = 1,
        page_size: int = 50,
        parent_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> EntityPage:
        """GET /v1/entities -- the exact filter set the live swagger
        documents; there is deliberately no entity-type param here (none
        exists server-side)."""
        params: dict = {"page": page, "pageSize": page_size}
        if q:
            params["q"] = q
        if parent_ids:
            params["parentIds"] = parent_ids
        if tags:
            params["tags"] = tags
        resp = await self._get("/entities", params=params)
        if resp.status_code == 404:
            raise HomeBoxUnavailableError(
                "/v1/entities missing -- run probe(); this instance may predate v0.26"
            )
        return EntityPage.model_validate(resp.json())

    async def get_entity(self, entity_id: str) -> Entity:
        resp = await self._get(f"/entities/{entity_id}")
        if resp.status_code == 404:
            raise HomeBoxNotFoundError(f"HomeBox entity {entity_id} not found")
        return Entity.model_validate(resp.json())

    async def get_path(self, entity_id: str) -> list[PathSegment]:
        """Root-first ancestor chain including the entity itself -- the
        breadcrumb source ("Garage > Shelf B > Bin 3")."""
        resp = await self._get(f"/entities/{entity_id}/path")
        if resp.status_code == 404:
            raise HomeBoxNotFoundError(f"HomeBox entity {entity_id} not found")
        return [PathSegment.model_validate(seg) for seg in resp.json()]

    async def get_tree(self, *, with_items: bool = False) -> list[TreeItem]:
        params = {"withItems": "true"} if with_items else None
        resp = await self._get("/entities/tree", params=params)
        if resp.status_code == 404:
            raise HomeBoxUnavailableError(
                "/v1/entities/tree missing -- run probe(); this instance may predate v0.26"
            )
        return [TreeItem.model_validate(node) for node in resp.json()]

    async def find_by_asset_id(self, asset_id: str) -> list[EntitySummary]:
        """GET /v1/assets/{id} -- asset ids are NOT unique, so this always
        returns a list; callers replicate HomeBox's own zero/one/many
        disambiguation (research doc recommendation #40). A 404 is treated
        as zero matches."""
        resp = await self._get(f"/assets/{asset_id}")
        if resp.status_code == 404:
            return []
        return EntityPage.model_validate(resp.json()).items
