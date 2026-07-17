from datetime import date, datetime

from pydantic import BaseModel, model_validator

from shared.core import tournament_state
from shared.core.enums import TournamentStatus

__all__ = (
    "TournamentCreate",
    "TournamentUpdate",
    "TournamentStatusTransition",
    "TournamentScheduleEntryInput",
    "TournamentScheduleSet",
)


class TournamentCreate(BaseModel):
    """Schema for creating a tournament"""

    workspace_id: int
    number: int | None = None
    name: str
    description: str | None = None
    is_league: bool = False
    is_hidden: bool = False
    team_formation: str = "balancer"
    status: TournamentStatus = TournamentStatus.REGISTRATION
    start_date: date
    end_date: date
    auto_transitions_enabled: bool = True
    allow_late_registration: bool = False
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
    is_hidden: bool | None = None
    team_formation: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    auto_transitions_enabled: bool | None = None
    allow_late_registration: bool | None = None
    win_points: float | None = None
    draw_points: float | None = None
    loss_points: float | None = None
    division_grid_version_id: int | None = None


class TournamentStatusTransition(BaseModel):
    """Schema for transitioning tournament status"""

    status: TournamentStatus
    force: bool = False


class TournamentScheduleEntryInput(BaseModel):
    """One phase-schedule row in a full-replace schedule update."""

    status: TournamentStatus
    starts_at: datetime
    ends_at: datetime | None = None


class TournamentScheduleSet(BaseModel):
    """Schema for replacing a tournament's phase schedule (full replace)."""

    schedule: list[TournamentScheduleEntryInput]

    @model_validator(mode="after")
    def _validate_schedule(self) -> "TournamentScheduleSet":
        seen: set[TournamentStatus] = set()
        previous: TournamentScheduleEntryInput | None = None
        for entry in sorted(self.schedule, key=lambda item: tournament_state.PHASE_ORDER[item.status]):
            if entry.status not in tournament_state.SCHEDULABLE_STATUSES:
                raise ValueError(f"Phase '{entry.status.value}' cannot be scheduled")
            if entry.status in seen:
                raise ValueError(f"Duplicate schedule entry for phase '{entry.status.value}'")
            seen.add(entry.status)
            if entry.ends_at is not None and entry.ends_at <= entry.starts_at:
                raise ValueError(f"Phase '{entry.status.value}' must end after it starts")
            if previous is not None and entry.starts_at <= previous.starts_at:
                raise ValueError(
                    f"Phase '{entry.status.value}' must start after phase '{previous.status.value}'"
                )
            previous = entry
        return self
