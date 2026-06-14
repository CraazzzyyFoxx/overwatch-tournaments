"""Deterministic draft pick-order generation (snake / linear).

Pure functions over scalar inputs so the ordering is fully reproducible from
the seed (team seed-order + round count) and trivially unit-testable without a
DB. ``team_index`` is the 0-based seat into the seed-ordered captain list.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.core.enums import DraftFormat


@dataclass(frozen=True)
class PickSlot:
    overall_no: int  # 1..(num_teams * rounds)
    round_no: int  # 1..rounds
    pick_in_round: int  # 1..num_teams
    team_index: int  # 0..num_teams-1 (seat in seed order)


def generate_pick_order(num_teams: int, rounds: int, fmt: DraftFormat) -> list[PickSlot]:
    """Return every pick slot in draft order.

    SNAKE: even rounds (1-indexed) reverse the team seat order (1->2->...->N,
    then N->...->2->1, ...). LINEAR: the same seat order every round.
    """
    if num_teams <= 0 or rounds <= 0:
        return []

    slots: list[PickSlot] = []
    for i in range(num_teams * rounds):
        round0 = i // num_teams  # 0-based round
        pos = i % num_teams  # 0-based position within the round
        reverse = fmt == DraftFormat.SNAKE and round0 % 2 == 1
        team_index = (num_teams - 1 - pos) if reverse else pos
        slots.append(
            PickSlot(
                overall_no=i + 1,
                round_no=round0 + 1,
                pick_in_round=pos + 1,
                team_index=team_index,
            )
        )
    return slots
