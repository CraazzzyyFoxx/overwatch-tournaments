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

from src.services.balancer.config.defaults import AlgorithmConfig


class ConfigPresets:
    """Pre-configured settings for common balancing scenarios."""

    # Balanced default — every field mirrors ``AlgorithmConfig``'s own field
    # defaults, computed once at import time so this can never drift from
    # them (previously a hand-copied 33-field dict that had already fallen
    # 4 fields behind: low_rank_threshold, low_rank_collision_weight,
    # rank_comfort_tilt, time_limit_ms — see ``defaults.py`` for tuning).
    DEFAULT: dict[str, Any] = AlgorithmConfig().model_dump()

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
    #
    # Значения подобраны абляцией `quality_harness` на шести профилях пула
    # (uniform / role_skew / narrow / wide_tank / one_trick / flex_heavy,
    # 8-40 команд, 3 сида): средние по ролям и глубина флекс-пула меняют
    # отклик на кнобы сильнее размера турнира, поэтому решение принималось
    # по геометрическому среднему отношений операционных метрик к baseline.
    #
    # Что дало выигрыш: convergence_patience 60 → 200 (comp 0.94 на всех
    # трёх этапах, +50% времени: 40 команд 21 c → 27 c); 1000 генераций
    # против 400 (mmr_std 4.66 → 2.23, total_gap 79 → 40 на 40 командах).
    # Что отвергнуто замерами: island_count 16 (0.98 при +50% времени),
    # population 320 (та же comp при +60% времени), generation_count 2000
    # (хуже 1000), convergence_epsilon 0.001, polish 60 (регресс 1.05-1.17
    # на крупных пулах — polish там ещё работает), polish 400 (плато),
    # mutation/crossover-кнобы (±2%, знак зависит от профиля пула).
    # Хард-стоп time_limit_ms (10 мин) в силе, прогоны в него влезают.
    HIGH_QUALITY: dict[str, Any] = {
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
