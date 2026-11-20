"""Single-elimination bracket generator.

Generates pairings for a full single-elim bracket with:
- power-of-2 bracket sizes via first-round byes
- standard 1v16, 8v9, etc. seeding
- explicit advancement edges (position 1 of match X → slot Y of match Z)
- optional third place between the two real semifinal losers, in the title round

The generator populates ``local_id`` on every :class:`Pairing` and a list of
:class:`AdvancementEdge` on the :class:`BracketSkeleton`;
``persist_skeleton`` translates ``local_id`` → real ``Encounter.id``.
"""

from __future__ import annotations

import math

from .seeding_order import seeding_order
from .types import AdvancementEdge, BracketSkeleton, Pairing, append_third_place


def generate(team_ids: list[int], *, third_place_match: bool = False) -> BracketSkeleton:
    n = len(team_ids)
    if n < 2:
        return BracketSkeleton(pairings=[], total_rounds=0)

    bracket_size = 1 << math.ceil(math.log2(n))
    total_rounds = int(math.log2(bracket_size))
    seeds = seeding_order(bracket_size)

    seed_to_team: dict[int, int | None] = {}
    for i, tid in enumerate(team_ids):
        seed_to_team[i] = tid
    for i in range(n, bracket_size):
        seed_to_team[i] = None

    pairings: list[Pairing] = []
    edges: list[AdvancementEdge] = []

    # Round 1: decide which first-round positions are real matches vs byes.
    # For each pair (seed_a, seed_b):
    #   - both present → real match
    #   - exactly one present → no match, the present seed auto-advances
    #   - both absent → no team reaches R2 from this position (rare)
    #
    # In the resulting bracket we keep ONLY real matches in the pairings list,
    # but we remember which team (if any) auto-advances to each R2 slot so
    # advancement edges land correctly.
    r1_match_local_ids: list[int | None] = []
    # For each R1 position (bracket_size/2 positions), the team that enters R2
    # without a match. ``None`` means "waiting for the first place of r1_match_local_ids[pos]".
    r1_autoadvance_team: list[int | None] = []

    next_local_id = 0
    match_counter_per_round: dict[int, int] = {}

    def _round_match_label(round_num: int, match_idx: int) -> str:
        rounds_from_end = total_rounds - round_num
        if rounds_from_end == 0:
            return "Grand Final"
        if rounds_from_end == 1:
            return f"Semifinal {match_idx}"
        if rounds_from_end == 2:
            return f"Quarterfinal {match_idx}"
        return f"R{round_num} Match {match_idx}"

    # --- R1 ---
    for i in range(0, bracket_size, 2):
        first = seed_to_team[seeds[i]]
        second = seed_to_team[seeds[i + 1]]

        if first is not None and second is not None:
            match_counter_per_round[1] = match_counter_per_round.get(1, 0) + 1
            local_id = next_local_id
            next_local_id += 1
            pairings.append(
                Pairing(
                    team_ids=(first, second),
                    round_number=1,
                    name=_round_match_label(1, match_counter_per_round[1]),
                    local_id=local_id,
                )
            )
            r1_match_local_ids.append(local_id)
            r1_autoadvance_team.append(None)
        elif first is not None:
            r1_match_local_ids.append(None)
            r1_autoadvance_team.append(first)
        elif second is not None:
            r1_match_local_ids.append(None)
            r1_autoadvance_team.append(second)
        else:
            r1_match_local_ids.append(None)
            r1_autoadvance_team.append(None)

    # --- R2+ ---
    # previous_round_positions[i] = (match_local_id_if_real, autoadvance_team_if_not)
    # Initially this mirrors r1_match_local_ids / r1_autoadvance_team.
    prev_match_local_ids = list(r1_match_local_ids)
    prev_autoadvance = list(r1_autoadvance_team)

    for round_num in range(2, total_rounds + 1):
        slots = len(prev_match_local_ids) // 2
        new_match_local_ids: list[int | None] = []
        new_autoadvance: list[int | None] = []

        for idx in range(slots):
            a_local = prev_match_local_ids[idx * 2]
            a_team = prev_autoadvance[idx * 2]
            b_local = prev_match_local_ids[idx * 2 + 1]
            b_team = prev_autoadvance[idx * 2 + 1]

            a_present = a_local is not None or a_team is not None
            b_present = b_local is not None or b_team is not None

            if a_present and b_present:
                match_counter_per_round[round_num] = match_counter_per_round.get(round_num, 0) + 1
                local_id = next_local_id
                next_local_id += 1
                pairings.append(
                    Pairing(
                        team_ids=(a_team, b_team),
                        round_number=round_num,
                        name=_round_match_label(round_num, match_counter_per_round[round_num]),
                        local_id=local_id,
                    )
                )
                new_match_local_ids.append(local_id)
                new_autoadvance.append(None)

                for source_local_id, target_slot in ((a_local, 1), (b_local, 2)):
                    if source_local_id is None:
                        continue
                    edges.append(
                        AdvancementEdge(
                            source_local_id=source_local_id,
                            source_position=1,
                            target_local_id=local_id,
                            target_slot=target_slot,
                        )
                    )
            elif a_present:
                new_match_local_ids.append(a_local)
                new_autoadvance.append(a_team)
            elif b_present:
                new_match_local_ids.append(b_local)
                new_autoadvance.append(b_team)
            else:
                new_match_local_ids.append(None)
                new_autoadvance.append(None)

        prev_match_local_ids = new_match_local_ids
        prev_autoadvance = new_autoadvance

    if third_place_match:
        append_third_place(pairings, edges, double_elimination=False)

    return BracketSkeleton(
        pairings=pairings,
        total_rounds=total_rounds,
        advancement_edges=edges,
    )
