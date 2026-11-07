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

__all__ = ("AggregateInput", "Seat", "compute_aggregate")

_METRICS = ("wins", "draws", "losses", "map_diff", "buchholz", "ffa_score")
_NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class AggregateInput:
    node_id: int
    rows: Sequence[ResultRow]
    final: bool
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Seat:
    """A non-substitute roster member of a team and the top-level role they played in it."""

    member_id: int
    role: str | None


@dataclass(frozen=True, slots=True)
class _Entry:
    index: int  #: position of the input in the edge order
    place: int
    score: float
    role: str | None
    team_id: int | None
    metrics: Mapping[str, float]


#: A participant's line in the aggregate: its id and, in a by-role ranking, the role (else None).
type _Key = tuple[int, str | None]


def compute_aggregate(
    config: AggregateNodeConfig, inputs: Sequence[AggregateInput], *, members_by_team: Mapping[int, Sequence[Seat]]
) -> PureOutput:
    """``members_by_team`` expands a team row in a players aggregate; a member row's role is ``row.role``."""
    formula = (
        compile_formula(config.score.formula or "", (), variables=AGGREGATE_VARIABLES)
        if config.score.preset == "formula"
        else None
    )
    entries: dict[_Key, list[_Entry]] = {}
    for index, source in enumerate(inputs):
        heads: dict[int, int] = {}  # tie_group -> rank of its first row: a shared place is its head rank
        for rank, row in enumerate(source.rows, 1):
            place = rank if row.tie_group is None else heads.setdefault(row.tie_group, rank)
            metrics = row.breakdown if isinstance(row.breakdown, dict) else {}
            if config.score.preset == "stage_points":
                score = row.score or 0
            elif formula is None:
                score = config.score.table.get(str(place), 0)
            else:
                values = {"place": place, "participants": len(source.rows), "points": row.score or 0}
                score = formula.evaluate({**values, **{m: float(metrics.get(m) or 0) for m in _METRICS}})
            shown = {m: metrics[m] for m in _METRICS if metrics.get(m) is not None}
            for pid, role in _participants(config.unit, row, members_by_team):
                key = (pid, role if config.by_role else None)
                entries.setdefault(key, []).append(_Entry(index, place, score, role, row.team_id, shown))

    # ``completed_at`` is the input's recency (the engine fills it in); the later edge is the more recent on a tie.
    def recency(i: int) -> tuple[datetime, int]:
        return inputs[i].completed_at or _NEVER, i

    last_n = set(sorted(range(len(inputs)), key=recency, reverse=True)[: config.n or 0])
    last_done = max((i for i, source in enumerate(inputs) if source.final), key=recency, default=None)
    max_place = max((e.place for rows in entries.values() for e in rows), default=0)

    totals: dict[_Key, float] = {}
    counted: dict[_Key, set[int]] = {}
    for key, rows in entries.items():
        match config.mode:
            case "sum_last_n":
                picked = {e.index for e in rows if e.index in last_n}
            case "sum_best_n":
                picked = {e.index for e in sorted(rows, key=lambda e: -e.score)[: config.n or 0]}
            case _:
                picked = {e.index for e in rows}
        counted[key] = picked
        total = sum(e.score for e in rows if e.index in picked)
        # Rounded: formula sums such as 0.1 + 0.2 and 0.3 must tie.
        totals[key] = round(total / len(rows) if config.mode == "average" else total, 9)

    def order(key: _Key) -> tuple:
        rows = entries[key]
        places = Counter(e.place for e in rows)
        best = tuple(-places[place] for place in range(1, max_place + 1)) if "best_places" in config.tiebreak else ()
        last = next((e.place for e in rows if e.index == last_done), math.inf) if "last_input" in config.tiebreak else 0
        return -totals[key], best, last

    keys = {key: order(key) for key in entries}
    # One role after another (the role-less last), each in ranking order; outside a by-role ranking every role is None.
    ranked = sorted(entries, key=lambda k: (k[1] is None, k[1] or "", keys[k], k[0]))
    heads: dict[_Key, int] = {}  # participant -> rank inside its role of the first of its tie
    rank = 0
    for i, key in enumerate(ranked):
        previous = ranked[i - 1] if i else None
        rank = 1 if previous is None or previous[1] != key[1] else rank + 1
        heads[key] = heads[previous] if rank > 1 and previous is not None and keys[previous] == keys[key] else rank
    tied = Counter((key[1], heads[key]) for key in ranked)

    players = config.unit == FlowUnit.PLAYERS
    return PureOutput(
        {
            "ranking": [
                ResultRow(
                    workspace_member_id=pid if players else None,
                    team_id=None if players else pid,
                    score=totals[(pid, role)],
                    tie_group=heads[(pid, role)] if tied[(role, heads[(pid, role)])] > 1 else None,
                    breakdown=[
                        {
                            "node_id": inputs[e.index].node_id,
                            "place": e.place,
                            "score": e.score,
                            "counted": e.index in counted[(pid, role)],
                            "role": e.role,
                            "team_id": e.team_id,
                            **e.metrics,
                        }
                        for e in entries[(pid, role)]
                    ],
                    role=role,
                )
                for pid, role in ranked
            ]
        }
    )


def _participants(
    unit: FlowUnit, row: ResultRow, members_by_team: Mapping[int, Sequence[Seat]]
) -> Sequence[tuple[int, str | None]]:
    """The participants a row scores for, with the role each played: a team row expands to its non-substitute members
    in a players aggregate."""
    if unit == FlowUnit.PLAYERS and row.workspace_member_id is None and row.team_id is not None:
        return [(seat.member_id, seat.role) for seat in members_by_team.get(row.team_id, ())]
    return ((participant_id(row), row.role),)
