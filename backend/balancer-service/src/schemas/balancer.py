from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConfigOverrides(BaseModel):
    """Optional public configuration overrides for the balancing algorithm."""

    model_config = ConfigDict(extra="forbid")

    role_mask: dict[str, int] | None = Field(
        None,
        description="Role mask defining required players per role (e.g., {'Tank': 1, 'Damage': 2, 'Support': 2})",
    )

    population_size: int | None = Field(None, ge=10, le=1000, description="Population size for the moo solver")
    generation_count: int | None = Field(None, ge=10, le=5000, description="Number of generations")
    mutation_rate: float | None = Field(None, ge=0, le=1, description="Probability of mutation")
    mutation_strength: int | None = Field(None, ge=1, le=10, description="Number of mutation operations per mutation")

    average_mmr_balance_weight: float | None = Field(None, ge=0, description="Weight for MMR difference between teams")
    team_total_balance_weight: float | None = Field(
        None,
        ge=0,
        description="Weight for aligning total rating sums among all teams",
    )
    max_team_gap_weight: float | None = Field(
        None,
        ge=0,
        description="Penalty weight for the rating gap between strongest and weakest team",
    )
    role_discomfort_weight: float | None = Field(None, ge=0, description="Weight for player role discomfort")
    max_role_discomfort_weight: float | None = Field(None, ge=0, description="Weight for maximum discomfort penalty")
    role_line_balance_weight: float | None = Field(None, ge=0, description="Weight for balancing roles between teams")
    intra_team_std_weight: float | None = Field(
        None,
        ge=0,
        description=(
            "Weight for the standard deviation of ratings inside each team. "
            "Higher values push the optimizer to spread top players across teams."
        ),
    )
    internal_role_spread_weight: float | None = Field(
        None,
        ge=0,
        description="Weight for uneven role-average strength inside the same team",
    )
    sub_role_collision_weight: float | None = Field(
        None,
        ge=0,
        description=(
            "Penalty weight per pair of players in the same team sharing the same "
            "role subclass. Use 0 to disable."
        ),
    )
    team_max_pain_weight: float | None = Field(
        None,
        ge=0,
        description=(
            "Weight for the per-team maximum role discomfort averaged over teams."
        ),
    )
    rank_comfort_tilt: float | None = Field(
        None, ge=0, le=1, description="Ranking tilt between balance and comfort (0.5 = balanced)"
    )
    tank_impact_weight: float | None = Field(
        None,
        ge=0,
        description="Importance multiplier for Tank role contribution in the effective team total.",
    )
    dps_impact_weight: float | None = Field(
        None,
        ge=0,
        description="Importance multiplier for Damage role contribution in the effective team total.",
    )
    support_impact_weight: float | None = Field(
        None,
        ge=0,
        description="Importance multiplier for Support role contribution in the effective team total.",
    )
    tank_gap_weight: float | None = Field(
        None,
        ge=0,
        description="Penalty multiplier for the rating gap between the strongest and weakest Tank lines.",
    )
    tank_std_weight: float | None = Field(
        None,
        ge=0,
        description="Penalty multiplier for Tank-line standard deviation across teams.",
    )
    effective_total_std_weight: float | None = Field(
        None,
        ge=0,
        description="Penalty multiplier for the weighted effective team-total standard deviation.",
    )

    use_captains: bool | None = Field(None, description="Whether to use captain assignment")
    convergence_patience: int | None = Field(
        None,
        ge=0,
        le=5000,
        description="Number of generations without meaningful Pareto improvement before early stop logic can trigger.",
    )
    convergence_epsilon: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Minimum relative improvement required to continue once convergence patience is reached.",
    )
    mutation_rate_min: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Lower bound for adaptive mutation rate during the Rust MOO search.",
    )
    mutation_rate_max: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Upper bound for adaptive mutation rate during the Rust MOO search.",
    )
    island_count: int | None = Field(
        None,
        ge=1,
        le=64,
        description="Number of independent Rust MOO islands explored in parallel.",
    )
    polish_max_passes: int | None = Field(
        None,
        ge=0,
        le=1000,
        description="Maximum local-polishing passes applied to final archive solutions.",
    )
    greedy_seed_count: int | None = Field(
        None,
        ge=0,
        le=1000,
        description="How many initial individuals are built from greedy seeding before random fill.",
    )
    stagnation_kick_patience: int | None = Field(
        None,
        ge=0,
        le=5000,
        description="Generations without archive improvement before a stronger mutation kick is applied.",
    )
    crossover_rate: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Probability of crossover when producing Rust MOO offspring.",
    )
    time_limit_ms: int | None = Field(
        None,
        ge=100,
        le=600000,
        description=(
            "Hard wall-clock budget for the native optimizer in milliseconds; "
            "the best result found so far is returned when exceeded."
        ),
    )
    max_result_variants: int | None = Field(
        None,
        ge=1,
        le=200,
        description="Maximum number of result variants to return for the selected solver",
    )

class BalanceRequest(BaseModel):
    """Request schema for direct team balancing."""

    player_data: dict = Field(..., description="Player data in the tournament format")
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
