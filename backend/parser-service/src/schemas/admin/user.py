import typing
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.core import pagination

__all__ = (
    "UserCreate",
    "UserUpdate",
    "DiscordIdentityCreate",
    "DiscordIdentityUpdate",
    "BattleTagIdentityCreate",
    "BattleTagIdentityUpdate",
    "TwitchIdentityCreate",
    "TwitchIdentityUpdate",
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


# ─── Discord Identity ────────────────────────────────────────────────────────


class DiscordIdentityCreate(BaseModel):
    """Schema for creating a Discord identity"""

    name: str  # Discord username


class DiscordIdentityUpdate(BaseModel):
    """Schema for updating a Discord identity"""

    name: str


# ─── BattleTag Identity ──────────────────────────────────────────────────────


class BattleTagIdentityCreate(BaseModel):
    """Schema for creating a BattleTag identity"""

    battle_tag: str  # Full battle tag (e.g., "Player#1234")


class BattleTagIdentityUpdate(BaseModel):
    """Schema for updating a BattleTag identity"""

    battle_tag: str


# ─── Twitch Identity ─────────────────────────────────────────────────────────


class TwitchIdentityCreate(BaseModel):
    """Schema for creating a Twitch identity"""

    name: str  # Twitch username


class TwitchIdentityUpdate(BaseModel):
    """Schema for updating a Twitch identity"""

    name: str
