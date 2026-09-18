from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Generated from ``AlgorithmConfig`` -- one declaration per knob, see
# ``services/balancer/config/public_contract.py``. Re-exported here because the
# request schemas below are the public face of it.
from src.services.balancer.config.public_contract import ConfigOverrides

__all__ = [
    "BalanceJobResult",
    "BalanceRequest",
    "BalanceResponse",
    "BalancerConfigResponse",
    "ConfigOverrides",
    "CreateJobResponse",
    "FeasibilityReport",
    "JobEvent",
    "JobProgress",
    "JobStatusResponse",
    "PlayerData",
    "RoleFeasibility",
    "Statistics",
    "TeamData",
    "TournamentBalanceRequest",
]


class BalanceRequest(BaseModel):
    """Request schema for the synchronous, stateless balance (``rpc.balancer.balance``).

    Everything the solver needs travels in this payload: the pool, the per-team
    roster shape and the knobs. Nothing is read from the workspace, so the same
    body balanced twice yields the same teams regardless of tournament state.
    ``extra="forbid"`` so a misspelled field is a 422, not a silently ignored
    knob on a request whose whole point is being self-describing.
    """

    model_config = ConfigDict(extra="forbid")

    player_data: dict = Field(..., description="Player data in the tournament format")
    role_mask: dict[str, Annotated[int, Field(ge=0, le=20)]] | None = Field(
        None,
        description=(
            'Per-team slot counts keyed by roster slot code, e.g. {"tank": 1, "damage": 2, "support": 2} '
            "-- the default when omitted. Team count is derived from it: floor(players / sum(slots)); "
            "the remainder is benched. Input role names are matched case-insensitively against these "
            'keys, so a pool written with "Damage" fills the "damage" slots.'
        ),
    )
    config_overrides: ConfigOverrides | None = Field(None, description="Optional configuration overrides")


class TournamentBalanceRequest(BaseModel):
    """Balance a tournament's own pool. Carries no players on purpose.

    The xv-1 input is built server-side from ``shared.services.roster`` -- the
    same engine the draft reads -- so the caller cannot hand the algorithm a
    different set of ranks than the draft sees. Use ``BalanceRequest`` /the
    multipart upload only for a payload that is genuinely not a tournament pool.
    """

    config_overrides: ConfigOverrides | None = Field(None, description="Optional configuration overrides")


class PlayerData(BaseModel):
    uuid: str
    name: str
    assigned_rating: int
    role_discomfort: int
    is_captain: bool
    role_preferences: list[str]
    all_ratings: dict[str, int]
    # Stable per-role discomfort snapshot (computed from original preferences),
    # so the frontend can re-derive discomfort when a player is moved between
    # roles without re-running the solver. Defaulted for legacy payloads.
    all_discomforts: dict[str, int] = Field(default_factory=dict)
    is_flex: bool = False
    sub_role: str | None = None


class TeamData(BaseModel):
    id: int
    name: str
    average_mmr: float
    rating_variance: float
    total_discomfort: int
    max_discomfort: int
    roster: dict[str, list[PlayerData]]


class RoleFeasibility(BaseModel):
    role: str
    supply: int
    demand: int
    flex_supply: int = 0


class FeasibilityReport(BaseModel):
    total_slots: int
    structural_min_off_role: int
    flex_player_count: int = 0
    roles: list[RoleFeasibility] = Field(default_factory=list)


class Statistics(BaseModel):
    average_mmr: float
    mmr_std_dev: float
    total_teams: int
    players_per_team: int
    off_role_count: int = 0
    sub_role_collision_count: int = 0
    unbalanced_count: int = 0
    average_total_rating: float | None = None
    total_rating_std_dev: float | None = None
    max_total_rating_gap: float | None = None
    balance_objective: float | None = None
    comfort_objective: float | None = None
    balance_objective_norm: float | None = None
    comfort_objective_norm: float | None = None
    composite_score: float | None = None
    mix_balancer_fairness: float | None = None
    mix_balancer_uniformity: float | None = None
    mix_balancer_role_fairness: float | None = None
    mix_balancer_role_points: float | None = None
    mix_balancer_quality_total: float | None = None
    off_role_rate: float | None = None
    off_role_above_minimum: int | None = None
    feasibility: FeasibilityReport | None = None


class BalanceResponse(BaseModel):
    teams: list[TeamData]
    statistics: Statistics
    benched_players: list[PlayerData] = Field(default_factory=list)
    applied_config: dict[str, Any] | None = None


class BalanceJobResult(BaseModel):
    variants: list[BalanceResponse]


class BalancerConfigResponse(BaseModel):
    defaults: dict[str, Any]
    limits: dict[str, dict[str, int | float]]
    presets: dict[str, dict[str, Any]]
    fields: list[dict[str, Any]] = Field(default_factory=list)


class JobProgress(BaseModel):
    current: int | None = None
    total: int | None = None
    percent: float | None = None


class JobEvent(BaseModel):
    event_id: int
    timestamp: float
    level: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    message: str
    progress: JobProgress | None = None


class CreateJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    status_url: str
    result_url: str
    stream_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str | None = None
    tournament_id: int | None = None
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    progress: JobProgress | None = None
    error: str | None = None
    events_count: int = 0
