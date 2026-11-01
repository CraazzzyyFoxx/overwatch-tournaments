"""Which of a source's matches a mix round played: every team's linked members, at least half of each, on distinct
sides (a private profile hides a player) and none of them on another side (the same players split otherwise, even by
one swap, are another round)."""

from __future__ import annotations

from shared.disciplines.ingest import MatchCandidate
from src.services.ingest.search import fitting

# Two teams of three linked members; "a3" has two Steam accounts.
ROUND = [
    [frozenset({"a1"}), frozenset({"a2"}), frozenset({"a3", "a3-alt"})],
    [frozenset({"b1"}), frozenset({"b2"}), frozenset({"b3"})],
]


def match(external_id: str, *sides: set[str]) -> MatchCandidate:
    return MatchCandidate(external_id=external_id, teams=tuple(frozenset(side) for side in sides))


def test_the_round_fits_on_either_side_and_with_private_profiles_up_to_half() -> None:
    candidates = [
        match("swapped", {"b1", "b2", "b3"}, {"a1", "a2", "a3-alt"}),
        # One of each team hidden (account 0 dropped by the source): two of three is still at least half.
        match("half", {"a1", "a3"}, {"b2", "b3"}),
    ]

    assert fitting(ROUND, candidates) == ["swapped", "half"]


def test_the_same_players_split_otherwise_or_too_few_of_a_team_is_not_the_round() -> None:
    candidates = [
        # One swap from the round: the next round of the same ten, say.
        match("one_swap", {"a1", "a2", "b1"}, {"a3", "b2", "b3"}),
        match("one_of_three", {"a1"}, {"b1", "b2", "b3"}),
        match("one_side", {"a1", "a2", "a3", "b1", "b2", "b3"}),
    ]

    assert fitting(ROUND, candidates) == []
