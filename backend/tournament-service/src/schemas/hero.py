import typing
from dataclasses import dataclass

from pydantic import BaseModel

from src.core import enums, pagination
from src.schemas import BaseRead

__all__ = (
    "OverfastHero",
    "HeroRead",
    "HeroPlaytime",
    "HeroPlaytimeQueryPaginationParams",
    "HeroPlaytimePaginationParams",
    "HeroStatsPaginationParams",
    "HeroStatsQueryPaginationParams",
    "HeroLeaderboardEntry",
    "HeroLeaderboardQueryParams",
    "HeroLeaderboardParams",
)


class OverfastHero(BaseModel):
    key: str
    name: str
    portrait: str
    role: str


class HeroRead(BaseRead):
    slug: str
    name: str
    image_path: str
    type: str
    color: str


class HeroPlaytime(BaseModel):
    hero: HeroRead
    playtime: float


class HeroPlaytimeQueryPaginationParams(pagination.PaginationSortQueryParams):
    user_id: int | typing.Literal["all"] = "all"
    sort: typing.Literal["id", "name", "slug", "playtime"] = "playtime"
    tournament_id: int | None = None


@dataclass
class HeroPlaytimePaginationParams(pagination.PaginationSortParams):
    user_id: int | typing.Literal["all"] = "all"
    # role: enums.HeroRole | typing.Literal["all"] = "all"
    tournament_id: int | None = None


class HeroStatsQueryPaginationParams(pagination.PaginationSortQueryParams):
    user_id: int | typing.Literal["all"] = "all"
    group_by: typing.Literal["overall", "match"] = "overall"
    stat: enums.LogStatsName = enums.LogStatsName.KDA


@dataclass
class HeroStatsPaginationParams(pagination.PaginationSortParams):
    user_id: int | typing.Literal["all"] = "all"
    group_by: typing.Literal["overall", "match"] = "overall"
    stat: enums.LogStatsName = enums.LogStatsName.HeroTimePlayed


class HeroLeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    username: str
    player_name: str
    role: enums.HeroClass | None
    div: int
    games_played: int
    playtime_seconds: float
    per10_eliminations: float
    per10_healing: float
    per10_deaths: float
    per10_damage: float
    per10_final_blows: float
    per10_damage_blocked: float
    per10_solo_kills: float
    per10_obj_kills: float
    per10_defensive_assists: float
    per10_offensive_assists: float
    per10_all_damage: float
    per10_damage_taken: float
    per10_self_healing: float
    per10_ultimates_used: float
    per10_multikills: float
    per10_env_kills: float
    per10_crit_hits: float
    avg_weapon_accuracy: float
    avg_crit_accuracy: float
    kd: float
    kda: float


class HeroLeaderboardQueryParams(pagination.PaginationQueryParams):
    tournament_id: int | None = None
    stat: enums.LogStatsName = enums.LogStatsName.Eliminations


@dataclass
class HeroLeaderboardParams(pagination.PaginationParams):
    tournament_id: int | None = None
    stat: enums.LogStatsName = enums.LogStatsName.Performance

    @classmethod
    def from_query_params(cls, query_params: HeroLeaderboardQueryParams) -> "HeroLeaderboardParams":  # type: ignore[override]
        return cls(
            page=query_params.page,
            per_page=query_params.per_page,
            entities=query_params.entities,
            tournament_id=query_params.tournament_id,
            stat=query_params.stat,
        )
