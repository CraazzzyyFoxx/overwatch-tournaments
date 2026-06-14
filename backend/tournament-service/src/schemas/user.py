import typing
from dataclasses import dataclass, field

import sqlalchemy as sa
from pydantic import BaseModel, Field

from src import schemas
from src.core import enums, pagination
from src.schemas.division_grid import DivisionGridVersionRead

__all__ = (
    "UserProfile",
    "UserRole",
    "UserTournamentWithStats",
    "UserTournament",
    "MatchReadWithUserStats",
    "EncounterReadWithUserStats",
    "UserMap",
    "UserMapHeroStats",
    "UserMapHighlight",
    "UserMapsOverall",
    "UserMapsSummary",
    "UserMapsSearchParams",
    "UserMapsSearchQueryParams",
    "UserTournamentStat",
    "HeroStat",
    "HeroWithUserStats",
    "HeroStatBest",
    "UserBestTeammate",
    "UserSearch",
    "UserOverviewRoleDivision",
    "UserOverviewHeroMetric",
    "UserOverviewHero",
    "UserOverviewAverages",
    "UserOverviewRow",
    "UserOverviewQueryParams",
    "UserOverviewParams",
    "UserCompareQueryParams",
    "UserCompareParams",
    "UserCompareBaselineMode",
    "UserCompareUser",
    "UserCompareBaselineInfo",
    "UserCompareMetric",
    "UserCompareResponse",
    "UserHeroCompareQueryParams",
    "UserHeroCompareParams",
    "UserHeroCompareMetric",
    "UserHeroCompareResponse",
)

from src.schemas import MapRead


class UserRole(BaseModel):
    role: enums.HeroClass
    tournaments: int
    maps_won: int
    maps: int
    division: int
    division_grid_version: DivisionGridVersionRead | None = None


class MatchReadWithUserStats(schemas.MatchRead):
    performance: int | None
    heroes: list[schemas.HeroRead]


class EncounterReadWithUserStats(schemas.EncounterRead):
    matches: list[MatchReadWithUserStats]


class UserTournament(BaseModel):
    id: int
    number: int | None
    name: str
    is_league: bool
    team_id: int
    team: str
    players: list["schemas.PlayerRead"]
    closeness: float
    placement: int | None
    count_teams: int
    won: int
    lost: int
    draw: int
    maps_won: int
    maps_lost: int
    role: enums.HeroClass
    division: int
    division_grid_version: DivisionGridVersionRead | None = None
    encounters: list[EncounterReadWithUserStats]


class UserTournamentStat(BaseModel):
    value: float
    rank: int
    total: int


class UserTournamentWithStats(BaseModel):
    id: int
    number: int | None
    name: str
    division: int
    closeness: float
    role: enums.HeroClass
    group_placement: float | None
    playoff_placement: float | None
    maps_won: int
    maps: int
    playtime: float

    stats: dict[enums.LogStatsName | typing.Literal["winrate"], UserTournamentStat]


class UserMapHeroStats(BaseModel):
    hero: schemas.HeroRead
    games: int
    win: int
    loss: int
    draw: int
    win_rate: float
    playtime_seconds: float
    playtime_share_on_map: float


class UserMap(BaseModel):
    map: MapRead
    count: int
    win: int
    loss: int
    draw: int
    win_rate: float
    heroes: list[schemas.HeroPlaytime]
    hero_stats: list[UserMapHeroStats] | None = None


class UserMapHighlight(BaseModel):
    map: MapRead
    count: int
    win: int
    loss: int
    draw: int
    win_rate: float


class UserMapsOverall(BaseModel):
    total_maps: int
    total_games: int
    win: int
    loss: int
    draw: int
    win_rate: float


class UserMapsSummary(BaseModel):
    overall: UserMapsOverall
    most_played: UserMapHighlight | None
    best: UserMapHighlight | None
    worst: UserMapHighlight | None


class UserMapsSearchQueryParams(pagination.PaginationSortSearchQueryParams):
    min_count: int | None = Field(default=None, ge=1)
    gamemode_id: int | None = None
    tournament_id: int | None = None


@dataclass
class UserMapsSearchParams(pagination.PaginationSortSearchParams):
    min_count: int | None = None
    gamemode_id: int | None = None
    tournament_id: int | None = None

    def apply_search(self, query: sa.Select, model: type) -> sa.Select:
        fields = self.fields if self.fields else ["name"]
        return pagination.apply_search(model, query, self.query, fields)


class UserProfile(BaseModel):
    tournaments_count: int
    tournaments_won: int
    maps_total: int
    maps_won: int
    avg_closeness: float | None
    avg_placement: float | None
    avg_playoff_placement: float | None
    avg_group_placement: float | None
    most_played_hero: schemas.HeroRead | None

    roles: list[UserRole]
    tournaments: list[schemas.TournamentRead]
    hero_statistics: list[schemas.HeroPlaytime]


