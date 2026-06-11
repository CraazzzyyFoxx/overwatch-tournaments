"""Rating normalization layer.

Linearly scales player ratings so that the observed maximum rating maps to a
fixed canonical ceiling (default 3500) before optimization. Restores the
original rating units after the optimizer returns. This makes the cost
function — and especially the piecewise gap-penalty thresholds in
``calculate_gap_penalty`` — dataset-independent.

Discomfort values (0 / N*100 / 1000 / 5000) are deliberately NOT scaled:
they live on a separate, calibrated scale relative to the canonical 0-3500
rating range.
"""

from __future__ import annotations

from typing import Iterable

from src.services.balancer.algorithm.entities import Player, Team

_SCALE_EPSILON = 1e-9


class RatingNormalizer:
    """Linearly rescales player ratings to a canonical ceiling.

    Usage:
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        normalizer.apply(players)              # before optimization
        ...optimize...
        normalizer.restore_players(players)    # once
        normalizer.refresh_team_stats(teams)   # per variant
    """

    __slots__ = ("target_max", "_scale", "_fitted")

    def __init__(self, target_max: int = 3500) -> None:
        if target_max <= 0:
            raise ValueError(f"target_max must be positive, got {target_max}")
        self.target_max = target_max
        self._scale: float = 1.0
        self._fitted: bool = False

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def is_identity(self) -> bool:
        return abs(self._scale - 1.0) < _SCALE_EPSILON

    def fit(self, players: list[Player]) -> None:
        observed_max = 0
        for player in players:
            for rating in player.ratings.values():
                if rating > observed_max:
                    observed_max = rating
        if observed_max <= 0:
            self._scale = 1.0
        else:
            self._scale = self.target_max / observed_max
        self._fitted = True

    def apply(self, players: list[Player]) -> None:
        if not self._fitted:
            raise RuntimeError("RatingNormalizer.apply called before fit")
        if self.is_identity:
            return
        self._rescale_players(players, self._scale)

    def restore_players(self, players: list[Player]) -> None:
        if not self._fitted:
            raise RuntimeError("RatingNormalizer.restore_players called before fit")
        if self.is_identity:
            return
        self._rescale_players(players, 1.0 / self._scale)

    @staticmethod
    def refresh_team_stats(teams: Iterable[Team]) -> None:
        for team in teams:
            team._is_dirty = True
            team.calculate_stats()

    @staticmethod
    def _rescale_players(players: list[Player], factor: float) -> None:
        for player in players:
            rescaled = {
                role: int(round(rating * factor)) for role, rating in player.ratings.items()
            }
            player.ratings = rescaled
            player._max_rating = max(rescaled.values()) if rescaled else 0


__all__ = ["RatingNormalizer"]
