"""Swiss round generator with Monrad-first pairing preferences.

The generator keeps Monrad ordering as the primary preference:
- higher score groups are processed first
- same-score opponents are preferred over float-down pairings
- within a score group, top-half vs bottom-half pairings are preferred

A round is chosen so the *next* round stays pairable: a locally fine pairing
can strand the field in a state where no rematch-free round exists at all (six
teams, round 3). When the field has played itself into a corner anyway, the
round is built with the fewest rematches a greedy pass can manage rather than
leaving anyone idle -- a full field is worth more than a first meeting.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from typing import Any, Literal

from .types import BracketSkeleton, Pairing

_NON_CANONICAL_DISTANCE = 10_000
# How many rematch-free rounds to weigh before taking the best-ranked one as is.
# Monrad order puts the good pairings first, so the cap only bounds a field that
# is nearly played out; the fallback keeps such a round valid, just not vetted.
_LOOKAHEAD_BUDGET = 200
# Hard ceiling on search nodes visited by one search, shared by the candidate
# enumeration and the next-round matching probe. _LOOKAHEAD_BUDGET caps how many
# finished rounds are weighed; this caps the work spent looking for them, so a
# played-out field cannot stall the worker on an exponential tree.
_SEARCH_NODE_BUDGET = 50_000
# ...and on its wall time: a node sorts its candidates, so its cost grows with the
# field -- 50k nodes of a 30-team field ran 1.2 s on the event loop. A round makes
# at most two searches (rematch-free, then the fallback), so a call stays under 1 s.
_SEARCH_SECONDS = 0.4


class SwissPairingImpossibleError(ValueError):
    """Raised when no complete Swiss round can be built, not even with rematches."""


class _BudgetExhausted(Exception):
    """One search ran out of nodes or time; the round falls back, it is not impossible."""


class _NodeBudget:
    """Countdown of search nodes and wall time for one search; raises once the field costs too much."""

    __slots__ = ("deadline", "remaining")

    def __init__(self, limit: int = _SEARCH_NODE_BUDGET, seconds: float = _SEARCH_SECONDS) -> None:
        self.remaining = limit
        self.deadline = time.perf_counter() + seconds

    def spend(self) -> None:
        self.remaining -= 1
        # The clock is read every 256 nodes: a node is microseconds, the read is not free.
        if self.remaining < 0 or ((self.remaining & 0xFF) == 0 and time.perf_counter() > self.deadline):
            raise _BudgetExhausted


@dataclass(frozen=True)
class SwissStanding:
    team_id: int
    points: float
    buchholz: float = 0.0
    #: Match wins plus byes, and losses: what :class:`SwissThresholds` reads.
    wins: int = 0
    losses: int = 0


SwissStatus = Literal["qualified", "eliminated"]


@dataclass(frozen=True)
class SwissThresholds:
    """When a team's Swiss ends before the stage does (``Stage.swiss_*``).

    ``qualify_wins`` wins -- a bye counts as one -- put a team through,
    ``eliminate_losses`` losses put it out; a draw is neither. A decided team is
    paired no more. ``None`` = that end never closes; both ``None`` is falsy.
    """

    qualify_wins: int | None = None
    eliminate_losses: int | None = None

    @classmethod
    def of(cls, stage: Any) -> SwissThresholds:
        return cls(stage.swiss_qualify_wins, stage.swiss_eliminate_losses)

    def __bool__(self) -> bool:
        return self.qualify_wins is not None or self.eliminate_losses is not None

    def status(self, wins: int, losses: int) -> SwissStatus | None:
        # Both only after the thresholds were lowered mid-stage; through wins.
        if self.qualify_wins is not None and wins >= self.qualify_wins:
            return "qualified"
        if self.eliminate_losses is not None and losses >= self.eliminate_losses:
            return "eliminated"
        return None

    def stakes(self, records: Iterable[tuple[int, int]]) -> tuple[bool, bool]:
        """``(qualification, elimination)``: can a match between teams with these
        ``(wins, losses)`` put one of them through / out?"""
        records = list(records)
        return (
            self.qualify_wins is not None and any(wins + 1 >= self.qualify_wins for wins, _ in records),
            self.eliminate_losses is not None and any(losses + 1 >= self.eliminate_losses for _, losses in records),
        )


@dataclass(frozen=True)
class _TeamMeta:
    rank_index: int
    group_index: int
    pos_in_group: int
    group_size: int

    @property
    def half_size(self) -> int:
        return self.group_size // 2

    @property
    def is_top_half(self) -> bool:
        return self.pos_in_group < self.half_size

    @property
    def is_bottom_half(self) -> bool:
        return self.half_size <= self.pos_in_group < self.half_size * 2


def _bye_candidates(team_ids: list[int], bye_history: set[int]) -> list[int | None]:
    if len(team_ids) % 2 == 0:
        return [None]

    lowest_first = list(reversed(team_ids))
    without_bye = [team_id for team_id in lowest_first if team_id not in bye_history]
    return without_bye or lowest_first


def _build_team_meta(sorted_teams: list[SwissStanding]) -> dict[int, _TeamMeta]:
    metadata: dict[int, _TeamMeta] = {}
    groups: list[list[SwissStanding]] = []
    current_group: list[SwissStanding] = []
    group_key: float | None = None

    for standing in sorted_teams:
        key = standing.points
        if key != group_key and current_group:
            groups.append(current_group)
            current_group = []
        group_key = key
        current_group.append(standing)
    if current_group:
        groups.append(current_group)

    rank_index = 0
    for group_index, group in enumerate(groups):
        group_size = len(group)
        for pos_in_group, standing in enumerate(group):
            metadata[standing.team_id] = _TeamMeta(
                rank_index=rank_index,
                group_index=group_index,
                pos_in_group=pos_in_group,
                group_size=group_size,
            )
            rank_index += 1

    return metadata


def _pair_bucket(anchor: _TeamMeta, candidate: _TeamMeta) -> int:
    if anchor.group_index == candidate.group_index:
        if (anchor.is_top_half and candidate.is_bottom_half) or (anchor.is_bottom_half and candidate.is_top_half):
            return 0
        return 1
    return 2


def _canonical_distance(anchor: _TeamMeta, candidate: _TeamMeta) -> int:
    if anchor.group_index != candidate.group_index:
        return _NON_CANONICAL_DISTANCE

    if anchor.is_top_half and candidate.is_bottom_half:
        expected = anchor.half_size + anchor.pos_in_group
        return abs(candidate.pos_in_group - expected)

    if anchor.is_bottom_half and candidate.is_top_half:
        expected = anchor.pos_in_group - anchor.half_size
        return abs(candidate.pos_in_group - expected)

    return _NON_CANONICAL_DISTANCE


def _pair_priority(
    anchor_team_id: int,
    candidate_team_id: int,
    *,
    metadata: dict[int, _TeamMeta],
) -> tuple[int, int, int, int, int]:
    anchor = metadata[anchor_team_id]
    candidate = metadata[candidate_team_id]

    group_distance = abs(anchor.group_index - candidate.group_index)
    pair_bucket = _pair_bucket(anchor, candidate)
    canonical_distance = _canonical_distance(anchor, candidate)
    rank_distance = abs(candidate.rank_index - anchor.rank_index)

    return (
        pair_bucket,
        group_distance,
        canonical_distance,
        rank_distance,
        candidate.rank_index,
    )


def _has_perfect_matching(team_ids: list[int], played_pairs: set[frozenset[int]], budget: _NodeBudget) -> bool:
    """Can every team still be given an unplayed opponent?"""

    def _search(remaining: tuple[int, ...]) -> bool:
        budget.spend()
        if not remaining:
            return True
        anchor = remaining[0]
        for candidate in remaining[1:]:
            if frozenset({anchor, candidate}) in played_pairs:
                continue
            if _search(tuple(team_id for team_id in remaining[1:] if team_id != candidate)):
                return True
        return False

    return _search(tuple(team_ids))


def _keeps_next_round_pairable(
    team_ids: list[int],
    played_pairs: set[frozenset[int]],
    pair_order: list[tuple[int, int]],
    budget: _NodeBudget,
) -> bool:
    """Would another rematch-free round still exist after playing this one?

    Only an even field is checked: with an odd one the bye absorbs the team that
    has run out of opponents, so the round after is always pairable. A field that
    has played itself out entirely is fine too -- there is no next round to save.
    """
    if len(team_ids) % 2:
        return True

    after = played_pairs | {frozenset(pair) for pair in pair_order}
    if len(after) >= len(team_ids) * (len(team_ids) - 1) // 2:
        return True
    return _has_perfect_matching(team_ids, after, budget)


def _iter_pairings(
    team_ids: list[int],
    *,
    metadata: dict[int, _TeamMeta],
    played_pairs: set[frozenset[int]],
    budget: _NodeBudget,
    allow_rematches: bool = False,
) -> Iterator[list[tuple[int, int]]]:
    """Rounds for this field, best Monrad pairing first.

    Rematch-free by default. With ``allow_rematches`` a played pair is still
    the last thing considered for any anchor, so the first round yielded uses
    as few of them as a greedy pass can manage.
    """

    def _priority(anchor_team_id: int, candidate_team_id: int) -> tuple[int, ...]:
        rematch = 1 if frozenset({anchor_team_id, candidate_team_id}) in played_pairs else 0
        return (rematch, *_pair_priority(anchor_team_id, candidate_team_id, metadata=metadata))

    def _search(remaining: tuple[int, ...]) -> Iterator[tuple[tuple[int, int], ...]]:
        budget.spend()
        if not remaining:
            yield ()
            return

        anchor_team_id = remaining[0]
        candidates = sorted(remaining[1:], key=lambda candidate: _priority(anchor_team_id, candidate))

        for candidate_team_id in candidates:
            if not allow_rematches and frozenset({anchor_team_id, candidate_team_id}) in played_pairs:
                continue
            next_remaining = tuple(team_id for team_id in remaining[1:] if team_id != candidate_team_id)
            for remainder in _search(next_remaining):
                yield ((anchor_team_id, candidate_team_id),) + remainder

    for pairing in _search(tuple(team_ids)):
        yield list(pairing)


def generate_round(
    standings: list[SwissStanding],
    played_pairs: set[frozenset[int]],
    round_number: int,
    *,
    bye_history: set[int] | None = None,
) -> BracketSkeleton:
    """Generate pairings for one Swiss round using Monrad-first preferences.

    Args:
        standings: Current standings.
        played_pairs: Set of frozensets of team_id pairs already played.
        round_number: Round number for generated pairings.
        bye_history: Optional set of team_ids that already received a bye.
    """
    sorted_teams = sorted(standings, key=lambda standing: (standing.points, standing.buchholz), reverse=True)
    team_ids = [standing.team_id for standing in sorted_teams]
    bye_history = bye_history or set()

    def _pick(allow_rematches: bool) -> tuple[int | None, list[tuple[int, int]]] | None:
        budget = _NodeBudget()
        first: tuple[int | None, list[tuple[int, int]]] | None = None
        try:
            for candidate in _bye_candidates(team_ids, bye_history):
                pairing_standings = [standing for standing in sorted_teams if standing.team_id != candidate]
                pairing_team_ids = [standing.team_id for standing in pairing_standings]
                metadata = _build_team_meta(pairing_standings)
                for option in islice(
                    _iter_pairings(
                        pairing_team_ids,
                        metadata=metadata,
                        played_pairs=played_pairs,
                        budget=budget,
                        allow_rematches=allow_rematches,
                    ),
                    _LOOKAHEAD_BUDGET,
                ):
                    if first is None:
                        first = (candidate, option)
                    if _keeps_next_round_pairable(team_ids, played_pairs, option, budget):
                        return candidate, option
        except _BudgetExhausted:
            # Out of budget: the best-ranked round found so far stands, unvetted
            # for the next round -- or, with none found, the fallback below runs.
            pass
        return first

    # A rematch-free round is always preferred. Only when the field has played
    # itself into a corner (or the search for a rematch-free round ran out of
    # budget) is one reused, and then the fewest the greedy pass can manage -- a
    # round where two teams sit idle is worse than a repeat. Each search gets
    # its own budget, so an exhausted first one still leaves the fallback room.
    chosen = _pick(allow_rematches=False) or _pick(allow_rematches=True)
    if chosen is None:
        raise SwissPairingImpossibleError("Unable to pair a Swiss round for this field")
    bye_candidate, pair_order = chosen

    pairings = [
        Pairing(
            team_ids=pair,
            round_number=round_number,
            name=f"Swiss R{round_number} Match {index}",
            local_id=index - 1,
        )
        for index, pair in enumerate(pair_order, start=1)
    ]

    return BracketSkeleton(
        pairings=pairings,
        total_rounds=1,
        bye_team_id=bye_candidate,
    )
