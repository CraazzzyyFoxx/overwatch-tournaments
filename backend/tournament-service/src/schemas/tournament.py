import typing
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from src.core import enums, pagination
from src.schemas import UserRead
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.stage import StageSummaryRead

__all__ = (
    "TournamentRead",
    "TournamentGroupRead",
    "OwalStanding",
    "OwalStandingDay",
    "OwalStandings",
    "TournamentPaginationSortSearchQueryParams",
    "TournamentPaginationSortSearchParams",
    "LeaguePlayerStack",
)


class TournamentGroupRead(BaseRead):
    name: str
    description: str | None
    is_groups: bool
    challonge_id: int | None
    challonge_slug: str | None


class TournamentRead(BaseRead):
    workspace_id: int
    number: int | None
    name: str
    description: str | None
    challonge_id: int | None
    challonge_slug: str | None
    is_league: bool
    is_finished: bool
    is_hidden: bool = False
    team_formation: str = "balancer"
    status: enums.TournamentStatus
    start_date: datetime
    end_date: datetime
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    check_in_opens_at: datetime | None = None
    check_in_closes_at: datetime | None = None
    win_points: float = 1.0
    draw_points: float = 0.5
    loss_points: float = 0.0

    stages: list[StageSummaryRead] = []
    participants_count: int | None
    registrations_count: int | None = None
    teams_count: int | None = None
    division_grid_version_id: int | None
    division_grid_version: DivisionGridVersionRead | None = None


class OwalStandingDay(BaseModel):
    team: str
    role: enums.HeroClass
    division: int
    points: float
    wins: int
    draws: int
    losses: int
    win_rate: float


class OwalStanding(BaseModel):
    user: UserRead
    role: enums.HeroClass
    division: int
    days: dict[int, OwalStandingDay]
    count_days: int
    place: int
    best_3_days: float
    avg_points: float
    wins: int
    draws: int
    losses: int
    win_rate: float


class OwalStandings(BaseModel):
    days: list[TournamentRead]
    standings: list[OwalStanding]


class TournamentPaginationSortSearchQueryParams(
    pagination.PaginationSortSearchQueryParams[
        typing.Literal["id", "name", "number", "start_date", "end_date", "similarity:name"]
    ]
):
    is_league: bool | None = None
    workspace_id: int | None = None


@dataclass
class TournamentPaginationSortSearchParams(pagination.PaginationSortSearchParams):
    is_league: bool | None = None
    workspace_id: int | None = None


class LeaguePlayerStack(BaseModel):
    user_1: UserRead
    user_2: UserRead
    games: int
    avg_position: float
