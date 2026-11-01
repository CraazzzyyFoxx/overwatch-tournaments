from dataclasses import dataclass

from pydantic import UUID4, BaseModel, Field

from shared.core import pagination
from shared.schemas.discipline_filter import InstalledDisciplineFilter
from shared.schemas.identity import PersonDisplayRead
from shared.schemas.role import RoleRef
from src.schemas import BaseRead
from src.schemas.tournament import TournamentRead
from src.schemas.user_base import UserRead

__all__ = (
    "BalancerTeamMember",
    "BalancerTeam",
    "TeamRead",
    "PlayerRead",
    "TeamGroupRead",
    "TeamFilterQueryParams",
    "TeamFilterParams",
)


class BalancerTeamMember(BaseModel):
    uuid: UUID4
    name: str
    sub_role: str | None = None
    role: RoleRef | None
    rank: int | None = None


class BalancerTeam(BaseModel):
    uuid: UUID4
    avg_sr: float = Field(alias="avgSr")
    name: str
    total_sr: int = Field(alias="totalSr")
    members: list[BalancerTeamMember]


class PlayerRead(BaseRead):
    name: str
    #: The name this game's surfaces show (``name`` is the roster snapshot). ``canonical`` builds the profile link.
    display: PersonDisplayRead
    #: ``None`` = rank not specified (e.g. a 1v1 duel); then there is no division either.
    rank: int | None
    division: int | None
    role: RoleRef | None = None
    tournament_id: int
    user_id: int
    team_id: int
    is_newcomer: bool
    is_newcomer_role: bool
    is_substitution: bool
    related_player_id: int | None

    tournament: TournamentRead | None
    team: TeamRead | None
    user: UserRead | None


class TeamGroupRead(BaseModel):
    """The group a team played in: a ``StageItem`` of type GROUP, name only."""

    id: int
    name: str


class TeamRead(BaseRead):
    name: str
    image_url: str | None = None
    avg_sr: float
    total_sr: int
    tournament_id: int
    captain_id: int | None
    tournament: TournamentRead | None
    players: list[PlayerRead]
    captain: UserRead | None
    placement: int | None
    group: TeamGroupRead | None


class TeamFilterQueryParams(pagination.PaginationSortQueryParams):
    tournament_id: int | None = None
    search: str | None = None
    #: Teams of one installed game's tournaments; absent is every game (spec §8.1).
    discipline: InstalledDisciplineFilter = None


@dataclass
class TeamFilterParams(pagination.PaginationSortParams):
    tournament_id: int | None = None
    search: str | None = None
    discipline: str | None = None


# PlayerRead.team forward-references TeamRead, defined below it. Pydantic leaves
# such a serializer as a MockValSer placeholder whose lazy rebuild fails ("'MockValSer'
# object cannot be converted to 'SchemaSerializer'") when the first use is a
# model_dump() of a cached/nested value; rebuilding at import time avoids that.
PlayerRead.model_rebuild()
TeamRead.model_rebuild()
