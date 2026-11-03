"""``assign_round_slots``: which round slot every member of an individual Swiss round sits in."""

from __future__ import annotations

import random
from unittest import TestCase

from src.domain.voice import assign_round_slots


def _stayers(round_slots: dict[int, int], previous: dict[int, int]) -> int:
    return sum(1 for member, slot in round_slots.items() if previous.get(member) == slot)


def _bracket_order(encounters) -> dict[int, int]:
    return {
        member: 2 * lobby + side
        for lobby, sides in enumerate(encounters)
        for side, members in enumerate(sides)
        for member in members
    }


class AssignRoundSlotsTests(TestCase):
    def test_round_one_is_the_bracket_order(self) -> None:
        rounds = [[([1, 2], [3, 4]), ([5], [6])]]
        self.assertEqual([{1: 0, 2: 0, 3: 1, 4: 1, 5: 2, 6: 3}], assign_round_slots(rounds))

    def test_a_later_round_keeps_people_in_their_slot(self) -> None:
        round_one = [([1, 2], [3, 4]), ([5], [6])]
        # Bracket order would move everyone but 6; laying the encounters onto the lobbies they came from keeps 1, 2, 6.
        round_two = [([5], [1, 2]), ([3, 4], [6])]
        first, second = assign_round_slots([round_one, round_two])
        self.assertEqual(1, _stayers(_bracket_order(round_two), first))
        self.assertEqual({1: 0, 2: 0, 5: 1, 6: 3, 3: 2, 4: 2}, second)

    def test_never_worse_than_the_bracket_order_and_deterministic(self) -> None:
        rng = random.Random(7)
        for _ in range(200):
            lobbies = rng.randint(1, 6)
            members = list(range(1, 2 * lobbies * 2 + 1))
            rounds = []
            for _round in range(4):
                rng.shuffle(members)
                seats = [members[i : i + 2] for i in range(0, len(members), 2)]
                rounds.append([(seats[2 * i], seats[2 * i + 1]) for i in range(lobbies)])
            result = assign_round_slots(rounds)
            self.assertEqual(result, assign_round_slots(rounds))
            for index in range(1, len(rounds)):
                self.assertGreaterEqual(
                    _stayers(result[index], result[index - 1]),
                    _stayers(_bracket_order(rounds[index]), result[index - 1]),
                )
            for round_slots, encounters in zip(result, rounds, strict=True):
                # A slot holds one team's members: every seat lands on one slot, and no two seats share one.
                self.assertEqual(len(encounters) * 2, len(set(round_slots.values())))
