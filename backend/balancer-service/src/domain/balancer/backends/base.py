from __future__ import annotations

import dataclasses
import typing

from src.domain.balancer.config.defaults import AlgorithmConfig
from src.domain.balancer.entities import Player, Team
from src.domain.balancer.progress import ProgressCallback


@dataclasses.dataclass(frozen=True, slots=True)
class BalanceMetrics:
    """Backend-reported diagnostics for one balance solution.

    One flat shape shared by every backend: each backend sets only its own
    engine-prefixed fields, everything else stays ``None``. Mirrors the
    optional fields on the ``schemas.balancer.Statistics`` response model.
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
    #: Each soft rule's penalty by kind, in rating units (``mix_rules``).
    mix_balancer_rules: dict[str, float] | None = None

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
        see ``native/balancer_native/src/mix.rs``), so scaling the inputs
        scales the output by the same factor.
        """
        updates: dict[str, typing.Any] = {
            name: value * factor for name in self._RATING_UNIT_FIELDS if (value := getattr(self, name)) is not None
        }
        if self.mix_balancer_rules:
            updates["mix_balancer_rules"] = {kind: value * factor for kind, value in self.mix_balancer_rules.items()}
        return dataclasses.replace(self, **updates) if updates else self

    def to_dict(self) -> dict[str, typing.Any]:
        """Non-``None`` fields only, rounded to 4 places, ready to merge into a response payload."""
        return {
            key: {kind: round(penalty, 4) for kind, penalty in value.items()}
            if isinstance(value, dict)
            else round(value, 4)
            for key, value in dataclasses.asdict(self).items()
            if value is not None
        }


@dataclasses.dataclass(frozen=True, slots=True)
class BalanceSolution:
    """One ranked outcome: a full team split plus how it scored."""

    teams: list[Team]
    metrics: BalanceMetrics
    #: Per rule kind, what the rule says about this split beyond its penalty
    #: (``mix_rules.variant_annotations``); empty for an engine without rules.
    annotations: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@typing.runtime_checkable
class OptimizerBackend(typing.Protocol):
    """A team-balancing engine, addressed only through this shape.

    ``runtime.balance_teams`` prepares the shared, algorithm-agnostic context
    (player loading, must-play/bench trimming, captain assignment,
    role-assignment feasibility) once, then hands it to the selected backend
    (registry: ``backends/__init__.py``). A backend owns everything downstream:
    translating ``Player``/``Team`` into its engine's request shape, invoking
    it, and translating the result back into ``BalanceSolution``s.
    """

    #: Short, stable identifier (used for logging, metrics labels, and the
    #: persisted-balance ``algorithm`` audit column).
    name: str

    #: Hard ceiling on how many teams this engine can form, or ``None`` if
    #: it scales to any team count. When set, ``runtime._prepare_balance_context``
    #: caps the natural team count at this value and benches the surplus like an
    #: uneven remainder (optional players sit out before must-play ones).
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
