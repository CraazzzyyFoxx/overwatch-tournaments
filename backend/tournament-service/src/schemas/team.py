import typing
from dataclasses import dataclass

from pydantic import UUID4, BaseModel, Field

from src.core import enums, pagination
from src.schemas import BaseRead, HeroRead
from src.schemas.tournament import TournamentGroupRead, TournamentRead
from src.schemas.user_base import UserRead

__all__ = (
    "BalancerTeamMember",
    "BalancerTeam",
    "TeamRead",
    "PlayerRead",
    "ChallongeTeam",
    "TeamFilterQueryParams",
    "TeamFilterParams",
    "PlayerFilterQueryParams",
    "PlayerFilterParams",
    "PlayerWithMatchStats",
    "TeamWithMatchStats",
)


class BalancerTeamMember(BaseModel):
    uuid: UUID4
    name: str
    sub_role: str | None = None
    role: typing.Literal["tank", "dps", "support"]
    rank: int


class BalancerTeam(BaseModel):
    uuid: UUID4
    avg_sr: float = Field(alias="avgSr")
    name: str
    total_sr: int = Field(alias="totalSr")
    members: list[BalancerTeamMember]


class PlayerRead(BaseRead):
    name: str
    sub_role: str | None
    rank: int
    division: int
    role: str | None
    tournament_id: int
    user_id: int
    team_id: int
    is_newcomer: bool
    is_newcomer_role: bool
    is_substitution: bool
    related_player_id: int | None

    tournament: TournamentRead | None
    team: typing.Optional["TeamRead"]
    user: UserRead | None


class TeamRead(BaseRead):
    name: str
    avg_sr: float
    total_sr: int
    tournament_id: int
    captain_id: int | None
    tournament: TournamentRead | None
    players: list[PlayerRead]
    captain: UserRead | None
    placement: int | None
    group: TournamentGroupRead | None


class ChallongeTeam(BaseModel):
    challonge_id: int
    team_id: int
    group_id: int | None
    tournament_id: int

    team: TeamRead | None
    group: TournamentGroupRead | None
    tournament: TournamentRead | None


class TeamFilterQueryParams(pagination.PaginationSortQueryParams):
    tournament_id: int | None = None


@dataclass
class TeamFilterParams(pagination.PaginationSortParams):
    tournament_id: int | None = None


class PlayerFilterQueryParams(pagination.PaginationSortQueryParams):
    tournament_id: int | None = None
    team_id: int | None = None


@dataclass
class PlayerFilterParams(pagination.PaginationSortParams):
    tournament_id: int | None = None
    team_id: int | None = None


class PlayerWithMatchStats(PlayerRead):
    stats: dict[int, dict[enums.LogStatsName, float]]
    heroes: dict[int, list[HeroRead]]


class TeamWithMatchStats(TeamRead):
    players: list[PlayerWithMatchStats]
