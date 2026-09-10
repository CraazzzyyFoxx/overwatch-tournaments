"""Catalog read models shared by app-service, parser-service, and tournament-service.

``HeroRead``/``MapRead``/``GamemodeRead`` and the hero playtime/stats/leaderboard
parameter shapes used to be copy-pasted into each of those three services'
``schemas`` packages -- 121 identical lines, including a 44-field
``HeroLeaderboardEntry``. They carry no per-service behavior, so there is exactly
one definition here and each service's local module re-exports what it needs.
Same consolidation as ``shared/schemas/base.py``; see its docstring.

Deliberate omission: ``aliases``. Only app-service serves it (the admin catalog
editor), and ``MapRead`` is embedded in ``EncounterRead.map`` in both
parser-service and tournament-service, so declaring ``aliases`` here would widen
two unrelated public payloads. app-service subclasses these three models to add
it.

No ``model_config`` here on purpose: callers that read ORM objects pass
``from_attributes=True`` to ``model_validate`` themselves.
"""

import typing
from dataclasses import dataclass

from pydantic import BaseModel

from shared.core import enums, pagination
from shared.schemas.base import BaseRead

__all__ = (
    "GamemodeRead",
    "HeroLeaderboardEntry",
    "HeroLeaderboardParams",
    "HeroLeaderboardQueryParams",
    "HeroPlaytime",
    "HeroPlaytimePaginationParams",
    "HeroPlaytimeQueryPaginationParams",
    "HeroRead",
    "MapRead",
)


class GamemodeRead(BaseRead):
    slug: str
    name: str
    image_path: str
    description: str | None


class HeroRead(BaseRead):
    slug: str
    name: str
    image_path: str
    type: str
    color: str


class MapRead(BaseRead):
    gamemode_id: int
    name: str
    image_path: str
    in_competitive: bool = True

    gamemode: GamemodeRead | None


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


class HeroLeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    username: str
    player_name: str
    role: enums.HeroClass | None
    div: int
    team: str | None = None
    team_id: int | None = None
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
    def from_query_params(cls, query_params: HeroLeaderboardQueryParams) -> HeroLeaderboardParams:  # type: ignore[override]
        return cls(
            page=query_params.page,
            per_page=query_params.per_page,
            entities=query_params.entities,
            tournament_id=query_params.tournament_id,
            stat=query_params.stat,
        )
