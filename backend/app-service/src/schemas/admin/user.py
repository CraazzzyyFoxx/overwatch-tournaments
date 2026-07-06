import typing
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.core import pagination

__all__ = (
    "UserCreate",
    "UserUpdate",
    "SocialAccountCreate",
    "SocialAccountUpdate",
    "SocialVisibilityUpdate",
    "UserListQueryParams",
    "UserListParams",
)


class UserCreate(BaseModel):
    """Schema for creating a user"""

    name: str


class UserUpdate(BaseModel):
    """Schema for updating a user"""

    name: str | None = None


class UserListQueryParams(
    pagination.PaginationSortQueryParams[typing.Literal["id", "name", "created_at", "updated_at"]]
):
    per_page: int = Field(default=50, ge=-1, le=500)
    sort: typing.Literal["id", "name", "created_at", "updated_at"] = "id"
    search: str | None = None


@dataclass
class UserListParams(pagination.PaginationSortParams):
    per_page: int = 50
    search: str | None = None


# ─── Social account (unified identity) ───────────────────────────────────────


class SocialAccountCreate(BaseModel):
    """Add a social identity to a user. ``username`` is the full handle
    (battletag ``Name#1234``, discord name, twitch login, etc.)."""

    provider: str
    username: str
    url: str | None = None


class SocialAccountUpdate(BaseModel):
    """Update a social identity's display handle and/or url."""

    username: str | None = None
    url: str | None = None


class SocialVisibilityUpdate(BaseModel):
    """Toggle visibility of an account in a scope (``workspace_id`` None = global)."""

    workspace_id: int | None = None
    visible: bool = True
