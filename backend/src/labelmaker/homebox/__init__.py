"""HomeBox integration (Phase 3): read-only API client for the unified
/v1/entities generation (HomeBox v0.26.1+). See client.py's module
docstring for the live-swagger provenance of every shape."""

from labelmaker.homebox.client import (
    Entity,
    EntityPage,
    EntitySummary,
    EntityTypeSummary,
    HomeBoxAuthError,
    HomeBoxClient,
    HomeBoxError,
    HomeBoxNotFoundError,
    HomeBoxStatus,
    HomeBoxUnavailableError,
    HomeBoxVersionError,
    PathSegment,
    TagSummary,
    TreeItem,
    build_client,
)

__all__ = [
    "Entity",
    "EntityPage",
    "EntitySummary",
    "EntityTypeSummary",
    "HomeBoxAuthError",
    "HomeBoxClient",
    "HomeBoxError",
    "HomeBoxNotFoundError",
    "HomeBoxStatus",
    "HomeBoxUnavailableError",
    "HomeBoxVersionError",
    "PathSegment",
    "TagSummary",
    "TreeItem",
    "build_client",
]
