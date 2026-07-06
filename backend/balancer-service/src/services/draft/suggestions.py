"""Per-player FIT scoring for draft autopick and suggestions.

A lightweight, pure-Python replica of the balancer's per-player discomfort
heuristic (``src/domain/balancer/entities.py``) and role-impact weights
(Rust ``moo_core`` ``lib.rs``). It scores a *single* candidate against a team's
open role capacity — it is NOT the full multi-objective genetic solver — so
autopick and ``/suggestions`` stay synchronous and deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from shared.core.enums import DraftAutopickStrategy, DraftRole

# Role-impact weights — mirror moo_core/src/lib.rs (tank 1.4 / dps 1.0 / support 1.1).
DEFAULT_ROLE_IMPACT: dict[DraftRole, float] = {
    DraftRole.TANK: 1.4,
    DraftRole.DPS: 1.0,
    DraftRole.SUPPORT: 1.1,
}


@dataclass(frozen=True)
class FitPlayer:
    player_id: int
    rank_value: int
    playable_roles: frozenset[DraftRole]
    preference_order: tuple[DraftRole, ...] = ()
    is_flex: bool = False
    user_id: int | None = None
    # Per-role ranks (role -> SR). ``rank_value`` is the fallback when a role
    # has no specific entry, so candidates are scored at the rank of the role
    # they'd actually fill — not their primary-role rank.
    rank_by_role: Mapping[DraftRole, int] = field(default_factory=dict)

    def rank_for(self, role: DraftRole) -> int:
        return self.rank_by_role.get(role, self.rank_value)


@dataclass(frozen=True)
class FitConfig:
    role_impact: Mapping[DraftRole, float] = field(default_factory=lambda: dict(DEFAULT_ROLE_IMPACT))
    discomfort_weight: float = 1.0
    # Large enough that role-need dominates raw fit when filling scarce roles.
    role_need_bonus: float = 1_000_000.0


@dataclass(frozen=True)
class FitResult:
    player_id: int
    role: DraftRole
    fit_score: float
    breakdown: dict[str, float]


def role_discomfort(player: FitPlayer, role: DraftRole) -> int:
    """Mirror of balancer ``Player.discomfort_map`` construction."""
    if player.is_flex and role in player.playable_roles:
        return 0
    if role in player.preference_order:
        return player.preference_order.index(role) * 100
    return 1000 if role in player.playable_roles else 5000


def player_fit(
    player: FitPlayer,
    role: DraftRole,
    cfg: FitConfig,
    *,
    strategy: DraftAutopickStrategy = DraftAutopickStrategy.BEST_FIT,
    remaining_capacity: int = 0,
) -> FitResult:
    impact = cfg.role_impact.get(role, 1.0)
    discomfort = role_discomfort(player, role)
    role_rank = player.rank_for(role)
    rating_term = role_rank * impact
    comfort_term = cfg.discomfort_weight * discomfort

    if strategy == DraftAutopickStrategy.BEST_AVAILABLE:
        score = float(role_rank)
        need_term = 0.0
    elif strategy == DraftAutopickStrategy.ROLE_NEED:
        need_term = cfg.role_need_bonus * remaining_capacity
        score = need_term + rating_term - comfort_term
    else:  # BEST_FIT
        need_term = 0.0
        score = rating_term - comfort_term

    return FitResult(
        player_id=player.player_id,
        role=role,
        fit_score=score,
        breakdown={
            "rating": rating_term,
            "discomfort": float(discomfort),
            "role_impact": impact,
            "role_need": need_term,
        },
    )


def _candidates(
    available: Sequence[FitPlayer],
    role_capacity: Mapping[DraftRole, int],
    cfg: FitConfig,
    strategy: DraftAutopickStrategy,
) -> list[FitResult]:
    open_roles = [role for role, cap in role_capacity.items() if cap > 0]
    results: list[FitResult] = []
    for player in available:
        for role in open_roles:
            if role not in player.playable_roles:
                continue
            results.append(
                player_fit(
                    player,
                    role,
                    cfg,
                    strategy=strategy,
                    remaining_capacity=role_capacity[role],
                )
            )
    return results


def _sort_key(result: FitResult, available_by_id: Mapping[int, FitPlayer]) -> tuple:
    # Higher fit, then higher rank (for the result's role), then lower player_id,
    # then role value asc — fully deterministic so autopick is reproducible.
    rank = available_by_id[result.player_id].rank_for(result.role)
    return (-result.fit_score, -rank, result.player_id, result.role.value)


def best_fit(
    available: Sequence[FitPlayer],
    role_capacity: Mapping[DraftRole, int],
    strategy: DraftAutopickStrategy,
    cfg: FitConfig,
) -> FitResult | None:
    results = _candidates(available, role_capacity, cfg, strategy)
    if not results:
        return None
    by_id = {p.player_id: p for p in available}
    return min(results, key=lambda r: _sort_key(r, by_id))


def rank_suggestions(
    available: Sequence[FitPlayer],
    role_capacity: Mapping[DraftRole, int],
    cfg: FitConfig,
    *,
    strategy: DraftAutopickStrategy = DraftAutopickStrategy.BEST_FIT,
    limit: int = 5,
) -> list[FitResult]:
    results = _candidates(available, role_capacity, cfg, strategy)
    by_id = {p.player_id: p for p in available}
    # Best role per player, then top-N players by fit.
    best_per_player: dict[int, FitResult] = {}
    for r in sorted(results, key=lambda r: _sort_key(r, by_id)):
        best_per_player.setdefault(r.player_id, r)
    ordered = sorted(best_per_player.values(), key=lambda r: _sort_key(r, by_id))
    return ordered[:limit]
