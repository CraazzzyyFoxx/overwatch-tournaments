from datetime import date, datetime
from pydantic import BaseModel

from shared.core.enums import TournamentStatus

__all__ = (
    "TournamentCreate",
    "TournamentUpdate",
    "TournamentStatusTransition",
)


class TournamentCreate(BaseModel):
    """Schema for creating a tournament"""

    workspace_id: int
    number: int | None = None
    name: str
    description: str | None = None
    is_league: bool = False
    status: TournamentStatus = TournamentStatus.DRAFT
    start_date: date
    end_date: date
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    check_in_opens_at: datetime | None = None
    check_in_closes_at: datetime | None = None
    win_points: float = 1.0
    draw_points: float = 0.5
    loss_points: float = 0.0
    division_grid_version_id: int | None = None


class TournamentUpdate(BaseModel):
    """Schema for updating a tournament"""

    number: int | None = None
    name: str | None = None
    description: str | None = None
    challonge_slug: str | None = None
    is_league: bool | None = None
    is_finished: bool | None = None
    start_date: date | None = None
    end_date: date | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    check_in_opens_at: datetime | None = None
    check_in_closes_at: datetime | None = None
    win_points: float | None = None
    draw_points: float | None = None
    loss_points: float | None = None
    division_grid_version_id: int | None = None


class TournamentStatusTransition(BaseModel):
    """Schema for transitioning tournament status"""

    status: TournamentStatus
    force: bool = False
