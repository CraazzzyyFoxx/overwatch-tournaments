import typing
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.core import pagination

__all__ = (
    "GamemodeCreate",
    "GamemodeUpdate",
    "GamemodeListQueryParams",
    "GamemodeListParams",
)


class GamemodeCreate(BaseModel):
    """Schema for creating a gamemode"""

    name: str


class GamemodeUpdate(BaseModel):
    """Schema for updating a gamemode"""

    name: str | None = None


class GamemodeListQueryParams(
    pagination.PaginationSortQueryParams[typing.Literal["id", "name", "created_at", "updated_at"]]
):
    per_page: int = Field(default=50, ge=-1, le=500)
    sort: typing.Literal["id", "name", "created_at", "updated_at"] = "id"
    search: str | None = None


@dataclass
class GamemodeListParams(pagination.PaginationSortParams):
    per_page: int = 50
    search: str | None = None
