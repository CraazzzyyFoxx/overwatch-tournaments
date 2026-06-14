import typing
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.core import pagination

__all__ = (
    "MapCreate",
    "MapUpdate",
    "MapListQueryParams",
    "MapListParams",
)


class MapCreate(BaseModel):
    """Schema for creating a map"""

    name: str
    gamemode_id: int


class MapUpdate(BaseModel):
    """Schema for updating a map"""

    name: str | None = None
    gamemode_id: int | None = None


class MapListQueryParams(
    pagination.PaginationSortQueryParams[typing.Literal["id", "name", "gamemode_id", "created_at", "updated_at"]]
):
    per_page: int = Field(default=50, ge=-1, le=500)
    sort: typing.Literal["id", "name", "gamemode_id", "created_at", "updated_at"] = "id"
    search: str | None = None
    gamemode_id: int | None = None


@dataclass
class MapListParams(pagination.PaginationSortParams):
    per_page: int = 50
    search: str | None = None
    gamemode_id: int | None = None
