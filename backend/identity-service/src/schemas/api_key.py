from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from shared.core import pagination

__all__ = (
    "ApiKeyCreate",
    "ApiKeyCreateResponse",
    "ApiKeyRead",
    "ApiKeyTokenInfo",
    "ApiKeyUpdate",
    "ApiKeyListQueryParams",
    "ApiKeyListParams",
    "ApiKeyStatusCounts",
    "ApiKeyListResponse",
)


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    workspace_id: int = Field(..., gt=0)
    expires_at: datetime | None = None
    # RBAC permission names (see shared.rbac.catalog). No default: a key with an
    # empty list authenticates but authorizes nothing, which is the only safe
    # thing to hand out when the caller did not say what the key is for.
    scopes: list[str] = Field(default_factory=list)


class ApiKeyUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyRead(BaseModel):
    id: int
    name: str
    workspace_id: int
    public_id: str
    owner_id: int
    owner_username: str
    scopes: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyRead
    key: str


class ApiKeyTokenInfo(BaseModel):
    id: int
    public_id: str
    workspace_id: int
    scopes: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)


_API_KEY_SORT = Literal["created_at", "name", "last_used_at", "expires_at"]


class ApiKeyListQueryParams(pagination.PaginationSortQueryParams[_API_KEY_SORT]):
    """Query params for the workspace API-key list (GET /api-keys)."""

    per_page: int = Field(default=20, ge=-1, le=100)
    sort: _API_KEY_SORT = "created_at"
    order: pagination.SortOrder = pagination.SortOrder.DESC
    search: str | None = None
    workspace_id: int | None = None


@dataclass
class ApiKeyListParams(pagination.PaginationSortParams):
    per_page: int = 20
    search: str | None = None
    workspace_id: int | None = None


class ApiKeyStatusCounts(BaseModel):
    """Workspace-wide API-key status tallies (survive pagination for the metrics row)."""

    total: int
    active: int
    expired: int
    revoked: int


class ApiKeyListResponse(pagination.Paginated[ApiKeyRead]):
    """Paginated API-key page, status counts, and the grantable scope set.

    ``available_scopes`` is the caller's own authority in this workspace, not the
    whole catalog: the create form must not offer a scope the caller cannot
    delegate, and the server would refuse it anyway.
    """

    counts: ApiKeyStatusCounts
    available_scopes: list[str] = Field(default_factory=list)
