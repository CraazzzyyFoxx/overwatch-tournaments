from pydantic import BaseModel

from shared.schemas import catalog
from shared.schemas.catalog import (
    HeroLeaderboardEntry,
    HeroLeaderboardParams,
    HeroLeaderboardQueryParams,
    HeroPlaytimePaginationParams,
    HeroPlaytimeQueryPaginationParams,
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


class HeroRead(catalog.HeroRead):
    # ponytail: aliases ride along in the public GET /api/v1/heroes too (~600
    # extra lines on an endpoint cached for a day). Separate *AdminRead schemas
    # when that payload becomes noticeable; today that is a 4th parameter to
    # `_register_entity` for no present benefit.
    aliases: list[str] = []


class HeroPlaytime(catalog.HeroPlaytime):
    # Narrowed from the shared model so the nested hero carries ``aliases`` too.
    hero: HeroRead
