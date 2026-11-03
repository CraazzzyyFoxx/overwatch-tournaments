"""Which Swiss round slot each member sits in.

A round slot is a voice channel reused every round. Slot ``2 * lobby + side`` is the lobby's side A (0) or B (1),
so the slot index is ``< teams_per_round``. A round lays its encounters onto lobbies and their seats onto sides so
that as many members as possible stay where they were last round.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ("Encounter", "assign_round_slots")

#: One encounter of a round: the member ids seated on side A (slot 1) and on side B (slot 2).
Encounter = tuple[Sequence[int], Sequence[int]]
Assignment = dict[int, int]


def _place(assignment: Assignment, lobby: int, encounter: Encounter, *, flipped: bool) -> None:
    sides = (encounter[1], encounter[0]) if flipped else encounter
    for side, members in enumerate(sides):
        for member in members:
            assignment[member] = 2 * lobby + side


def _stayers(assignment: Assignment, previous: Assignment) -> int:
    return sum(1 for member, slot in assignment.items() if previous.get(member) == slot)


def _bracket_order(encounters: Sequence[Encounter]) -> Assignment:
    assignment: Assignment = {}
    for lobby, encounter in enumerate(encounters):
        _place(assignment, lobby, encounter, flipped=False)
    return assignment


def _keeping(encounters: Sequence[Encounter], previous: Assignment) -> Assignment:
    """Greedy: the best-scoring (encounter, lobby) pair first, each with its better orientation."""
    candidates: list[tuple[int, int, int, bool]] = []
    for index, (home, away) in enumerate(encounters):
        for lobby in range(len(encounters)):
            straight = sum(previous.get(m) == 2 * lobby for m in home) + sum(
                previous.get(m) == 2 * lobby + 1 for m in away
            )
            flipped = sum(previous.get(m) == 2 * lobby + 1 for m in home) + sum(
                previous.get(m) == 2 * lobby for m in away
            )
            candidates.append((-max(straight, flipped), index, lobby, flipped > straight))
    assignment: Assignment = {}
    placed: set[int] = set()
    taken: set[int] = set()
    for _score, index, lobby, flipped in sorted(candidates):
        if index in placed or lobby in taken:
            continue
        placed.add(index)
        taken.add(lobby)
        _place(assignment, lobby, encounters[index], flipped=flipped)
    return assignment


def assign_round_slots(rounds: Sequence[Sequence[Encounter]]) -> list[Assignment]:
    """``{member_id: slot_index}`` for every round, from round 1 on.

    Round 1 is the bracket order (encounter ``i`` on lobby ``i``, home on A, away on B). A later round keeps the
    better of the plain bracket order and the greedy placement, measured in members who keep last round's slot,
    so it is never worse than the bracket order. Deterministic: ties fall to the bracket order.
    """
    result: list[Assignment] = []
    previous: Assignment = {}
    for encounters in rounds:
        plain = _bracket_order(encounters)
        current = plain
        if result:
            keeping = _keeping(encounters, previous)
            if _stayers(keeping, previous) > _stayers(plain, previous):
                current = keeping
        result.append(current)
        previous = current
    return result
