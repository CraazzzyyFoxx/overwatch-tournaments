from pydantic import BaseModel

__all__ = (
    "TournamentStatistics",
    "DivisionStatistics",
    "PlayerStatistics",
    "OverallStatistics",
    "DashboardActiveTournamentStats",
    "DashboardIssues",
    "DashboardStats",
    "TournamentReadiness",
)


class TournamentStatistics(BaseModel):
    id: int
    name: str
    players_count: int
    avg_sr: float
    avg_closeness: float | None


class DivisionStatistics(BaseModel):
    id: int
    name: str
    tank_avg_div: float | None
    damage_avg_div: float | None
    support_avg_div: float | None


class PlayerStatistics(BaseModel):
    id: int
    name: str
    value: int | float


class OverallStatistics(BaseModel):
    tournaments: int
    teams: int
    players: int
    champions: int
    # Played volume — see tournament-service's copy of this model, which is the
    # one the public endpoint serves.
    encounters: int
    maps: int
    days: int
    hours: int


class DashboardActiveTournamentStats(BaseModel):
    tournament_id: int
    encounters_total: int
    encounters_missing_logs: int
    log_coverage_percent: int


class DashboardIssues(BaseModel):
    encounters_missing_logs: int
    teams_without_players: int
    tournaments_without_stages: int
    users_without_identities: int
    # Encounters whose scheduled slot has passed with no recorded result.
    encounters_awaiting_result: int
    # Captain-submitted results still waiting on an admin confirmation.
    encounters_pending_confirmation: int
    # Bracket slots still on StageItemInputType.EMPTY.
    stage_slots_empty: int


class DashboardStats(BaseModel):
    tournaments_total: int
    tournaments_active: int
    teams_total: int
    players_total: int
    encounters_total: int
    # Decision metrics: how far the current cycle has progressed.
    tournaments_registration_open: int
    encounters_completed: int
    heroes_total: int
    gamemodes_total: int
    maps_total: int
    active_tournament_stats: DashboardActiveTournamentStats | None
    issues: DashboardIssues


class TournamentReadiness(BaseModel):
    """Living-checklist aggregate for one tournament (D13, §7.1).

    Field groups are masked by the caller's workspace permissions:
    ``tournament.read`` gates the setup/bracket/logs fields, ``team.read`` gates
    the registration/pool/balance/draft fields — a missing group yields ``None``
    so the checklist renders "no-access" instead of zeros.
    """

    tournament_id: int
    status: str
    team_formation: str
    # visible with tournament.read:
    schedule_configured: bool | None
    grid_selected: bool | None
    stages_total: int | None
    stage_slots_filled: bool | None
    bracket_generated: bool | None
    encounters_total: int | None
    encounters_with_logs: int | None
    logs_used: bool | None
    # visible with team.read (None -> checklist renders no-access):
    registration_form_configured: bool | None
    registration_open: bool | None
    registrations_pending: int | None
    registrations_approved: int | None
    registrations_checked_in: int | None
    registrations_ranked: int | None
    pool_ready: int | None
    pool_need_fix: int | None
    balance_saved: bool | None
    balance_exported_at: str | None
    draft_session_status: str | None
