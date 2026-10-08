from __future__ import annotations

from typing import Any

from loguru import logger

from src.domain.balancer import native
from src.domain.balancer.determinism import build_balancer_seed, derive_balancer_seed
from src.domain.balancer.entities import Player, Team
from src.services.balancer.config.defaults import AlgorithmConfig

#: Engine metric name -> the name this domain reports it under.
_METRIC_NAMES = {
    "balance": "balance_objective",
    "comfort": "comfort_objective",
    "balance_norm": "balance_objective_norm",
    "comfort_norm": "comfort_objective_norm",
    "score": "composite_score",
}


def _serialize_native_request(
    players: list[Player],
    num_teams: int,
    config: AlgorithmConfig,
    role_assignment: dict[str, str] | None,
    seed: int,
) -> str:
    return native.build_request(
        players,
        num_teams,
        native.build_roles(
            config.role_mask,
            config.role_settings,
            lambda settings: {
                "impact": settings.impact,
                "line_gap_weight": settings.line_gap_weight,
                "line_std_weight": settings.line_std_weight,
            },
        ),
        {
            "population_size": config.population_size,
            "generation_count": config.generation_count,
            "mutation_rate": config.mutation_rate,
            "mutation_strength": config.mutation_strength,
            "max_result_variants": config.max_result_variants,
            "average_mmr_balance_weight": config.average_mmr_balance_weight,
            "team_total_balance_weight": config.team_total_balance_weight,
            "max_team_gap_weight": config.max_team_gap_weight,
            "role_discomfort_weight": config.role_discomfort_weight,
            "max_role_discomfort_weight": config.max_role_discomfort_weight,
            "team_max_pain_weight": config.team_max_pain_weight,
            "role_line_balance_weight": config.role_line_balance_weight,
            "intra_team_std_weight": config.intra_team_std_weight,
            "internal_role_spread_weight": config.internal_role_spread_weight,
            "sub_role_collision_weight": config.sub_role_collision_weight,
            "low_rank_threshold": config.low_rank_threshold,
            "low_rank_collision_weight": config.low_rank_collision_weight,
            "effective_total_std_weight": config.effective_total_std_weight,
            "use_captains": config.use_captains,
            "convergence_patience": config.convergence_patience,
            "convergence_epsilon": config.convergence_epsilon,
            "mutation_rate_min": config.mutation_rate_min,
            "mutation_rate_max": config.mutation_rate_max,
            "island_count": config.island_count,
            "polish_max_passes": config.polish_max_passes,
            "greedy_seed_count": config.greedy_seed_count,
            "stagnation_kick_patience": config.stagnation_kick_patience,
            "crossover_rate": config.crossover_rate,
            "time_limit_ms": config.time_limit_ms,
            "rank_comfort_tilt": config.rank_comfort_tilt,
        },
        seed=seed,
        role_assignment=role_assignment,
    )


def _log_native_repair_diagnostics(payload: dict[str, Any]) -> None:
    diagnostics = payload.get("repair_diagnostics")
    if not isinstance(diagnostics, dict):
        return

    crossover_children = int(diagnostics.get("crossover_children", 0) or 0)
    crossover_repaired = int(diagnostics.get("crossover_children_requiring_repair", 0) or 0)
    crossover_changed = int(diagnostics.get("crossover_children_changed_by_repair", 0) or 0)
    mutation_only_children = int(diagnostics.get("mutation_only_children", 0) or 0)
    mutation_only_repaired = int(diagnostics.get("mutation_only_children_requiring_repair", 0) or 0)

    crossover_repair_rate = crossover_repaired / crossover_children if crossover_children > 0 else 0.0
    mutation_repair_rate = mutation_only_repaired / mutation_only_children if mutation_only_children > 0 else 0.0

    logger.info(
        "Rust MOO repair diagnostics: crossover repaired {}/{} ({:.1%}), "
        "crossover changed by repair {}, duplicates {}, missing {}, over-capacity {}, "
        "captain-lock conflicts {}, mutation-only repaired {}/{} ({:.1%})",
        crossover_repaired,
        crossover_children,
        crossover_repair_rate,
        crossover_changed,
        int(diagnostics.get("crossover_duplicate_assignments_total", 0) or 0),
        int(diagnostics.get("crossover_missing_players_total", 0) or 0),
        int(diagnostics.get("crossover_over_capacity_total", 0) or 0),
        int(diagnostics.get("crossover_captain_lock_conflicts_total", 0) or 0),
        mutation_only_repaired,
        mutation_only_children,
        mutation_repair_rate,
    )


def run_moo_optimizer(
    players: list[Player],
    num_teams: int,
    config: AlgorithmConfig,
    progress_callback,
    role_assignment: dict[str, str] | None = None,
    seed: int | None = None,
) -> list[tuple[list[Team], dict[str, float]]]:
    resolved_seed = seed
    if resolved_seed is None:
        resolved_seed = derive_balancer_seed(build_balancer_seed(players, num_teams, config), "moo_optimizer")

    logger.info("Running moo via Rust backend")
    request = _serialize_native_request(players, num_teams, config, role_assignment, resolved_seed)
    payload = native.call_engine("run_moo_optimizer", request, progress_callback)
    _log_native_repair_diagnostics(payload)
    return [
        (teams, {ours: float(metrics.get(theirs, 0.0)) for theirs, ours in _METRIC_NAMES.items()})
        for teams, metrics in native.deserialize_variants(payload, players, config.role_mask)
    ]
