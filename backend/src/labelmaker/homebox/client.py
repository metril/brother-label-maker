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

The client is read-mostly: this app renders its own labels and treats
HomeBox as a data source, but the opt-in write helpers (create_entity,
add_attachment; gated by the `homebox_writes_enabled` setting at the router
layer) can create items and upload photos. All calls carry
`Authorization: Bearer <hb_ key>`; the key inherits the creating user's
permissions, so a read-only key keeps the whole integration read-only
server-side too.

Error taxonomy: transport failures and 5xx raise HomeBoxUnavailableError,
401/403 raise HomeBoxAuthError, a missing entity raises
HomeBoxNotFoundError, and a pre-entity-merge server (the /v1/items API
generation) raises HomeBoxVersionError from probe() -- this app targets
v0.26.1+ only (plan risk #4), and the probe exists to turn that hard
requirement into a clear message instead of a cascade of 404s.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

# Cap on how much of an upstream 4xx body is echoed into our own error message.
_MAX_ERROR_BODY_CHARS = 200


def _path_segment(value: str) -> str:
    """Percent-encode a caller-supplied id for use as ONE URL path segment, so
    `/`, `?`, `#` or `..` can't redirect the request (carrying the server's
    API key) to a different HomeBox endpoint."""
    encoded = quote(value, safe="")
    # quote() leaves "." alone, so a bare "."/".." would still be a dot segment.
    return encoded.replace(".", "%2E") if set(encoded) == {"."} else encoded


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


class HomeBoxValidationError(HomeBoxError):
    """HomeBox answered 422 to a write: the payload was rejected."""


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


class EntityAttachment(_ApiModel):
    """repo.EntityAttachment subset -- enough to find the attachment an
    upload just created (HomeBox titles it with the uploaded `name`)."""

    id: str = ""
    title: str = ""
    primary: bool = False
    type: str = ""


class Entity(EntitySummary):
    """repo.EntityOut -- the full single-entity shape (label-relevant
    subset; purchase/sold/warranty fields deliberately unmodeled)."""

    serial_number: str = Field("", validation_alias="serialNumber")
    model_number: str = Field("", validation_alias="modelNumber")
    manufacturer: str = ""
    notes: str = ""
    children: list[EntitySummary] = []
    attachments: list[EntityAttachment] = []


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


def build_client(
    url: str | None, api_key: str | None, *, timeout: float = 10.0
) -> HomeBoxClient | None:
    """`None` when either half is unset -- the ONE "is HomeBox configured"
    predicate, shared by main.py's lifespan (building the FIRST
    `app.state.homebox`) and api/router_settings.py's PUT handler
    (rebuilding it after `homebox_url`/`homebox_api_key` is overridden).
    Both call sites pass EFFECTIVE settings-overlay values, never
    `AppConfig` fields directly, so a DB-stored override takes effect
    immediately."""
    return HomeBoxClient(url, api_key, timeout=timeout) if url and api_key else None


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

    def _check(self, resp: httpx.Response, *, write: bool = False) -> httpx.Response:
        """Shared status mapping. 404 is returned to the caller for reads
        (its meaning is endpoint-specific); everything else that isn't 2xx
        raises. For writes 404/405 mean the route is missing (a server too
        old for writes) and 422 is a HomeBoxValidationError."""
        if resp.status_code in (401, 403):
            raise HomeBoxAuthError(
                f"HomeBox rejected the API key (HTTP {resp.status_code}) -- check "
                "HOMEBOX_API_KEY (an hb_-prefixed key from HomeBox's user settings)"
                + (" and that it has write access" if write else "")
            )
        if resp.status_code >= 500:
            raise HomeBoxUnavailableError(f"HomeBox server error (HTTP {resp.status_code})")
        if write and resp.status_code in (404, 405):
            raise HomeBoxVersionError(
                f"HomeBox server too old for writes (HTTP {resp.status_code} on this route; "
                "or the target entity no longer exists) -- upgrade HomeBox (v0.26.1+)"
            )
        body = resp.text[:_MAX_ERROR_BODY_CHARS]
        if resp.status_code == 422:
            raise HomeBoxValidationError(f"HomeBox rejected the request (HTTP 422): {body}")
        if resp.status_code >= 400 and resp.status_code != 404:
            raise HomeBoxError(f"HomeBox request failed (HTTP {resp.status_code}): {body}")
        return resp

    async def _send(
        self, method: str, path: str, *, write: bool = False, **kwargs
    ) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise HomeBoxUnavailableError(f"HomeBox unreachable at {self.base_url}: {exc}") from exc
        return self._check(resp, write=write)

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """GET with the shared error mapping (see `_check`)."""
        return await self._send("GET", path, params=params)

    async def _post_json(self, path: str, body: dict) -> httpx.Response:
        """POST a JSON body with the shared error mapping, write flavor."""
        return await self._send("POST", path, write=True, json=body)

    async def _post_multipart(
        self, path: str, *, files: dict, data: dict, timeout: float = 60.0
    ) -> httpx.Response:
        """POST multipart/form-data (uploads get a longer timeout than the
        client's 10s default)."""
        return await self._send("POST", path, write=True, files=files, data=data, timeout=timeout)

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
        resp = await self._get(f"/entities/{_path_segment(entity_id)}")
        if resp.status_code == 404:
            raise HomeBoxNotFoundError(f"HomeBox entity {entity_id} not found")
        return Entity.model_validate(resp.json())

    async def get_path(self, entity_id: str) -> list[PathSegment]:
        """Root-first ancestor chain including the entity itself -- the
        breadcrumb source ("Garage > Shelf B > Bin 3")."""
        resp = await self._get(f"/entities/{_path_segment(entity_id)}/path")
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
        resp = await self._get(f"/assets/{_path_segment(asset_id)}")
        if resp.status_code == 404:
            return []
        return EntityPage.model_validate(resp.json()).items

    async def create_entity(
        self,
        name: str,
        *,
        parent_id: str | None = None,
        entity_type_id: str | None = None,
        tag_ids: list[str] | None = None,
        description: str | None = None,
        quantity: int | None = None,
        location_id: str | None = None,
        manufacturer: str | None = None,
        model_number: str | None = None,
    ) -> Entity:
        """POST /v1/entities (repo.EntityCreate, camelCase) -> 201 EntityOut;
        the server assigns assetId when auto-increment is on. Unset optional
        fields are omitted from the body. `location_id` is only meaningful
        when the parent is an item."""
        body: dict = {"name": name}
        optional = {
            "description": description,
            "parentId": parent_id,
            "locationId": location_id,
            "entityTypeId": entity_type_id,
            "tagIds": tag_ids or None,
            "quantity": quantity,
            "manufacturer": manufacturer,
            "modelNumber": model_number,
        }
        body.update({k: v for k, v in optional.items() if v is not None})
        resp = await self._post_json("/entities", body)
        return Entity.model_validate(resp.json())

    async def list_tags(self) -> list[TagSummary]:
        resp = await self._get("/tags")
        if resp.status_code == 404:
            raise HomeBoxVersionError("/v1/tags missing -- HomeBox server too old")
        return [TagSummary.model_validate(t) for t in resp.json()]

    async def list_entity_types(self) -> list[EntityTypeSummary]:
        resp = await self._get("/entity-types")
        if resp.status_code == 404:
            raise HomeBoxVersionError("/v1/entity-types missing -- HomeBox server too old")
        return [EntityTypeSummary.model_validate(t) for t in resp.json()]

    async def add_attachment(
        self,
        entity_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        *,
        type: str = "photo",  # noqa: A002 -- HomeBox's own form field name
        primary: bool = False,
    ) -> Entity:
        """POST /v1/entities/{id}/attachments (multipart: file, name, type,
        primary) -> 201 EntityOut. A 404 here is the entity (or route) being
        absent; writes map it to the too-old-server error, so check the id
        via get_entity first when the distinction matters."""
        resp = await self._post_multipart(
            f"/entities/{_path_segment(entity_id)}/attachments",
            files={"file": (filename, content, content_type)},
            data={"name": filename, "type": type, "primary": "true" if primary else "false"},
        )
        return Entity.model_validate(resp.json())
