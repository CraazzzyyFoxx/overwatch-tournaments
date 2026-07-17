from datetime import datetime

from pydantic import BaseModel

from src.core import enums
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.stage import StageRead

__all__ = ("TournamentRead", "TournamentGroupRead", "TournamentPhaseScheduleRead")


class TournamentGroupRead(BaseRead):
    name: str
    description: str | None
    is_groups: bool
    challonge_id: int | None
    challonge_slug: str | None


class TournamentPhaseScheduleRead(BaseModel):
    """One phase-schedule row: when phase ``status`` starts (and its action window ends)."""

    status: enums.TournamentStatus
    starts_at: datetime
    ends_at: datetime | None = None


class TournamentRead(BaseRead):
    workspace_id: int
    number: int | None
    name: str
    description: str | None
    challonge_id: int | None
    challonge_slug: str | None
    is_league: bool
    is_finished: bool
    status: enums.TournamentStatus
    start_date: datetime
    end_date: datetime
    auto_transitions_enabled: bool = True
    allow_late_registration: bool = False
    phase_schedule: list[TournamentPhaseScheduleRead] = []
    win_points: float = 1.0
    draw_points: float = 0.5
    loss_points: float = 0.0

    stages: list[StageRead] = []
    division_grid_version_id: int | None
    division_grid_version: DivisionGridVersionRead | None = None
