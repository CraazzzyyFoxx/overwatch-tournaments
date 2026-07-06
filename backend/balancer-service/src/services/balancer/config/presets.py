"""Canonical balancer configuration presets.

All weights are calibrated for the canonical 0-3500 rating scale enforced by
``RatingNormalizer``. Each preset stores only the delta from ``DEFAULT`` so
overrides remain readable; missing fields fall back to ``AlgorithmConfig``
defaults at runtime.

Only the Rust MOO solver is supported, so presets no longer carry an
``algorithm`` key.
"""

from __future__ import annotations

from typing import Any


class ConfigPresets:
    """Pre-configured settings for common balancing scenarios."""

    # Balanced default — fits the majority of tournaments. Compute budget tuned
    # for sub-second runs on Rust MOO with 4 islands in parallel.
    DEFAULT: dict[str, Any] = {
        "role_mask": {"Tank": 1, "Damage": 2, "Support": 2},
        "population_size": 60,
        "generation_count": 120,
        "mutation_rate": 0.35,
        "mutation_strength": 2,
        "average_mmr_balance_weight": 0.8,
        "team_total_balance_weight": 1.0,
        "max_team_gap_weight": 1.5,
        "role_discomfort_weight": 1.0,
        "max_role_discomfort_weight": 2.0,
        "role_line_balance_weight": 1.0,
        # Per-team normalized terms (Rust divides by team count); values are
        # pre-multiplied so behaviour matches the legacy sums at 4 teams.
        "intra_team_std_weight": 2.8,
        "internal_role_spread_weight": 1.2,
        "sub_role_collision_weight": 24.0,
        "team_max_pain_weight": 1.0,
        "tank_impact_weight": 1.4,
        "dps_impact_weight": 1.0,
        "support_impact_weight": 1.1,
        # Adjacent (sorted) tank-line gap, not the irreducible max-min spread.
        "tank_gap_weight": 1.0,
        "tank_std_weight": 1.5,
        "effective_total_std_weight": 1.2,
        "use_captains": True,
        "convergence_patience": 0,
        "convergence_epsilon": 0.005,
        "mutation_rate_min": 0.15,
        "mutation_rate_max": 0.65,
        "island_count": 4,
        "polish_max_passes": 50,
        "greedy_seed_count": 3,
        "stagnation_kick_patience": 15,
        "crossover_rate": 0.85,
        "max_result_variants": 10,
        "rating_scale_ceiling": 3500,
    }

    # Sub-second preview / debugging — weaker but meaningful balance.
    QUICK: dict[str, Any] = {
        "population_size": 30,
        "generation_count": 50,
        "polish_max_passes": 10,
        "island_count": 2,
        "greedy_seed_count": 1,
        "max_result_variants": 5,
    }

    # Official tournament play — balance dominates over comfort. Spends more
    # compute, applies aggressive polishing, emphasises tank-line parity.
    COMPETITIVE: dict[str, Any] = {
        "population_size": 100,
        "generation_count": 200,
        "average_mmr_balance_weight": 2.0,
        "team_total_balance_weight": 2.0,
        "max_team_gap_weight": 3.0,
        "tank_gap_weight": 1.8,
        "tank_std_weight": 2.0,
        "effective_total_std_weight": 2.0,
        "role_discomfort_weight": 0.5,
        "max_role_discomfort_weight": 1.0,
        "sub_role_collision_weight": 40.0,
        "polish_max_passes": 80,
        "island_count": 6,
        "stagnation_kick_patience": 20,
    }

    # Pickup / casual play — comfort dominates over balance.
    CASUAL: dict[str, Any] = {
        "population_size": 60,
        "generation_count": 100,
        "average_mmr_balance_weight": 0.4,
        "team_total_balance_weight": 0.6,
        "max_team_gap_weight": 0.8,
        "tank_gap_weight": 0.5,
        "role_discomfort_weight": 2.0,
        "max_role_discomfort_weight": 4.0,
        "sub_role_collision_weight": 48.0,
        "use_captains": False,
    }

    # Minimise off-role assignments at almost any cost.
    PREFERENCE_FOCUSED: dict[str, Any] = {
        "population_size": 80,
        "generation_count": 150,
        "role_discomfort_weight": 3.0,
        "max_role_discomfort_weight": 6.0,
        "sub_role_collision_weight": 64.0,
        "average_mmr_balance_weight": 0.5,
        "max_team_gap_weight": 1.0,
    }

    # Long, deep search — best quality, highest runtime.
    HIGH_QUALITY: dict[str, Any] = {
        "population_size": 200,
        "generation_count": 400,
        "mutation_rate": 0.45,
        "mutation_strength": 3,
        "mutation_rate_min": 0.2,
        "mutation_rate_max": 0.75,
        "polish_max_passes": 150,
        "island_count": 8,
        "stagnation_kick_patience": 25,
        "convergence_patience": 60,
    }


