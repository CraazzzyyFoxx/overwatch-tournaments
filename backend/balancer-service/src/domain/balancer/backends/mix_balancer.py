from __future__ import annotations

from typing import Any

from loguru import logger

from src.domain.balancer import native
from src.domain.balancer.backends.base import BalanceMetrics, BalanceSolution
from src.domain.balancer.entities import Player
from src.domain.balancer.progress import ProgressCallback
from src.services.balancer.config.defaults import AlgorithmConfig


def build_metrics(metrics: dict[str, Any]) -> BalanceMetrics:
    """The engine's quality terms -> this domain's typed metrics.

    Prefixed fields so they never collide with ``tournament_balancer``'s own
    (``balance_objective``, ``comfort_objective``, ...) on the shared
    ``BalanceMetrics`` dataclass.
    """
    return BalanceMetrics(
        mix_balancer_fairness=float(metrics["fairness"]),
        mix_balancer_uniformity=float(metrics["uniformity"]),
        mix_balancer_role_fairness=float(metrics["role_fairness"]),
        mix_balancer_role_points=float(metrics["role_points"]),
        mix_balancer_quality_total=float(metrics["total"]),
    )


def quality_coefficients(tilt: float) -> tuple[float, float, float]:
    """``mix_comfort_tilt`` -> (fairness, role_fairness, role_priority) weights.

    ``0`` weighs only how evenly the two teams' ranks split, ``1`` only how
    many players got a preferred role, and ``0.5`` reproduces the engine's own
    defaults (every coefficient ``1.0``) -- so a mix that never touches the
    knob balances exactly as it did before the knob existed.

    Uniformity carries no coefficient in the engine at all, so even a full
    comfort tilt keeps some pressure towards evenly spread teams.
    """
    balance = 2.0 * (1.0 - tilt)
    comfort = 2.0 * tilt
    return balance, balance, comfort


class MixBalancerBackend:
    """Adapter over the native exhaustive two-team engine
    (``balancer_native.run_mix_balancer``) -- pinned only to the
    mix/custom-game flow (see services/balancer/solver.run_mix_balance).

    Enumerates every player/role split and returns the true optimum (not a GA
    approximation), but the search is only tractable, and only implemented,
    for exactly two equal-size teams. The engine is deterministic by
    construction (no RNG), so ``seed`` and ``role_assignment`` (both
    ``tournament_balancer``-specific hints) travel in the shared request
    envelope but are unused.
    """

    name = "mix_balancer"
    max_teams = 2

    def solve(
        self,
        players: list[Player],
        num_teams: int,
        config: AlgorithmConfig,
        role_assignment: dict[str, str] | None,
        seed: int,
        progress_callback: ProgressCallback | None,
    ) -> list[BalanceSolution]:
        fairness, role_fairness, role_priority = quality_coefficients(config.mix_comfort_tilt)
        request = native.build_request(
            players,
            num_teams,
            native.build_roles(
                config.role_mask,
                config.role_settings,
                lambda settings: {"weight": settings.mix_weight},
            ),
            {
                "max_result_variants": config.max_result_variants,
                "fairness_weight": fairness,
                "role_fairness_weight": role_fairness,
                "role_priority_weight": role_priority,
            },
            seed=seed,
            role_assignment=role_assignment,
        )
        logger.info("Running mix_balancer exhaustive engine for a 2-team split")
        payload = native.call_engine("run_mix_balancer", request, progress_callback)
        return [
            BalanceSolution(teams=teams, metrics=build_metrics(metrics))
            for teams, metrics in native.deserialize_variants(payload, players, config.role_mask)
        ]


__all__ = ["MixBalancerBackend", "build_metrics", "quality_coefficients"]
