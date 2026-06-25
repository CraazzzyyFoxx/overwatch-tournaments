import typing

from pydantic import BaseModel, Field

from .base import BaseRead, PlayerRead, TeamRead, UserReadMin

__all__ = (
    "PlayerAnalytics",
    "TeamAnalytics",
    "TournamentAnalytics",
    "AnalyticsAlgorithmRead",
    "AnalyticsAnomaly",
    "PlayerStreak",
    "PlayerShiftUpdate",
    "PredictedDirection",
    "TournamentAnalyticsSummary",
    "BalancePlayerSnapshotRead",
    "BalanceQualityRead",
)


class AnalyticsAlgorithmRead(BaseRead):
    name: str
    # Whether this algorithm has computed shift rows for the queried tournament.
    # ``None`` when the algorithms were listed without a tournament context.
    has_data: bool | None = None


class AnalyticsAnomaly(BaseModel):
    player_id: int
    kind: str
    score: float
    confidence: float | None = None
    reasons: list[str] = Field(default_factory=list)
    encounter_id: int | None = None


PredictedDirection = typing.Literal["promote", "demote", "flat"]


class PlayerAnalytics(PlayerRead):
    points: float
    move_1: float | None
    move_2: float | None
    shift: float | None
    confidence: float
    effective_evidence: float
    sample_tournaments: int
    sample_matches: int
    log_coverage: float
    predicted_division: int | None = None
    predicted_direction: PredictedDirection = "flat"
    predicted_delta: int = 0
    anomalies: list[AnalyticsAnomaly] = Field(default_factory=list)


class TeamAnalytics(TeamRead):
    players: list[PlayerAnalytics]
    wins: int
    losses: int
    predicted_place: int | None = None
    placement_delta: int | None = None
    avg_confidence: float
    manual_shift_points: int
    anomalies: list[AnalyticsAnomaly] = Field(default_factory=list)
    balancer_shift: float
    manual_shift: float
    total_shift: float


class TournamentAnalyticsSummary(BaseModel):
    total_teams: int
    total_players: int
    avg_confidence: float
    anomaly_count: int
    manual_shift_team_count: int
    newcomer_count: int
    divergent_team_count: int
    avg_placement_delta: float


class TournamentAnalytics(BaseModel):
    teams: list[TeamAnalytics]
    teams_wins: dict[int, int]
    summary: TournamentAnalyticsSummary


class PlayerStreak(BaseModel):
    user: UserReadMin
    role: str
    sum_position: int
    current_position: int
    previous_position: int | None
    pre_previous_position: int | None


class PlayerShiftUpdate(BaseModel):
    player_id: int
    shift: int


# ---------------------------------------------------------------------------
# Balance quality snapshot schemas (extracted from the decommissioned
# ``src/routes/analytics_read.py``; the ``balance_quality`` RPC handler builds
# these by hand from ``AnalyticsBalanceSnapshot`` rows — keep field names,
# order and defaults identical so the response bytes stay the same).
# ---------------------------------------------------------------------------


class BalancePlayerSnapshotRead(BaseModel):
    user_id: int | None = None
    team_id: int | None = None
    assigned_role: str
    preferred_role: str | None = None
    assigned_rank: int
    discomfort: int = 0
    division_number: int | None = None
    is_captain: bool = False
    was_off_role: bool = False


class BalanceQualityRead(BaseModel):
    tournament_id: int
    algorithm: str
    division_scope: str | None = None
    team_count: int
    player_count: int
    avg_sr_overall: float
    sr_std_dev: float
    sr_range: float
    total_discomfort: int
    off_role_count: int
    objective_score: float | None = None
    players: list[BalancePlayerSnapshotRead]
