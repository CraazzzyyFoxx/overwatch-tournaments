"""The organizer dashboard (``GET /api/v1/admin/dashboard``) of one workspace.

Every permission-gated group is ``None`` when the caller lacks its grant, never
zero: ``tournament.read`` gates structure (schedule, timeline, stages),
``team.read`` registrations/pool/balance/teams, ``match.read`` encounter-derived
counts, ``user.read`` identities and ``achievement.read`` achievement state.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .readiness import TournamentReadiness

__all__ = (
    "DashboardPhase",
    "DashboardScheduleEntry",
    "DashboardPlay",
    "DashboardWrapUp",
    "DashboardTournamentCard",
    "DashboardTimelineEvent",
    "DashboardIssueKey",
    "DashboardIssue",
    "DashboardBacklogRow",
    "DashboardBacklog",
    "AdminDashboard",
)

DashboardPhase = Literal["preparation", "live", "wrap_up"]


class DashboardScheduleEntry(BaseModel):
    node_id: int
    node_name: str
    phase: str  # open | check_in | start
    starts_at: datetime
    ends_at: datetime | None


class DashboardPlay(BaseModel):
    """``match.read``; the card's ``play`` is None without it."""

    encounters_total: int
    encounters_completed: int
    encounters_live: int
    # result_status none, scheduled_at < now, status != completed
    encounters_overdue: int
    encounters_pending_confirmation: int
    # auto-disputed report mismatches included
    encounters_disputed: int


class DashboardWrapUp(BaseModel):
    """Present only on a ``wrap_up`` card. ``done`` is computed on full data regardless of permissions."""

    done: bool
    results_open: int | None  # pending_confirmation + disputed (match.read)
    logs_used: bool | None  # (match.read)
    duel_encounters_total: int | None  # (match.read)
    duel_encounters_with_logs: int | None  # (match.read)
    # Latest evaluation run status; "none" = never ran; "not_configured" = no enabled rules (achievement.read)
    achievements_status: str | None
    standings_recalc_pending: bool | None  # (tournament.read)


class DashboardTournamentCard(BaseModel):
    id: int
    name: str
    discipline: str
    status: str
    phase: DashboardPhase
    is_hidden: bool
    # Organizer branding (public URLs), unmasked like the name; None when not uploaded
    logo_url: str | None
    cover_image_url: str | None
    team_formation: str
    start_date: datetime | None
    end_date: datetime | None
    # wrap_up only: COALESCE(end_date, latest encounter confirmed_at)
    finished_at: datetime | None
    schedule: list[DashboardScheduleEntry]  # [] without tournament.read
    # Earliest schedule starts_at/ends_at after now (None without tournament.read)
    next_deadline_at: datetime | None
    # The earliest ``open`` row's ends_at among the registration nodes that are open
    registration_closes_at: datetime | None
    registrations_last_24h: int | None  # team.read
    # A tournament- or stage-level Challonge source with a slug
    has_challonge_source: bool
    readiness: TournamentReadiness
    play: DashboardPlay | None
    wrap_up: DashboardWrapUp | None


class DashboardTimelineEvent(BaseModel):
    tournament_id: int
    tournament_name: str
    phase: str  # the schedule row's phase: open | check_in | start
    node_name: str
    edge: Literal["start", "end"]
    at: datetime
    # A start more than 10 minutes past whose node has not made the move
    overdue: bool


DashboardIssueKey = Literal[
    "results_disputed",
    "results_overdue",
    "results_pending_confirmation",
    "phase_overdue",
    "registrations_pending",
    "pool_need_fix",
    "ranks_missing",
    "balance_not_exported",
    "stage_slots_empty",
    "logs_missing",
    "achievements_pending",
    "standings_recalc_pending",
]


class DashboardIssue(BaseModel):
    key: DashboardIssueKey
    severity: Literal["critical", "warning", "info"]
    tournament_id: int
    tournament_name: str
    count: int | None  # None for boolean conditions


class DashboardBacklogRow(BaseModel):
    """One tournament without a card that has a visible non-zero issue."""

    tournament_id: int
    tournament_name: str
    discipline: str
    encounters_missing_logs: int | None  # match.read; duels only
    teams_without_players: int | None  # team.read
    stage_slots_empty: int | None  # tournament.read
    has_stages: bool | None  # tournament.read


class DashboardBacklog(BaseModel):
    rows: list[DashboardBacklogRow]  # newest tournament first, at most 20
    tournaments_total: int  # tournaments with a visible backlog issue (rows may be truncated)
    encounters_missing_logs: int | None
    teams_without_players: int | None
    tournaments_without_stages: int | None
    stage_slots_empty: int | None
    users_without_identities: int | None  # user.read; the workspace roster


class AdminDashboard(BaseModel):
    generated_at: datetime
    # live phase first; then next_deadline_at asc, nulls last; wrap_up last; tie -> id desc
    tournaments: list[DashboardTournamentCard]
    # None without tournament.read; [now, now + 7d] plus every overdue start; sorted by at
    timeline: list[DashboardTimelineEvent] | None
    issues: list[DashboardIssue]  # critical -> warning -> info, then card order
    backlog: DashboardBacklog
