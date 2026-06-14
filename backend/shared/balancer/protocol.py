"""Protocol definition for balancer algorithms.

Any algorithm (CPAT, Genetic, future implementations) must satisfy the
:class:`BalancerAlgorithm` protocol so they can be used interchangeably
by the balancer service worker.
"""

from __future__ import annotations

from typing import Any, Protocol

from shared.balancer.types import BalanceOutput, PlayerInput, RoleMask


class BalancerAlgorithm(Protocol):
    """Structural subtyping protocol for balancer algorithms."""

    def solve(
        self,
        players: list[PlayerInput],
        mask: RoleMask,
        config: dict[str, Any],
    ) -> list[BalanceOutput]:
        """Run the balancing algorithm.

        Args:
            players: List of players to balance into teams.
            mask: Team composition template (roles and slot counts).
            config: Algorithm-specific configuration overrides.

        Returns:
            One or more solution variants, ordered by quality
            (best first).
        """
        ...
