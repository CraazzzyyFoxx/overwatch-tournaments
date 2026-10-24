"""Player division forecast from a shift estimate and its uncertainty. No session."""

from __future__ import annotations

import typing
from statistics import NormalDist

from shared.division_grid import DEFAULT_GRID, DivisionGrid, canonical_tier_number

PredictedDirection = typing.Literal["promote", "demote", "flat"]

__all__ = ("PredictedDirection", "predict_player_division")

#: The largest move a forecast shows, in canonical divisions.
MAX_MOVE = 3


def _probability(margin: float, sd: float) -> float:
    """``P(X ≥ 0)`` for ``X ~ N(margin, sd²)``; a zero sd is the point mass at ``margin``."""
    return NormalDist().cdf(margin / sd) if sd > 0 else float(margin >= 0)


def predict_player_division(
    rank: int | None,
    grid: DivisionGrid,
    shift: float,
    shift_sd: float | None,
    *,
    threshold: float,
) -> tuple[int | None, PredictedDirection, int, float]:
    """Forecast the player's next division on the tournament ``grid``.

    The player's mis-rating ``m`` in canonical-ladder divisions (``DEFAULT_GRID``, + = belongs higher) is taken as
    ``N(shift, shift_sd²)``. The shown move is the largest ``k ≤ 3`` with ``P(m ≥ k − 0.5) ≥ threshold`` (promote),
    else the largest with ``P(m ≤ −(k − 0.5)) ≥ threshold`` (demote), else hold. The confidence is the probability
    of the shown outcome — for hold ``P(−0.5 < m < 0.5)``. A row without an sd holds with confidence 0.

    The move is applied on the canonical ladder from the player's canonical division and mapped back to the
    ``grid`` tier with the nearest canonical number (a tie moves past the half-way point), so the forecast always
    stays inside the grid. Returns ``(predicted division, direction, delta in grid tiers, confidence)``.
    """
    delta, confidence = 0, 0.0  # canonical delta: negative = promote (lower division number)
    if shift_sd is not None:
        moves = [(-k, _probability(shift - (k - 0.5), shift_sd)) for k in range(MAX_MOVE, 0, -1)]
        moves += [(k, _probability(-(k - 0.5) - shift, shift_sd)) for k in range(MAX_MOVE, 0, -1)]
        hold = _probability(0.5 - shift, shift_sd) - _probability(-0.5 - shift, shift_sd)
        delta, confidence = next(((move, p) for move, p in moves if p >= threshold), (0, hold))

    if delta < 0:
        direction: PredictedDirection = "promote"
    elif delta > 0:
        direction = "demote"
    else:
        direction = "flat"

    current = grid.resolve_division(rank)
    if current is None:
        return None, direction, 0, confidence
    if delta == 0:
        return current.number, direction, 0, confidence

    canonical = {tier.number: canonical_tier_number(tier, grid, DEFAULT_GRID) for tier in grid.tiers}
    origin = canonical[current.number]
    target = origin + delta
    predicted = min(canonical, key=lambda number: (abs(canonical[number] - target), -abs(canonical[number] - origin)))
    return predicted, direction, predicted - current.number, confidence
