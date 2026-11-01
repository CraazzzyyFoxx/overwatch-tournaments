import typing
from datetime import datetime

from pydantic import BaseModel, Field

from shared.core.pagination import SortOrder
from shared.schemas.identity import PersonDisplayRead

__all__ = (
    "PlayerStatistics",
    "PlayerLeaderboardQueryParams",
    "PlayerLeaderboardRow",
    "StatPlayerRef",
    "StatRef",
    "StatMapRef",
    "StatRecordCode",
    "StatRecord",
    "StatRecords",
    "MapStat",
    "MapModeStats",
    "MapStatsResponse",
)


class PlayerStatistics(BaseModel):
    id: int
    name: str
    value: int | float


class PlayerLeaderboardQueryParams(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort: typing.Literal["titles", "tournaments", "maps_won", "winrate"] = "titles"
    order: SortOrder = SortOrder.DESC
    #: Case-insensitive substring of the player's name; it filters the page, never renumbers ``rank``.
    query: str = ""


class PlayerLeaderboardRow(BaseModel):
    #: Competition rank (1, 2, 2, 4) by the sort metric over the whole population.
    rank: int
    id: int
    #: How the page's game names the player (``display.canonical`` builds the profile link); every game's
    #: board carries the canonical name.
    display: PersonDisplayRead
    titles: int
    tournaments: int
    maps_won: int
    maps_lost: int
    #: ``maps_won / (maps_won + maps_lost)``; null without maps.
    winrate: float | None
    #: Three tournaments or fewer: below the win-rate board's threshold.
    low_sample: bool


class StatRef(BaseModel):
    id: int
    name: str


class StatPlayerRef(BaseModel):
    id: int
    #: How the record's game names the player; the cross-game read carries the canonical name.
    display: PersonDisplayRead


class StatMapRef(BaseModel):
    id: int
    name: str
    slug: str
    image_path: str | None


StatRecordCode = typing.Literal[
    "win_streak",
    "biggest_upset",
    "underdog_champion",
    "closest_final",
    "hero_damage",
    "healing",
    "eliminations",
    "damage_blocked",
    "solo_kills",
    "most_mvps",
    "longest_map",
]


class StatRecord(BaseModel):
    code: StatRecordCode
    value: float
    player: StatPlayerRef | None = None
    team: StatRef | None = None
    opponent: StatRef | None = None
    tournament: StatRef | None = None
    encounter_id: int | None = None
    match_id: int | None = None
    map: StatMapRef | None = None
    #: Series score, ``team`` first.
    score: tuple[float, float] | None = None
    duration_s: float | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    relative: float | None = None
    of_total: int | None = None


class StatRecords(BaseModel):
    records: list[StatRecord]


class MapStat(BaseModel):
    map: StatMapRef
    games: int
    #: ``games`` over the mode's games.
    share: float
    avg_duration_s: float | None


class MapModeStats(BaseModel):
    #: The mode the games were played in (the game's/match's own); null for games without one.
    mode: StatMapRef | None
    games: int
    maps: list[MapStat]


class MapStatsResponse(BaseModel):
    total_games: int
    modes: list[MapModeStats]
