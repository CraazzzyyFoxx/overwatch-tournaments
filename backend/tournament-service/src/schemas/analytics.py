from pydantic import BaseModel

from src.schemas import BaseRead, PlayerRead, TeamRead
from src.schemas.user_base import UserRead

__all__ = (
    "PlayerAnalytics",
    "TeamAnalytics",
    "TournamentAnalytics",
    "AnalyticsAlgorithmRead",
    "PlayerStreak",
    "PlayerShiftUpdate",
)


class AnalyticsAlgorithmRead(BaseRead):
    name: str


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


class TeamAnalytics(TeamRead):
    players: list[PlayerAnalytics]
    balancer_shift: int
    manual_shift: int
    total_shift: int


class TournamentAnalytics(BaseModel):
    teams: list[TeamAnalytics]
    teams_wins: dict[int, int]


class PlayerStreak(BaseModel):
    user: UserRead
    role: str
    sum_position: int
    current_position: int
    previous_position: int | None
    pre_previous_position: int | None


class PlayerShiftUpdate(BaseModel):
    player_id: int
    shift: int
