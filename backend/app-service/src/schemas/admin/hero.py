import typing
from dataclasses import dataclass

from pydantic import BaseModel, Field
from shared.core import enums

from src.core import pagination

__all__ = (
    "HeroCreate",
    "HeroUpdate",
    "HeroListQueryParams",
    "HeroListParams",
)


class HeroCreate(BaseModel):
    """Schema for creating a hero"""

    name: str
    role: enums.HeroClass
    color: str | None = None
    image_path: str | None = None


class HeroUpdate(BaseModel):
    """Schema for updating a hero"""

    name: str | None = None
    role: enums.HeroClass | None = None
    color: str | None = None
    image_path: str | None = None


class HeroListQueryParams(
    pagination.PaginationSortQueryParams[typing.Literal["id", "name", "role", "created_at", "updated_at"]]
):
    per_page: int = Field(default=50, ge=-1, le=500)
    sort: typing.Literal["id", "name", "role", "created_at", "updated_at"] = "id"
    search: str | None = None
    role: enums.HeroClass | None = None


@dataclass
class HeroListParams(pagination.PaginationSortParams):
    per_page: int = 50
    search: str | None = None
    role: enums.HeroClass | None = None
