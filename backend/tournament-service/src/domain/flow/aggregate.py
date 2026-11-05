"""The aggregate node (spec §7.4): scores every input row, totals per participant, orders with ties and a breakdown."""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from shared.core.enums import FlowUnit
from shared.domain.ffa_formula import compile_formula
from shared.domain.flow.config import AGGREGATE_VARIABLES, AggregateNodeConfig
from src.domain.flow.compute import PureOutput, ResultRow, participant_id

__all__ = ("AggregateInput", "compute_aggregate")

_METRICS = ("wins", "draws", "losses", "map_diff", "buchholz", "ffa_score")
_NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class AggregateInput:
    node_id: int
    rows: Sequence[ResultRow]
    final: bool
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Entry:
    index: int  #: position of the input in the edge order
    place: int
    score: float


def compute_aggregate(
    config: AggregateNodeConfig, inputs: Sequence[AggregateInput], *, members_by_team: Mapping[int, Sequence[int]]
) -> PureOutput:
    formula = (
        compile_formula(config.score.formula or "", (), variables=AGGREGATE_VARIABLES)
        if config.score.preset == "formula"
        else None
    )
    entries: dict[int, list[_Entry]] = {}
    for index, source in enumerate(inputs):
        for place, row in enumerate(source.rows, 1):
            metrics = row.breakdown if isinstance(row.breakdown, dict) else {}
            if config.score.preset == "stage_points":
                score = row.score or 0
            elif formula is None:
                score = config.score.table.get(str(place), 0)
            else:
                values = {"place": place, "participants": len(source.rows), "points": row.score or 0}
                score = formula.evaluate({**values, **{m: float(metrics.get(m) or 0) for m in _METRICS}})
            for pid in _participants(config.unit, row, members_by_team):
                entries.setdefault(pid, []).append(_Entry(index, place, score))

    recent = sorted(range(len(inputs)), key=lambda i: inputs[i].completed_at or _NEVER, reverse=True)
    last_n = set(recent[: config.n or 0])
    last_done = max(
        (i for i, source in enumerate(inputs) if source.final and source.completed_at),
        key=lambda i: inputs[i].completed_at or _NEVER,
        default=None,
    )
    max_place = max((e.place for rows in entries.values() for e in rows), default=0)

    totals: dict[int, float] = {}
    counted: dict[int, set[int]] = {}
    for pid, rows in entries.items():
        match config.mode:
            case "sum_last_n":
                picked = {e.index for e in rows if e.index in last_n}
            case "sum_best_n":
                picked = {e.index for e in sorted(rows, key=lambda e: -e.score)[: config.n or 0]}
            case _:
                picked = {e.index for e in rows}
        counted[pid] = picked
        total = sum(e.score for e in rows if e.index in picked)
        totals[pid] = total / len(rows) if config.mode == "average" else total

    def key(pid: int) -> tuple:
        rows = entries[pid]
        places = Counter(e.place for e in rows)
        best = tuple(-places[place] for place in range(1, max_place + 1)) if "best_places" in config.tiebreak else ()
        last = next((e.place for e in rows if e.index == last_done), math.inf) if "last_input" in config.tiebreak else 0
        return -totals[pid], best, last

    keys = {pid: key(pid) for pid in entries}
    ranked = sorted(entries, key=lambda pid: (keys[pid], pid))
    heads: dict[int, int] = {}  # participant -> rank of the first of its tie
    for rank, pid in enumerate(ranked, 1):
        heads[pid] = heads[ranked[rank - 2]] if rank > 1 and keys[ranked[rank - 2]] == keys[pid] else rank
    tied = Counter(heads.values())

    players = config.unit == FlowUnit.PLAYERS
    return PureOutput(
        {
            "ranking": [
                ResultRow(
                    workspace_member_id=pid if players else None,
                    team_id=None if players else pid,
                    score=totals[pid],
                    tie_group=heads[pid] if tied[heads[pid]] > 1 else None,
                    breakdown=[
                        {
                            "node_id": inputs[e.index].node_id,
                            "place": e.place,
                            "score": e.score,
                            "counted": e.index in counted[pid],
                        }
                        for e in entries[pid]
                    ],
                )
                for pid in ranked
            ]
        }
    )


def _participants(unit: FlowUnit, row: ResultRow, members_by_team: Mapping[int, Sequence[int]]) -> Sequence[int]:
    """The participants a row scores for: a team row expands to its non-substitute members in a players aggregate."""
    if unit == FlowUnit.PLAYERS and row.workspace_member_id is None and row.team_id is not None:
        return members_by_team.get(row.team_id, ())
    return (participant_id(row),)
