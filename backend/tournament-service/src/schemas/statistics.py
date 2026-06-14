from pydantic import BaseModel

__all__ = (
    "TournamentStatistics",
    "DivisionStatistics",
    "PlayerStatistics",
    "OverallStatistics",
    "DashboardActiveTournamentStats",
    "DashboardIssues",
    "DashboardStats",
)


class TournamentStatistics(BaseModel):
    id: int
    number: int
    players_count: int
    avg_sr: float
    avg_closeness: float | None


class DivisionStatistics(BaseModel):
    id: int
    number: int
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


class DashboardStats(BaseModel):
    tournaments_total: int
    tournaments_active: int
    teams_total: int
    players_total: int
    encounters_total: int
    heroes_total: int
    gamemodes_total: int
    maps_total: int
    active_tournament_stats: DashboardActiveTournamentStats | None
    issues: DashboardIssues
