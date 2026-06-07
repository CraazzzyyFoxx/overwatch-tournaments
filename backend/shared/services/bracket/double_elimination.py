"""Double-elimination bracket generator.

Convention (matching the historical codebase):
  round > 0  → upper (winners) bracket
  round < 0  → lower (losers) bracket
  last positive round = Grand Final (and optional Grand Final Reset)

This implementation produces a correct bracket for power-of-two team counts
(2, 4, 8, 16, 32, 64). Non-power-of-two counts are handled by extending the
bracket to the next power of two and inserting first-round byes in the upper
bracket; byes do NOT produce LB dropouts.

Returns a :class:`BracketSkeleton` with complete advancement edges:
- Every UB match produces an edge (winner → next UB match).
- Every UB loser produces an edge to the appropriate LB match
  ("cross-drop" pattern: loser of UB R1 match k drops to LB R1, loser of
  UB R2 match k drops to LB R2, etc.).
- LB reduction rounds produce winner-edges to the next LB round.
- UB final and LB final both feed the Grand Final.

The Grand Final Reset is NOT materialised on generation — it must be created
on demand if the LB champion wins the first Grand Final. Skeleton includes a
stub Grand Final Reset pairing only if the caller explicitly sets
``include_reset=True``.
"""

from __future__ import annotations

import math

from .types import AdvancementEdge, BracketSkeleton, Pairing