class ConfigBuilder:
    """Helper to compose canonical balancer configuration payloads."""

    def __init__(self, preset: str | None = None) -> None:
        self.config = {}
        if preset:
            preset_upper = preset.upper()
            if not hasattr(ConfigPresets, preset_upper):
                raise ValueError(f"Unknown preset: {preset}")
            self.config = getattr(ConfigPresets, preset_upper).copy()
        else:
            self.config = ConfigPresets.DEFAULT.copy()

    def with_role_mask(self, role_mask: dict[str, int]) -> ConfigBuilder:
        if not role_mask or not any(value > 0 for value in role_mask.values()):
            raise ValueError("Role mask must have at least one role with count > 0")
        self.config["role_mask"] = role_mask
        return self

    def with_population(self, population_size: int, generation_count: int) -> ConfigBuilder:
        if not 10 <= population_size <= 1000:
            raise ValueError("Population size must be between 10 and 1000")
        if not 10 <= generation_count <= 5000:
            raise ValueError("Generations must be between 10 and 5000")
        self.config["population_size"] = population_size
        self.config["generation_count"] = generation_count
        return self

    def with_ga_parameters(
        self,
        mutation_rate: float | None = None,
        mutation_strength: int | None = None,
    ) -> ConfigBuilder:
        if mutation_rate is not None:
            if not 0 <= mutation_rate <= 1:
                raise ValueError("Mutation rate must be between 0 and 1")
            self.config["mutation_rate"] = mutation_rate
        if mutation_strength is not None:
            if not 1 <= mutation_strength <= 10:
                raise ValueError("Mutation strength must be between 1 and 10")
            self.config["mutation_strength"] = mutation_strength
        return self

    def with_weights(
        self,
        average_mmr_balance_weight: float | None = None,
        role_discomfort_weight: float | None = None,
        max_role_discomfort_weight: float | None = None,
        team_total_balance_weight: float | None = None,
        max_team_gap_weight: float | None = None,
        role_line_balance_weight: float | None = None,
        intra_team_std_weight: float | None = None,
        internal_role_spread_weight: float | None = None,
    ) -> ConfigBuilder:
        overrides = {
            "average_mmr_balance_weight": average_mmr_balance_weight,
            "role_discomfort_weight": role_discomfort_weight,
            "max_role_discomfort_weight": max_role_discomfort_weight,
            "team_total_balance_weight": team_total_balance_weight,
            "max_team_gap_weight": max_team_gap_weight,
            "role_line_balance_weight": role_line_balance_weight,
            "intra_team_std_weight": intra_team_std_weight,
            "internal_role_spread_weight": internal_role_spread_weight,
        }
        for key, value in overrides.items():
            if value is None:
                continue
            if value < 0:
                raise ValueError(f"{key} must be >= 0")
            self.config[key] = value
        return self

    def with_captains(self, use_captains: bool) -> ConfigBuilder:
        self.config["use_captains"] = use_captains
        return self

    def build(self) -> dict[str, Any]:
        return self.config.copy()
