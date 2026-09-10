"""Per-player FIT scoring for draft autopick and suggestions.

A lightweight, pure-Python replica of the balancer's per-player discomfort
heuristic (``domain/balancer/entities.py``) and role-impact weights
(Rust ``tournament_balancer`` ``lib.rs``). It scores a *single* candidate against a team's
open role capacity — it is NOT the full multi-objective genetic solver — so
autopick and ``/suggestions`` stay synchronous and deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from shared.core.enums import DraftAutopickStrategy, HeroClass
from src.domain.draft.entities import FitConfig, FitPlayer, FitResult

__all__ = ("best_fit", "player_fit", "rank_suggestions", "role_discomfort")


def role_discomfort(player: FitPlayer, role: HeroClass) -> int:
    """How much a role hurts this player, for autopick ranking.

    NOT in step with the balancer, despite encoding the same idea. ``preference_order``
    carries only the primary role here, so both non-priority roles land on the flat
    1000 below, while the balancer walks a full ordering and charges 100 and 200.
    Pinned by ``TestDiscomfortDivergesFromTheBalancer``; see the code-mirrors
    registry, class D.
    """
    if player.is_flex and role in player.playable_roles:
        return 0
    if role in player.preference_order:
        return player.preference_order.index(role) * 100
    return 1000 if role in player.playable_roles else 5000


def player_fit(
    player: FitPlayer,
    role: HeroClass,
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
    role_capacity: Mapping[HeroClass, int],
    cfg: FitConfig,
    strategy: DraftAutopickStrategy,
    allowed_options: set[tuple[int, HeroClass]] | None = None,
) -> list[FitResult]:
    open_roles = [role for role, cap in role_capacity.items() if cap > 0]
    results: list[FitResult] = []
    for player in available:
        for role in open_roles:
            if role not in player.playable_roles:
                continue
            if allowed_options is not None and (player.player_id, role) not in allowed_options:
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
    return (-result.fit_score, -rank, result.player_id, result.role.slot_code)


def best_fit(
    available: Sequence[FitPlayer],
    role_capacity: Mapping[HeroClass, int],
    strategy: DraftAutopickStrategy,
    cfg: FitConfig,
    *,
    allowed_options: set[tuple[int, HeroClass]] | None = None,
) -> FitResult | None:
    results = _candidates(available, role_capacity, cfg, strategy, allowed_options)
    if not results:
        return None
    by_id = {p.player_id: p for p in available}
    return min(results, key=lambda r: _sort_key(r, by_id))


def rank_suggestions(
    available: Sequence[FitPlayer],
    role_capacity: Mapping[HeroClass, int],
    cfg: FitConfig,
    *,
    strategy: DraftAutopickStrategy = DraftAutopickStrategy.BEST_FIT,
    limit: int = 5,
    allowed_options: set[tuple[int, HeroClass]] | None = None,
) -> list[FitResult]:
    results = _candidates(available, role_capacity, cfg, strategy, allowed_options)
    by_id = {p.player_id: p for p in available}
    # Best role per player, then top-N players by fit.
    best_per_player: dict[int, FitResult] = {}
    for r in sorted(results, key=lambda r: _sort_key(r, by_id)):
        best_per_player.setdefault(r.player_id, r)
    ordered = sorted(best_per_player.values(), key=lambda r: _sort_key(r, by_id))
    return ordered[:limit]
