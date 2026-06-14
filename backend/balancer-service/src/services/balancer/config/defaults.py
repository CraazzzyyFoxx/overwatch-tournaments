"""Algorithm configuration defaults for the balancer solver.

Holds the canonical :class:`AlgorithmConfig` definition (field defaults and
limits) for the Rust MOO solver. This is the single source of truth for solver
parameter defaults; presets store only deltas from these values.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AlgorithmConfig(BaseSettings):
    """Configuration for balancer solver parameters."""

    model_config = SettingsConfigDict(
        env_prefix="BALANCER_",
        extra="ignore",
    )

    # Role configuration
    role_mask: dict[str, int] = Field(
        default={"Tank": 1, "Damage": 2, "Support": 2},
        description="Default role mask defining required players per role",
    )

    # Shared optimizer parameters
    population_size: int = Field(default=60, ge=10, le=1000)
    generation_count: int = Field(default=120, ge=10, le=5000)
    mutation_rate: float = Field(default=0.35, ge=0.0, le=1.0)
    mutation_strength: int = Field(default=2, ge=1, le=10)

    # Cost function weights
    average_mmr_balance_weight: float = Field(default=0.8, ge=0.0)
    team_total_balance_weight: float = Field(default=1.0, ge=0.0)
    max_team_gap_weight: float = Field(default=1.5, ge=0.0)
    role_discomfort_weight: float = Field(default=1.0, ge=0.0)
    max_role_discomfort_weight: float = Field(default=2.0, ge=0.0)
    role_line_balance_weight: float = Field(default=1.0, ge=0.0)
    # Per-team normalized terms (Rust divides by team count): defaults are
    # pre-multiplied so behaviour matches the legacy sums at 4 teams.
    intra_team_std_weight: float = Field(default=2.8, ge=0.0)
    internal_role_spread_weight: float = Field(default=1.2, ge=0.0)
    sub_role_collision_weight: float = Field(
        default=24.0,
        ge=0.0,
        description=(
            "Penalty weight per subclass-collision pair in a team, normalized "
            "per team count (e.g., two players with the same subclass on the "
            "same role)."
        ),
    )
    team_max_pain_weight: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Weight for the per-team maximum role discomfort averaged over "
            "teams. Makes 'one suffering player in every team' visible, "
            "unlike the single global maximum."
        ),
    )
    rank_comfort_tilt: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Ranking tilt between balance and comfort when ordering result "
            "variants. 0.5 = balanced (legacy); toward 1 favours comfort/off-role, "
            "toward 0 favours team balance (StdDev). Affects only variant ordering "
            "and primary selection, not the optimizer search."
        ),
    )

    # Rust MOO advanced objective shaping
    tank_impact_weight: float = Field(default=1.4, ge=0.0)
    dps_impact_weight: float = Field(default=1.0, ge=0.0)
    support_impact_weight: float = Field(default=1.1, ge=0.0)
    # Penalizes the largest hole between adjacent (sorted) tank lines instead
    # of the structurally irreducible max-min pool spread.
    tank_gap_weight: float = Field(default=1.0, ge=0.0)
    tank_std_weight: float = Field(default=1.5, ge=0.0)
    effective_total_std_weight: float = Field(default=1.2, ge=0.0)

    # Strategy configuration
    use_captains: bool = Field(default=True)
    convergence_patience: int = Field(default=0, ge=0, le=5000)
    convergence_epsilon: float = Field(default=0.005, ge=0.0, le=1.0)
    mutation_rate_min: float = Field(default=0.15, ge=0.0, le=1.0)
    mutation_rate_max: float = Field(default=0.65, ge=0.0, le=1.0)
    island_count: int = Field(default=4, ge=1, le=64)
    polish_max_passes: int = Field(default=50, ge=0, le=1000)
    greedy_seed_count: int = Field(default=3, ge=0, le=1000)
    stagnation_kick_patience: int = Field(default=15, ge=0, le=5000)
    crossover_rate: float = Field(default=0.85, ge=0.0, le=1.0)
    time_limit_ms: int | None = Field(
        default=None,
        ge=100,
        le=600000,
        description=(
            "Hard wall-clock budget for the native optimizer in milliseconds. "
            "When exceeded, evolution and polishing stop early and the best "
            "archive found so far is returned. Trades reproducibility "
            "(same seed may yield different results under load) for latency."
        ),
    )

    max_result_variants: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Maximum number of solution variants returned by the solver.",
    )

    # Rating normalization
    rating_scale_ceiling: int = Field(
        default=3500,
        ge=100,
        le=10000,
        description=(
            "Canonical max rating. Input ratings are linearly scaled so the "
            "observed maximum maps to this value before optimization. Keeps "
            "gap-penalty thresholds and weight calibration dataset-independent."
        ),
    )
