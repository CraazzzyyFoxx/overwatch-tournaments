"""Pluggable balancing backends behind a single ``OptimizerBackend`` interface.

Every algorithm the balancer can run -- ``tournament_balancer`` (the in-house
Rust NSGA-II optimizer) and ``mix_balancer`` (the exhaustive Rust two-team
engine) -- lives here as its own connector module: request/response
translation between the domain's backend-agnostic ``Player``/``Team``
entities and whatever shape that particular engine wants.
``domain/balancer/runtime.py`` only ever talks to the ``OptimizerBackend``
protocol, never to a specific engine.
"""

from __future__ import annotations

from src.domain.balancer.backends.base import OptimizerBackend
from src.domain.balancer.backends.mix_balancer import MixBalancerBackend
from src.domain.balancer.backends.tournament_balancer import TournamentBalancerBackend

_BACKENDS: dict[str, OptimizerBackend] = {
    "tournament_balancer": TournamentBalancerBackend(),
    "mix_balancer": MixBalancerBackend(),
}


def get_backend(name: str) -> OptimizerBackend:
    try:
        return _BACKENDS[name]
    except KeyError:
        available = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown balancer algorithm '{name}'; available: {available}") from None


__all__ = ["OptimizerBackend", "get_backend"]
