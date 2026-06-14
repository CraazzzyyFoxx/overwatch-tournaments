from datetime import datetime

from pydantic import Field

from src.schemas.base import BaseRead


class DivisionGridTierRead(BaseRead):
    version_id: int
    slug: str
    number: int
    name: str
    sort_order: int
    rank_min: int
    rank_max: int | None
    icon_url: str


class DivisionGridVersionRead(BaseRead):
    grid_id: int
    version: int
    label: str
    status: str
    created_from_version_id: int | None
    published_at: datetime | None
    tiers: list[DivisionGridTierRead] = Field(default_factory=list)
