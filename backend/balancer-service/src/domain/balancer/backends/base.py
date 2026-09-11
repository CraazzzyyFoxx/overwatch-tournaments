from __future__ import annotations

import dataclasses
import typing

from src.domain.balancer.entities import Player, Team
from src.domain.balancer.progress import ProgressCallback
from src.services.balancer.config.defaults import AlgorithmConfig


@dataclasses.dataclass(frozen=True, slots=True)
class BalanceMetrics:
    """Backend-reported diagnostics for one balance solution.

    A single flat, typed shape shared by every backend instead of an
    untyped ``dict[str, float]`` -- each backend only ever sets its own
    fields (prefixed by engine so two engines' metrics never collide were
    they ever compared side by side), everything else stays ``None``.
    Mirrors the equivalent optional fields already on the
    ``schemas.balancer.Statistics`` response model.
    """

    # tournament_balancer (Rust NSGA-II Pareto front)
    balance_objective: float | None = None
    comfort_objective: float | None = None
    balance_objective_norm: float | None = None
    comfort_objective_norm: float | None = None
    composite_score: float | None = None

    # mix_balancer (brute-force two-team engine)
    mix_balancer_fairness: float | None = None
    mix_balancer_uniformity: float | None = None
    mix_balancer_role_fairness: float | None = None
    mix_balancer_role_points: float | None = None
    mix_balancer_quality_total: float | None = None

    #: Fields the engine reports in *rating* units. They are computed after
    #: ``RatingNormalizer`` has rescaled every rating to the canonical ceiling,
    #: so they come back on that scale and mean nothing next to a team total
    #: until they are divided back out (see ``rescale_ratings``).
    #: ``mix_balancer_role_points`` is a count of lost preference points and
    #: ``mix_balancer_quality_total`` sums the two kinds, so neither is here:
    #: the total stays the engine's own ranking key, comparable only between
    #: solutions of the same run.
    _RATING_UNIT_FIELDS = (
        "mix_balancer_fairness",
        "mix_balancer_uniformity",
        "mix_balancer_role_fairness",
    )

    def rescale_ratings(self, factor: float) -> BalanceMetrics:
        """Same metrics with every rating-unit field multiplied by ``factor``.

        Exact rather than approximate: each of those terms is homogeneous of
        degree 1 in rating (an absolute difference, or a power mean of them --
        see ``native/mix_balancer/mix_balancer.cpp``), so scaling the inputs
        scales the output by the same factor.
        """
        updates = {
            name: value * factor for name in self._RATING_UNIT_FIELDS if (value := getattr(self, name)) is not None
        }
        return dataclasses.replace(self, **updates) if updates else self

    def to_dict(self) -> dict[str, float]:
        """Non-``None`` fields only, ready to merge into a response payload."""
        return {key: value for key, value in dataclasses.asdict(self).items() if value is not None}


@dataclasses.dataclass(frozen=True, slots=True)
class BalanceSolution:
    """One ranked outcome: a full team split plus how it scored."""

    teams: list[Team]
    metrics: BalanceMetrics


@typing.runtime_checkable
class OptimizerBackend(typing.Protocol):
    """A team-balancing engine, addressed only through this shape.

    Two backends implement it today: ``TournamentBalancerBackend`` (the
    in-house Rust NSGA-II optimizer, N-team capable -- the default) and
    ``MixBalancerBackend`` (a vendored brute-force engine pinned to exactly
    two teams, used only by the mix/custom-game flow). See
    ``domain/balancer/backends/__init__.py`` for the registry.

    ``domain/balancer/runtime.py`` prepares the shared context (player
    loading, must-play/bench trimming, captain assignment, role-assignment
    feasibility -- all algorithm-agnostic) once, then hands the result to
    whichever backend was selected. A backend owns everything downstream of
    that: translating ``Player``/``Team`` into its own engine's request shape,
    invoking it, and translating the result back into ``BalanceSolution``s.
    """

    #: Short, stable identifier (used for logging, metrics labels, and the
    #: persisted-balance ``algorithm`` audit column).
    name: str

    #: Hard ceiling on how many teams this engine can form, or ``None`` if
    #: it scales to any team count. When set, ``runtime._prepare_balance_context``
    #: caps the natural team count at this value and benches the surplus the
    #: same way it already benches an uneven remainder -- must-play players
    #: first, optional players last.
    max_teams: int | None

    def solve(
        self,
        players: list[Player],
        num_teams: int,
        config: AlgorithmConfig,
        role_assignment: dict[str, str] | None,
        seed: int,
        progress_callback: ProgressCallback | None,
    ) -> list[BalanceSolution]:
        """Return ranked solutions for the same players."""
        ...


__all__ = ["BalanceMetrics", "BalanceSolution", "OptimizerBackend"]
