"""Pure flow node functions (spec §5.4): filter in every mode, merge."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from shared.domain.flow.config import FilterNodeConfig

__all__ = ("PureOutput", "ResultRow", "compute_filter", "compute_merge", "participant_id")


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


@dataclass(frozen=True, slots=True)
class PureOutput:
    """What a pure node computes: its rows per output port, and whether a tie straddles a cut it made."""

    ports: dict[str, list[ResultRow]]
    boundary_tie: bool = False


def participant_id(row: ResultRow) -> int:
    pid = row.workspace_member_id if row.workspace_member_id is not None else row.team_id
    if pid is None:
        raise ValueError("a result row names neither a player nor a team")
    return pid


def _straddles(rows: Sequence[ResultRow], cut: int) -> bool:
    """A tie group spans the row before the cut and the one after it."""
    return (
        0 < cut < len(rows) and rows[cut - 1].tie_group is not None and rows[cut - 1].tie_group == rows[cut].tie_group
    )


def compute_filter(config: FilterNodeConfig, rows: Sequence[ResultRow], *, item_order: Mapping[int, int]) -> PureOutput:
    boundary_tie = False
    match config.mode:
        case "top":
            n = config.n or 0
            passed, boundary_tie = list(rows[:n]), _straddles(rows, n)
        case "range":
            start, stop = (config.from_ or 1) - 1, config.to or 0
            passed, boundary_tie = list(rows[start:stop]), _straddles(rows, start) or _straddles(rows, stop)
        case "per_item_top":
            passed, boundary_tie = _per_item_top(config, rows, item_order)
        case "swiss_status":
            passed = [
                r
                for r in rows
                if isinstance(r.breakdown, dict) and r.breakdown.get("swiss_status") == config.swiss_status
            ]
        case "manual":
            chosen = set(config.manual)
            passed = [r for r in rows if participant_id(r) in chosen]
    return PureOutput({"passed": passed}, boundary_tie)


def _per_item_top(
    config: FilterNodeConfig, rows: Sequence[ResultRow], item_order: Mapping[int, int]
) -> tuple[list[ResultRow], bool]:
    n = config.n or 0
    groups: defaultdict[int | None, list[ResultRow]] = defaultdict(list)
    for r in rows:
        if r.item_rank is not None:
            groups[r.stage_item_id].append(r)
    kept: list[tuple[int, int, int, ResultRow]] = []
    boundary_tie = False
    for item, group in groups.items():
        group.sort(key=lambda r: r.item_rank or 0)
        cut = sum(1 for r in group if (r.item_rank or 0) <= config.per_item.get(item, n))
        boundary_tie = boundary_tie or _straddles(group, cut)
        upper = config.per_item_upper.get(item, config.upper)
        for r in group[:cut]:
            if upper is not None and (r.item_rank or 0) > upper:
                r = replace(r, breakdown={**(r.breakdown if isinstance(r.breakdown, dict) else {}), "bracket": "lower"})
            kept.append((r.item_rank or 0, item_order.get(item, 0), item or 0, r))
    return [r for *_, r in sorted(kept, key=lambda k: k[:3])], boundary_tie


def compute_merge(inputs: Sequence[Sequence[ResultRow]]) -> list[ResultRow]:
    seen: set[tuple[int | None, int | None]] = set()
    merged: list[ResultRow] = []
    for r in (r for rows in inputs for r in rows):
        if (key := (r.workspace_member_id, r.team_id)) not in seen:
            seen.add(key)
            merged.append(r)
    return merged
