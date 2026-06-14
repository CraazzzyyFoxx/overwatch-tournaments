from datetime import datetime

from src.core import enums
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.stage import StageRead

__all__ = ("TournamentRead", "TournamentGroupRead")


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

    stages: list[StageRead] = []
    division_grid_version_id: int | None
    division_grid_version: DivisionGridVersionRead | None = None
