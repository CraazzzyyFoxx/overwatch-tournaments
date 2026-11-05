"""Pure flow node functions (spec §5.4): filter ``top`` / ``per_item_top`` and merge."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shared.domain.flow.config import FilterNodeConfig

__all__ = ("ResultRow", "compute_filter", "compute_merge")


@dataclass(frozen=True, slots=True)
class ResultRow:
    """One participant on a node port; the rank is its index in the list plus one."""

    workspace_member_id: int | None
    team_id: int | None
    stage_item_id: int | None = None
    item_rank: int | None = None
    score: float | None = None
    tie_group: int | None = None
    breakdown: dict[str, Any] | list[Any] | None = None


def compute_filter(
    config: FilterNodeConfig, rows: Sequence[ResultRow], *, item_order: Mapping[int, int]
) -> list[ResultRow]:
    n = config.n or 0
    if config.mode == "top":
        return list(rows[:n])
    if config.mode == "per_item_top":
        kept = [
            (r.item_rank, item_order.get(r.stage_item_id, 0), index, r)
            for index, r in enumerate(rows)
            if r.item_rank is not None and r.item_rank <= config.per_item.get(r.stage_item_id, n)
        ]
        return [r for *_, r in sorted(kept, key=lambda k: k[:3])]
    raise ValueError(f"filter mode {config.mode} is computed from phase 4")


def compute_merge(inputs: Sequence[Sequence[ResultRow]]) -> list[ResultRow]:
    seen: set[tuple[int | None, int | None]] = set()
    merged: list[ResultRow] = []
    for r in (r for rows in inputs for r in rows):
        if (key := (r.workspace_member_id, r.team_id)) not in seen:
            seen.add(key)
            merged.append(r)
    return merged
