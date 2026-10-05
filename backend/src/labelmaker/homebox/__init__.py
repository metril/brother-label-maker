"""HomeBox integration (Phase 3): API client for the unified
/v1/entities generation (HomeBox v0.26.1+). See client.py's module
docstring for the live-swagger provenance of every shape."""

from labelmaker.homebox.client import (
    Entity,
    EntityAttachment,
    EntityPage,
    EntitySummary,
    EntityTypeSummary,
    HomeBoxAuthError,
    HomeBoxClient,
    HomeBoxError,
    HomeBoxNotFoundError,
    HomeBoxStatus,
    HomeBoxUnavailableError,
    HomeBoxValidationError,
    HomeBoxVersionError,
    PathSegment,
    TagSummary,
    TreeItem,
    build_client,
)

__all__ = [
    "Entity",
    "EntityPage",
    "EntityAttachment",
    "EntitySummary",
    "EntityTypeSummary",
    "HomeBoxAuthError",
    "HomeBoxClient",
    "HomeBoxError",
    "HomeBoxNotFoundError",
    "HomeBoxStatus",
    "HomeBoxUnavailableError",
    "HomeBoxValidationError",
    "HomeBoxVersionError",
    "PathSegment",
    "TagSummary",
    "TreeItem",
    "build_client",
]