def generate(
    team_ids: list[int],
    *,
    lower_bracket_team_ids: list[int] | None = None,
    include_reset: bool = False,
) -> BracketSkeleton:
    """Generate a double-elimination skeleton.

    ``team_ids`` seed the upper bracket. ``lower_bracket_team_ids`` (optional)
    are teams that *start* in the lower bracket: they play each other in LB
    Round 1, and the upper-bracket Round-1 losers join them in the next LB
    round ("group winners → Upper, runners-up → Lower"). This works cleanly
    when the upper and lower counts are equal (an even split).
    """
    n = len(team_ids)
    if n < 2:
        return BracketSkeleton(pairings=[], total_rounds=0)

    lb_seeds = list(lower_bracket_team_ids or [])

    bracket_size = 1 << math.ceil(math.log2(n))
    upper_rounds = int(math.log2(bracket_size))

    # UB seeding
    seeds = _seeding_order(bracket_size)
    seed_to_team: dict[int, int | None] = {}
    for i, tid in enumerate(team_ids):
        seed_to_team[i] = tid
    for i in range(n, bracket_size):
        seed_to_team[i] = None

    pairings: list[Pairing] = []
    edges: list[AdvancementEdge] = []
    next_local_id = 0

    # upper_matches[r][k] = local_id or None (None = bye-advance, no match)
    upper_matches: list[list[int | None]] = []

    # --- UB Round 1 ---
    r1: list[int | None] = []
    match_counter = 0
    for i in range(0, bracket_size, 2):
        home_seed = seeds[i]
        away_seed = seeds[i + 1]
        home = seed_to_team[home_seed]
        away = seed_to_team[away_seed]

        if home is not None and away is not None:
            match_counter += 1
            local_id = next_local_id
            next_local_id += 1
            pairings.append(
                Pairing(
                    home_team_id=home,
                    away_team_id=away,
                    round_number=1,
                    name=f"UB R1 Match {match_counter}",
                    local_id=local_id,
                )
            )
            r1.append(local_id)
        else:
            # Bye — no match in R1, the present team auto-advances to R2.
            r1.append(None)
    upper_matches.append(r1)

    # --- UB Round 2+ ---
    #   In round r, slot k's home team is the winner of upper_matches[r-1][2k]
    #   and away team is winner of upper_matches[r-1][2k+1]. If upper_matches[r-1]
    #   contains a None, the corresponding R1 autoadvance is wired in by
    #   tracking r1_autoadvance_team alongside (we don't need it for
    #   advancement edges, just for labels).
    for round_num in range(2, upper_rounds + 1):
        previous = upper_matches[-1]
        current: list[int | None] = []
        round_matches = len(previous) // 2
        round_match_counter = 0
        for k in range(round_matches):
            a_local = previous[2 * k]
            b_local = previous[2 * k + 1]

            round_match_counter += 1
            local_id = next_local_id
            next_local_id += 1
            pairings.append(
                Pairing(
                    home_team_id=None,
                    away_team_id=None,
                    round_number=round_num,
                    name=_ub_round_label(round_num, upper_rounds, round_match_counter),
                    local_id=local_id,
                )
            )
            current.append(local_id)

            if a_local is not None:
                edges.append(
                    AdvancementEdge(
                        source_local_id=a_local,
                        target_local_id=local_id,
                        role="winner",
                        target_slot="home",
                    )
                )
            if b_local is not None:
                edges.append(
                    AdvancementEdge(
                        source_local_id=b_local,
                        target_local_id=local_id,
                        role="winner",
                        target_slot="away",
                    )
                )
        upper_matches.append(current)

    # --- Lower Bracket ---
    # LB has (upper_rounds - 1) * 2 rounds total, structured as:
    #   phase p (0-indexed):
    #     - dropout round: size = |UB R(p+1)| , each match receives one LB
    #       carry-over (home) + one UB loser (away).
    #     - reduction round: size = |dropout round| / 2 OR same size
    #       (depending on phase pattern).
    #
    # For power-of-2 UB, standard LB structure:
    #   LB R1 (dropouts from UB R1): |UB R1| / 2 matches
    #   LB R2 (LB R1 winners vs UB R2 losers): |UB R2| matches
    #   LB R3 (LB R2 winners): |UB R2| / 2 matches
    #   LB R4 (LB R3 winners vs UB R3 losers): |UB R3| matches
    #   ... alternating carry-over + dropout until 1 match remains (LB Final).

    lb_rounds: list[list[int]] = []
    lb_round_index = 1

    if lb_seeds:
        # Teams seeded directly into the lower bracket play each other in LB R1.
        # The first dropout round (r=1) then merges their winners with the UB
        # Round-1 losers; UB R2+ losers drop in later rounds as usual.
        lb_r1: list[int] = []
        match_idx = 0
        i = 0
        while i < len(lb_seeds):
            match_idx += 1
            local_id = next_local_id
            next_local_id += 1
            pairings.append(
                Pairing(
                    home_team_id=lb_seeds[i],
                    away_team_id=lb_seeds[i + 1] if i + 1 < len(lb_seeds) else None,
                    round_number=-lb_round_index,
                    name=f"LB R{lb_round_index} Match {match_idx}",
                    local_id=local_id,
                )
            )
            lb_r1.append(local_id)
            i += 2
        lb_rounds.append(lb_r1)
        lb_round_index += 1
        ub_dropout_start = 1
    else:
        # Standard LB R1: for every PAIR of UB R1 matches, create one LB R1
        # match whose home=loser of the first UB R1 match, away=loser of the
        # second. Byes create phantom losers that are skipped.
        if upper_matches:
            ub_r1 = upper_matches[0]
            for pair_idx in range(0, len(ub_r1), 2):
                a_local = ub_r1[pair_idx]
                b_local = ub_r1[pair_idx + 1] if pair_idx + 1 < len(ub_r1) else None
                if a_local is None or b_local is None:
                    continue

                if not lb_rounds:
                    lb_rounds.append([])
                match_idx = len(lb_rounds[0]) + 1
                local_id = next_local_id
                next_local_id += 1
                pairings.append(
                    Pairing(
                        home_team_id=None,
                        away_team_id=None,
                        round_number=-lb_round_index,
                        name=f"LB R{lb_round_index} Match {match_idx}",
                        local_id=local_id,
                    )
                )
                lb_rounds[0].append(local_id)

                edges.append(
                    AdvancementEdge(
                        source_local_id=a_local,
                        target_local_id=local_id,
                        role="loser",
                        target_slot="home",
                    )
                )
                edges.append(
                    AdvancementEdge(
                        source_local_id=b_local,
                        target_local_id=local_id,
                        role="loser",
                        target_slot="away",
                    )
                )

        lb_round_index += 1
        ub_dropout_start = 2

    # Subsequent LB rounds
    # Pattern for UB round r:
    #   dropout round: size = |UB Rr|, each match has
    #     home = winner of corresponding LB carry round
    #     away = loser of UB Rr match k
    #   reduction round: size = |dropout round| / 2
    prev_lb = lb_rounds[0] if lb_rounds else []

    for r in range(ub_dropout_start, upper_rounds + 1):
        ub_round_matches = upper_matches[r - 1]

        # Dropout round — pair LB prev winners (by 2 if multiple) with UB losers.
        # For standard DE: |LB prev| == |UB Rr| (after first alignment).
        dropout_round: list[int] = []
        match_idx = 0
        for k, ub_match_local in enumerate(ub_round_matches):
            match_idx += 1
            local_id = next_local_id
            next_local_id += 1
            pairings.append(
                Pairing(
                    home_team_id=None,
                    away_team_id=None,
                    round_number=-lb_round_index,
                    name=f"LB R{lb_round_index} Match {match_idx}",
                    local_id=local_id,
                )
            )
            dropout_round.append(local_id)

            # LB carry: home = winner of prev_lb[k] (if exists)
            if k < len(prev_lb):
                edges.append(
                    AdvancementEdge(
                        source_local_id=prev_lb[k],
                        target_local_id=local_id,
                        role="winner",
                        target_slot="home",
                    )
                )
            # UB drop: away = loser of ub_match_local
            if ub_match_local is not None:
                edges.append(
                    AdvancementEdge(
                        source_local_id=ub_match_local,
                        target_local_id=local_id,
                        role="loser",
                        target_slot="away",
                    )
                )

        lb_rounds.append(dropout_round)
        lb_round_index += 1
        prev_lb = dropout_round

        # Reduction round: pair up winners of dropout round, halving.
        if len(prev_lb) > 1:
            reduction_round: list[int] = []
            match_idx = 0
            for pair_idx in range(0, len(prev_lb), 2):
                a_local = prev_lb[pair_idx]
                b_local = prev_lb[pair_idx + 1] if pair_idx + 1 < len(prev_lb) else None
                if b_local is None:
                    # Odd count — carry forward without a match
                    reduction_round.append(a_local)
                    continue

                match_idx += 1
                local_id = next_local_id
                next_local_id += 1
                pairings.append(
                    Pairing(
                        home_team_id=None,
                        away_team_id=None,
                        round_number=-lb_round_index,
                        name=f"LB R{lb_round_index} Match {match_idx}",
                        local_id=local_id,
                    )
                )
                reduction_round.append(local_id)

                edges.append(
                    AdvancementEdge(
                        source_local_id=a_local,
                        target_local_id=local_id,
                        role="winner",
                        target_slot="home",
                    )
                )
                edges.append(
                    AdvancementEdge(
                        source_local_id=b_local,
                        target_local_id=local_id,
                        role="winner",
                        target_slot="away",
                    )
                )

            lb_rounds.append(reduction_round)
            lb_round_index += 1
            prev_lb = reduction_round

    # --- Grand Final ---
    gf_round = upper_rounds + 1
    gf_local_id = next_local_id
    next_local_id += 1
    pairings.append(
        Pairing(
            home_team_id=None,
            away_team_id=None,
            round_number=gf_round,
            name="Grand Final",
            local_id=gf_local_id,
        )
    )
    # UB final winner → GF home
    if upper_matches and upper_matches[-1]:
        ub_final_local = upper_matches[-1][0]
        if ub_final_local is not None:
            edges.append(
                AdvancementEdge(
                    source_local_id=ub_final_local,
                    target_local_id=gf_local_id,
                    role="winner",
                    target_slot="home",
                )
            )
    # LB final winner → GF away
    if prev_lb:
        lb_final_local = prev_lb[-1]
        edges.append(
            AdvancementEdge(
                source_local_id=lb_final_local,
                target_local_id=gf_local_id,
                role="winner",
                target_slot="away",
            )
        )

    # Grand Final Reset — only if explicitly requested. Engine consumers are
    # expected to materialise it on demand when LB champion wins GF #1.
    if include_reset:
        reset_local_id = next_local_id
        next_local_id += 1
        pairings.append(
            Pairing(
                home_team_id=None,
                away_team_id=None,
                round_number=gf_round + 1,
                name="Grand Final Reset",
                local_id=reset_local_id,
            )
        )
        # Reset is fed by the winner of GF if that winner is the LB champion;
        # this rule can't be expressed as a pure winner/loser edge so we leave
        # it to consumer logic.

    total_rounds = gf_round + (1 if include_reset else 0)
    return BracketSkeleton(
        pairings=pairings, total_rounds=total_rounds, advancement_edges=edges
    )


def _ub_round_label(round_num: int, upper_rounds: int, match_idx: int) -> str:
    if round_num == upper_rounds:
        return "UB Final"
    if round_num == upper_rounds - 1:
        return f"UB Semifinal {match_idx}"
    return f"UB R{round_num} Match {match_idx}"


def _seeding_order(size: int) -> list[int]:
    if size == 1:
        return [0]
    half = _seeding_order(size // 2)
    result: list[int] = []
    for seed in half:
        result.append(seed)
        result.append(size - 1 - seed)
    return result
