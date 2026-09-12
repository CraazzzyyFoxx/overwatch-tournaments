"""Double-elimination bracket generator.

Convention (matching the historical codebase):
  round > 0  → upper (winners) bracket
  round < 0  → lower (losers) bracket
  last positive round = Grand Final (and optional Grand Final Reset)

Non-power-of-two team counts extend the bracket to the next power of two and
leave the surplus positions empty. Everything is expressed in terms of a slot's
*origin* — a known team, or the winner/loser of a match that has not been
played yet — and a match only exists where two origins actually meet. A slot
with a single origin has nobody to play: that origin advances untouched (a
bye), in the upper bracket and in the lower bracket alike. That is what keeps
an 6- or 12-team bracket from stranding the top seeds in a half-empty match
they can never play.

Returns a :class:`BracketSkeleton` with complete advancement edges:
- Every UB match produces an edge (winner → next UB match).
- Every UB loser produces an edge to the appropriate LB match
  (cross-drop: dropouts are reversed so a loser does not immediately
  rematch the opponent that just beat them) — or, when the LB slot it
  would have played in is empty, to the first LB match that has an opponent.
- LB reduction rounds produce winner-edges to the next LB round.
- UB final and LB final both feed the Grand Final.

The Grand Final Reset is NOT materialised on generation — it must be created
on demand if the LB champion wins the first Grand Final. Skeleton includes a
stub Grand Final Reset pairing only if the caller explicitly sets
``include_reset=True``.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from .seeding_order import seeding_order
from .types import AdvancementEdge, BracketSkeleton, Pairing

# Origin kinds. WINNER/LOSER carry a pairing's ``local_id``; TEAM carries a
# team id. WINNER/LOSER double as ``AdvancementEdge.role`` values.
_TEAM = "team"
_WINNER = "winner"
_LOSER = "loser"

# Where the team occupying a bracket slot comes from: ``(kind, value)``.
Origin = tuple[str, int]


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

    pairings: list[Pairing] = []
    edges: list[AdvancementEdge] = []
    next_local_id = 0

    def play(
        home: Origin | None,
        away: Origin | None,
        round_number: int,
        label: Callable[[int], str],
        *,
        match_index: int,
        force: bool = False,
    ) -> tuple[Origin | None, Origin | None]:
        """Materialise the match between two slot origins.

        Returns ``(winner_origin, loser_origin)``: what the slot passes on, and
        what drops to the lower bracket. With only one origin present there is
        no match to play — it advances as a bye and produces no loser.
        ``force`` keeps a pairing that has to exist regardless (the Grand
        Final) even when one side is still unreachable.
        """
        nonlocal next_local_id
        if (home is None or away is None) and not force:
            return (home or away), None

        local_id = next_local_id
        next_local_id += 1
        pairings.append(
            Pairing(
                home_team_id=home[1] if home is not None and home[0] == _TEAM else None,
                away_team_id=away[1] if away is not None and away[0] == _TEAM else None,
                round_number=round_number,
                name=label(match_index),
                local_id=local_id,
            )
        )
        for origin, slot in ((home, "home"), (away, "away")):
            if origin is None or origin[0] == _TEAM:
                continue
            edges.append(
                AdvancementEdge(
                    source_local_id=origin[1],
                    target_local_id=local_id,
                    role=origin[0],
                    target_slot=slot,
                )
            )
        return (_WINNER, local_id), (_LOSER, local_id)

    def pair_up(
        origins: list[Origin | None],
        round_number: int,
        label: Callable[[int], str],
    ) -> tuple[list[Origin | None], list[Origin | None]]:
        """Play every adjacent pair of ``origins``, halving the field.

        ``label`` numbers only the matches that actually exist, so a bracket
        with byes still reads "Match 1, Match 2, …".
        """
        winners: list[Origin | None] = []
        losers: list[Origin | None] = []
        match_index = 0
        for index in range(0, len(origins), 2):
            home = origins[index]
            away = origins[index + 1] if index + 1 < len(origins) else None
            if home is not None and away is not None:
                match_index += 1
            winner, loser = play(home, away, round_number, label, match_index=match_index)
            winners.append(winner)
            losers.append(loser)
        return winners, losers

    # ── Upper bracket ───────────────────────────────────────────────────────
    seeds = seeding_order(bracket_size)
    slots: list[Origin | None] = [(_TEAM, team_ids[seed]) if seed < n else None for seed in seeds]

    # ``ub_losers[r - 1][k]`` — what drops out of slot k of UB round r, or None
    # when that slot was a bye.
    ub_losers: list[list[Origin | None]] = []
    for round_num in range(1, upper_rounds + 1):
        slots, losers = pair_up(slots, round_num, _ub_label(round_num, upper_rounds))
        ub_losers.append(losers)

    # ── Lower bracket ───────────────────────────────────────────────────────
    lb_round = 1
    if lb_seeds:
        # Teams seeded straight into the lower bracket meet each other first;
        # the upper bracket's Round-1 losers join them in the next round.
        carry, _ = pair_up([(_TEAM, tid) for tid in lb_seeds], -lb_round, _lb_label(lb_round))
        dropout_start = 1
    else:
        # LB Round 1 pairs the upper bracket's Round-1 losers two by two.
        carry, _ = pair_up(ub_losers[0], -lb_round, _lb_label(lb_round))
        dropout_start = 2
    lb_round += 1

    for round_num in range(dropout_start, upper_rounds + 1):
        # Cross-drop: reverse so the loser of UB match k does not immediately
        # play the loser of the UB match that received k's winner.
        dropouts = list(reversed(ub_losers[round_num - 1]))
        label = _lb_label(lb_round)
        dropout_round: list[Origin | None] = []
        match_index = 0
        for k, dropout in enumerate(dropouts):
            home = carry[k] if k < len(carry) else None
            if home is not None and dropout is not None:
                match_index += 1
            winner, _ = play(home, dropout, -lb_round, label, match_index=match_index)
            dropout_round.append(winner)
        carry = dropout_round
        lb_round += 1

        # Reduction round: halve the survivors.
        if len(carry) > 1:
            carry, _ = pair_up(carry, -lb_round, _lb_label(lb_round))
            lb_round += 1

    # ── Grand Final ─────────────────────────────────────────────────────────
    gf_round = upper_rounds + 1
    play(
        slots[0] if slots else None,
        carry[-1] if carry else None,
        gf_round,
        lambda _: "Grand Final",
        match_index=1,
        force=True,
    )

    # Grand Final Reset — only if explicitly requested. Engine consumers are
    # expected to materialise it on demand when LB champion wins GF #1.
    if include_reset:
        pairings.append(
            Pairing(
                home_team_id=None,
                away_team_id=None,
                round_number=gf_round + 1,
                name="Grand Final Reset",
                local_id=next_local_id,
            )
        )
        next_local_id += 1
        # Reset is fed by the winner of GF if that winner is the LB champion;
        # this rule can't be expressed as a pure winner/loser edge so we leave
        # it to consumer logic.

    total_rounds = gf_round + (1 if include_reset else 0)
    return BracketSkeleton(pairings=pairings, total_rounds=total_rounds, advancement_edges=edges)


def _ub_label(round_num: int, upper_rounds: int) -> Callable[[int], str]:
    if round_num == 1:
        return lambda match_idx: f"UB R1 Match {match_idx}"
    return lambda match_idx: _ub_round_label(round_num, upper_rounds, match_idx)


def _lb_label(round_num: int) -> Callable[[int], str]:
    return lambda match_idx: f"LB R{round_num} Match {match_idx}"


def _ub_round_label(round_num: int, upper_rounds: int, match_idx: int) -> str:
    if round_num == upper_rounds:
        return "UB Final"
    if round_num == upper_rounds - 1:
        return f"UB Semifinal {match_idx}"
    return f"UB R{round_num} Match {match_idx}"
