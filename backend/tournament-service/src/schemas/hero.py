from pydantic import BaseModel

from shared.schemas.catalog import (
    HeroLeaderboardEntry,
    HeroLeaderboardParams,
    HeroLeaderboardQueryParams,
    HeroPlaytime,
    HeroPlaytimePaginationParams,
    HeroPlaytimeQueryPaginationParams,
    HeroRead,
)

__all__ = (
    "OverfastHero",
    "HeroRead",
    "HeroPlaytime",
    "HeroPlaytimeQueryPaginationParams",
    "HeroPlaytimePaginationParams",
    "HeroLeaderboardEntry",
    "HeroLeaderboardQueryParams",
    "HeroLeaderboardParams",
)


class OverfastHero(BaseModel):
    key: str
    name: str
    portrait: str
    role: str
