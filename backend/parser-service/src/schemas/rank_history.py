from datetime import datetime

from pydantic import BaseModel

__all__ = (
    "RankHistoryPoint",
    "RankSeries",
    "RankHistoryResponse",
    "CurrentRank",
    "CurrentRanksResponse",
)


class RankHistoryPoint(BaseModel):
    captured_at: datetime
    rank_value: int | None
    division: str | None
    tier: int | None
    is_ranked: bool
    season: int | None


class RankSeries(BaseModel):
    """One time series for a (battle_tag, role, platform) tuple.

    The frontend pivots a list of these into either grouping: fix a battle tag
    and draw a line per role, or fix a role and draw a line per battle tag.
    """

    battle_tag_id: int
    battle_tag: str
    role: str
    platform: str
    points: list[RankHistoryPoint]
    current: RankHistoryPoint | None
    peak_rank_value: int | None
    latest_captured_at: datetime | None


class RankHistoryResponse(BaseModel):
    user_id: int | None
    series: list[RankSeries]
    generated_at: datetime


class CurrentRank(BaseModel):
    battle_tag_id: int
    battle_tag: str
    role: str
    platform: str
    rank_value: int | None
    division: str | None
    tier: int | None
    is_ranked: bool
    season: int | None
    captured_at: datetime


class CurrentRanksResponse(BaseModel):
    user_id: int | None
    ranks: list[CurrentRank]
    generated_at: datetime
