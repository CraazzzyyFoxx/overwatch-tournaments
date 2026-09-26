"""Per-round best-of resolution for bracket generation and backfill.

The configuration lives on the stage: ``Stage.best_of_default`` (the fallback),
``Stage.best_of_final`` (an elimination stage's last round, NULL = none) and one
``StageRoundBestOf`` row per round with its own length.

Resolution precedence for an encounter in round ``R`` of stage ``S``:

1. ``S`` is elimination AND ``R`` == the max round of the generated set AND
   ``final`` is set -> ``final``.
2. ``R`` has a round row -> that row's best-of.
3. otherwise -> ``default``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_BEST_OF = 3


@dataclass
class BestOfConfig:
    default: int = DEFAULT_BEST_OF
    by_round: dict[int, int] = field(default_factory=dict)
    final: int | None = None


def best_of_config(stage: Any) -> BestOfConfig:
    """The stage's series lengths, as the resolver reads them."""
    return BestOfConfig(
        default=stage.best_of_default,
        by_round={row.round: row.best_of for row in stage.round_best_of},
        final=stage.best_of_final,
    )


def resolve_best_of(cfg: BestOfConfig, round_number: int, *, is_final: bool) -> int:
    """Resolve the best-of for a single encounter (see module docstring)."""
    if is_final and cfg.final is not None:
        return cfg.final
    if round_number in cfg.by_round:
        return cfg.by_round[round_number]
    return cfg.default
