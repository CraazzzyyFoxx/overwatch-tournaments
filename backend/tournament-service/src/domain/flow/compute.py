"""Pure flow node functions (spec §5.4): filter in every mode, merge, split, leaderboard."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import groupby
from typing import Any

from shared.domain.flow.config import FilterNodeConfig, LeaderboardNodeConfig, SplitNodeConfig
from src.domain.stage.seeds import group_for_index
from src.services.standings.service import apply_pins

__all__ = (
    "PureOutput",
    "ResultRow",
    "compute_filter",
    "compute_leaderboard",
    "compute_merge",
    "compute_split",
    "participant_id",
)


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


def compute_split(config: SplitNodeConfig, rows: Sequence[ResultRow]) -> PureOutput:
    sizes = [bucket.size for bucket in config.buckets]
    buckets: list[list[ResultRow]] = [[] for _ in sizes]
    if config.serpentine:

        def full(i: int) -> bool:
            return sizes[i] is not None and len(buckets[i]) >= sizes[i]

        dealt = 0
        for r in rows:
            if all(full(i) for i in range(len(sizes))):
                break
            while full(i := group_for_index(dealt, len(sizes), snake=True)):
                dealt += 1
            buckets[i].append(r)
            dealt += 1
    else:
        start = 0
        for i, size in enumerate(sizes):
            end = len(rows) if size is None else start + size
            buckets[i] = list(rows[start:end])
            start = end
    return PureOutput({f"bucket_{i}": bucket for i, bucket in enumerate(buckets, 1)})


def compute_leaderboard(config: LeaderboardNodeConfig, rows: Sequence[ResultRow]) -> PureOutput:
    if not config.pins:
        return PureOutput({"ranking": list(rows)})
    by_id = {participant_id(r): r for r in rows}
    placed = apply_pins(
        [(participant_id(r), index) for index, r in enumerate(rows, 1)],
        {p.participant_id: p.position for p in config.pins},
    )
    ordered = [(by_id[pid], pinned) for pid, _position, pinned in placed]
    ranking: list[ResultRow] = []
    # A pinned row is never tied; an unpinned one stays tied only with the adjacent unpinned rows of its group, and a
    # run that a pin split gets its own tie group: its head rank (the group numbers of the input may repeat).
    for key, run in groupby(((r, None if pinned else r.tie_group) for r, pinned in ordered), key=lambda pair: pair[1]):
        members = [r for r, _ in run]
        head = len(ranking) + 1 if key is not None and len(members) > 1 else None
        ranking.extend(replace(r, tie_group=head) for r in members)
    return PureOutput({"ranking": ranking})
