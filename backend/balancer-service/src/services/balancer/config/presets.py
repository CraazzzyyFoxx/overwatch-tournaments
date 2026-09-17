"""Canonical balancer configuration presets.

All weights are calibrated for the canonical 0-3500 rating scale enforced by
``RatingNormalizer``. ``DEFAULT`` mirrors ``AlgorithmConfig``; the three
targeted presets below share one search budget and differ only in which axis
they optimize: team balance (``HIGH_QUALITY``), first-preference roles
(``PREFERENCE_FOCUSED``) or both (``COMBINED``). Each of them states its full
weight set rather than a delta, so a change of defaults cannot silently move
their tuning. Tuning evidence lives in ``native/tournament_balancer``'s
``quality_harness`` ablations.

Only the Rust MOO solver is supported, so presets no longer carry an
``algorithm`` key.
"""

from __future__ import annotations

from typing import Any

from src.services.balancer.config.defaults import AlgorithmConfig


class ConfigPresets:
    """Pre-configured settings for common balancing scenarios."""

    # Mirrors ``AlgorithmConfig`` field defaults, computed at import time so it
    # can never drift from them (see ``defaults.py``).
    DEFAULT: dict[str, Any] = AlgorithmConfig().model_dump()

    # Search budget shared by the three targeted presets.
    _deep_search: dict[str, Any] = {
        "population_size": 200,
        "generation_count": 1000,
        "mutation_rate": 0.45,
        "mutation_strength": 3,
        "mutation_rate_min": 0.2,
        "mutation_rate_max": 0.75,
        "polish_max_passes": 150,
        "island_count": 8,
        "stagnation_kick_patience": 25,
        "convergence_patience": 200,
        "max_result_variants": 30,
    }

    # Team balance first.
    HIGH_QUALITY: dict[str, Any] = {
        **_deep_search,
        "average_mmr_balance_weight": 4.0,
        "intra_team_std_weight": 0.5,
        "internal_role_spread_weight": 0.2,
        "tank_gap_weight": 0.25,
        "tank_std_weight": 0.75,
        "effective_total_std_weight": 0.75,
        "role_discomfort_weight": 1.0,
        "max_role_discomfort_weight": 2.0,
        "team_max_pain_weight": 1.0,
        "rank_comfort_tilt": 0.1,
    }

    # First-preference roles first.
    PREFERENCE_FOCUSED: dict[str, Any] = {
        **_deep_search,
        "average_mmr_balance_weight": 0.8,
        "intra_team_std_weight": 2.8,
        "internal_role_spread_weight": 1.2,
        "tank_gap_weight": 1.0,
        "tank_std_weight": 1.5,
        "effective_total_std_weight": 1.2,
        "role_discomfort_weight": 4.0,
        "max_role_discomfort_weight": 0.5,
        "team_max_pain_weight": 0.25,
        "rank_comfort_tilt": 0.8,
    }

    # Both axes, in between.
    COMBINED: dict[str, Any] = {
        **_deep_search,
        "average_mmr_balance_weight": 2.0,
        "intra_team_std_weight": 1.8,
        "internal_role_spread_weight": 0.8,
        "tank_gap_weight": 0.8,
        "role_discomfort_weight": 2.0,
        "max_role_discomfort_weight": 1.0,
        "team_max_pain_weight": 0.6,
        "rank_comfort_tilt": 0.45,
    }