class HeroStatBest(BaseModel):
    encounter_id: int
    tournament_name: str
    map_name: str
    map_image_path: str
    value: float
    player_name: str


class HeroStat(BaseModel):
    name: enums.LogStatsName
    overall: float
    best: HeroStatBest
    avg_10: float
    best_all: HeroStatBest | None
    avg_10_all: float


class HeroWithUserStats(BaseModel):
    hero: schemas.HeroRead
    stats: list[HeroStat]


class UserBestTeammate(BaseModel):
    user: schemas.UserRead
    tournaments: int
    winrate: float
    stats: dict[enums.LogStatsName, float | None]


class UserSearch(BaseModel):
    id: int
    name: str


class UserOverviewRoleDivision(BaseModel):
    role: enums.HeroClass
    division: int


class UserOverviewHeroMetric(BaseModel):
    name: enums.LogStatsName
    avg_10: float


class UserOverviewHero(BaseModel):
    hero: schemas.HeroRead
    playtime_seconds: float
    metrics: list[UserOverviewHeroMetric]


class UserOverviewAverages(BaseModel):
    avg_closeness: float | None
    avg_placement: float | None
    avg_playoff_placement: float | None
    avg_group_placement: float | None


class UserOverviewRow(BaseModel):
    id: int
    name: str
    roles: list[UserOverviewRoleDivision]
    top_heroes: list[UserOverviewHero]
    tournaments_count: int
    achievements_count: int
    averages: UserOverviewAverages


class UserOverviewQueryParams(
    pagination.PaginationSortSearchQueryParams[
        typing.Literal[
            "id",
            "name",
            "tournaments_count",
            "achievements_count",
            "avg_placement",
        ]
    ]
):
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)


@dataclass
class UserOverviewParams(pagination.PaginationSortSearchParams):
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None

    def apply_search(self, query: sa.Select, model: type) -> sa.Select:
        fields = self.fields if self.fields else ["name"]
        return pagination.apply_search(model, query, self.query, fields)


UserCompareBaselineMode = typing.Literal["target_user", "global", "cohort"]


class UserCompareUser(BaseModel):
    id: int
    name: str


class UserCompareBaselineInfo(BaseModel):
    mode: UserCompareBaselineMode
    sample_size: int
    target_user: UserCompareUser | None
    role: enums.HeroClass | None
    div_min: int | None
    div_max: int | None


class UserCompareMetric(BaseModel):
    key: str
    label: str
    subject_value: float | int | None
    baseline_value: float | int | None
    delta: float | None
    delta_percent: float | None
    better_worse: typing.Literal["better", "worse", "equal"] | None
    higher_is_better: bool
    subject_rank: int | None
    subject_percentile: float | None


class UserCompareResponse(BaseModel):
    subject: UserCompareUser
    baseline: UserCompareBaselineInfo
    metrics: list[UserCompareMetric]


class UserCompareQueryParams(BaseModel):
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = Field(default=None, ge=1)
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)
    tournament_id: int | None = Field(default=None, ge=1)


@dataclass
class UserCompareParams:
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = None
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None
    tournament_id: int | None = None

    @classmethod
    def from_query_params(cls, query_params: UserCompareQueryParams):
        return cls(**query_params.model_dump())


class UserHeroCompareMetric(BaseModel):
    stat: enums.LogStatsName
    left_value: float
    right_value: float
    delta: float
    delta_percent: float | None
    better_worse: typing.Literal["better", "worse", "equal"] | None
    higher_is_better: bool


class UserHeroCompareResponse(BaseModel):
    subject: UserCompareUser
    target: UserCompareUser | None
    baseline: UserCompareBaselineInfo
    subject_hero: schemas.HeroRead | None
    target_hero: schemas.HeroRead | None
    map: schemas.MapRead | None
    left_playtime_seconds: float
    right_playtime_seconds: float
    metrics: list[UserHeroCompareMetric]


class UserHeroCompareQueryParams(BaseModel):
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = Field(default=None, ge=1)
    left_hero_id: int | None = Field(default=None, ge=1)
    right_hero_id: int | None = Field(default=None, ge=1)
    map_id: int | None = Field(default=None, ge=1)
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)
    tournament_id: int | None = Field(default=None, ge=1)
    stats: list[enums.LogStatsName] | None = None


@dataclass
class UserHeroCompareParams:
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = None
    left_hero_id: int | None = None
    right_hero_id: int | None = None
    map_id: int | None = None
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None
    tournament_id: int | None = None
    stats: list[enums.LogStatsName] = field(default_factory=list)

    @classmethod
    def from_query_params(cls, query_params: UserHeroCompareQueryParams):
        payload = query_params.model_dump()
        payload["stats"] = payload.get("stats") or []
        return cls(**payload)
