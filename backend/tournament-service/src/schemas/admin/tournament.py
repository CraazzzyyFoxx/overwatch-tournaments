from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from shared.core import tournament_state
from shared.core.enums import TournamentStatus
from shared.schemas.draft_format import DraftFormatField

__all__ = (
    "TournamentCreate",
    "TournamentUpdate",
    "TournamentStatusTransition",
    "TournamentScheduleEntryInput",
    "TournamentScheduleSet",
)

#: Upper bound on the published regulations. Not a storage limit (the column is
#: ``Text``) but a trust boundary: the document rides in the public tournament
#: read that every section of the page shell already fetches, so an unbounded
#: field would let one organizer inflate every request for their tournament.
#: ~32k characters is several pages of rules.
RULES_MAX_LENGTH = 32_000


class TournamentCreate(BaseModel):
    workspace_id: int
    #: The game the tournament is played in; always the caller's explicit choice (enabled in the workspace).
    discipline: str
    name: str
    # Public-URL slug. Slugified and uniqueness-checked server-side; left
    # blank, one is generated from `name` (see shared.services.tournament.slug).
    slug: str | None = None
    description: str | None = None
    is_league: bool = False
    is_hidden: bool = False
    team_formation: str = "balancer"
    status: TournamentStatus = TournamentStatus.ANNOUNCEMENT
    start_date: date
    end_date: date
    auto_transitions_enabled: bool = True
    allow_late_registration: bool = False
    # Owner policy for canonical match ingest; false unless the authorized organizer sets it.
    logs_official: bool = False
    win_points: float = 1.0
    draw_points: float = 0.5
    loss_points: float = 0.0
    division_grid_version_id: int | None = None
    # None = the snake default. Normalized by DraftFormatField, so the column
    # never stores round rules a non-custom format would ignore.
    draft_format_json: DraftFormatField = None


class TournamentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rules: str | None = Field(default=None, max_length=RULES_MAX_LENGTH)
    challonge_slug: str | None = None
    # Explicit rename of the public-URL slug (frozen otherwise). Slugified
    # server-side; the retired value keeps resolving via a slug_redirect row.
    slug: str | None = None
    is_league: bool | None = None
    is_finished: bool | None = None
    is_hidden: bool | None = None
    team_formation: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    auto_transitions_enabled: bool | None = None
    allow_late_registration: bool | None = None
    discord_broadcasts_enabled: bool | None = None
    discord_dms_enabled: bool | None = None
    logs_official: bool | None = None
    # 900 is Twitch's maximum broadcast delay; the column carries the same CHECK.
    pov_stream_delay_s: int | None = Field(default=None, ge=0, le=900)
    win_points: float | None = None
    draw_points: float | None = None
    loss_points: float | None = None
    division_grid_version_id: int | None = None
    draft_format_json: DraftFormatField = None


class TournamentStatusTransition(BaseModel):
    status: TournamentStatus
    force: bool = False


class TournamentScheduleEntryInput(BaseModel):
    """One phase-schedule row in a full-replace schedule update."""

    status: TournamentStatus
    starts_at: datetime
    ends_at: datetime | None = None


class TournamentScheduleSet(BaseModel):
    """A tournament's whole phase schedule; replaces the stored one."""

    schedule: list[TournamentScheduleEntryInput]

    @model_validator(mode="after")
    def _validate_schedule(self) -> TournamentScheduleSet:
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
                raise ValueError(f"Phase '{entry.status.value}' must start after phase '{previous.status.value}'")
            previous = entry
        return self
