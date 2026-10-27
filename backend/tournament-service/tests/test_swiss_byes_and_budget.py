"""The Swiss search budget.

The search cap bounds found options; the node and time budget bound the work
spent finding them -- and running out of it falls back to a round with
rematches instead of ending the scope.

Does not touch the database: ``src.domain.bracket`` is pure.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from src.domain.bracket import swiss  # noqa: E402


def _stress_field(team_count: int) -> tuple[list[swiss.SwissStanding], set[frozenset[int]]]:
    """A field that has played itself into a corner, the review's heavy case.

    Every team sits in its own score group, the lowest-ranked one has already
    met everyone, and neighbours have met too -- so no rematch-free round
    exists, and a naive search only learns that after enumerating the whole
    matching tree of the remaining teams.
    """
    standings = [swiss.SwissStanding(team_id=i, points=float(team_count - i)) for i in range(1, team_count + 1)]
    played = {frozenset({team_count, other}) for other in range(1, team_count)}
    played |= {frozenset({i, i + 1}) for i in range(1, team_count - 1)}
    return standings, played


class SwissSearchBudgetTests(TestCase):
    def test_heavy_field_falls_back_to_a_full_round_within_a_second(self) -> None:
        """Running out of budget used to skip the rematch fallback and stop the
        scope; a 30-team field burned 1.2 s of event loop doing it."""
        standings, played_pairs = _stress_field(30)

        started = time.perf_counter()
        skeleton = swiss.generate_round(standings, played_pairs, round_number=5)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)
        self.assertIsNone(skeleton.bye_team_id)
        seated = [team_id for pairing in skeleton.pairings for team_id in pairing.team_ids]
        self.assertEqual(sorted(seated), list(range(1, 31)))

    def test_a_rematch_free_round_found_before_the_budget_ran_out_stands(self) -> None:
        """The lookahead may run out of budget; the best rematch-free round found by then is still used."""
        standings = [swiss.SwissStanding(team_id=i, points=1.0 if i <= 4 else 0.0) for i in range(1, 9)]
        played_pairs = {frozenset({1, 5}), frozenset({2, 6}), frozenset({3, 7}), frozenset({4, 8})}

        with patch.object(swiss, "_keeps_next_round_pairable", side_effect=swiss._BudgetExhausted):
            skeleton = swiss.generate_round(standings, played_pairs=played_pairs, round_number=2)

        self.assertEqual(
            [(1, 3), (2, 4), (5, 7), (6, 8)],
            [tuple(pairing.team_ids) for pairing in skeleton.pairings],
        )

    def test_ordinary_round_is_unaffected_by_the_budget(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=1.0 if i <= 4 else 0.0) for i in range(1, 9)]
        played_pairs = {frozenset({1, 5}), frozenset({2, 6}), frozenset({3, 7}), frozenset({4, 8})}

        skeleton = swiss.generate_round(standings, played_pairs=played_pairs, round_number=2)

        self.assertIsNone(skeleton.bye_team_id)
        self.assertEqual(
            [(1, 3), (2, 4), (5, 7), (6, 8)],
            # ``team_ids[i]`` is slot ``i + 1``; there is no home or away.
            [tuple(pairing.team_ids) for pairing in skeleton.pairings],
        )
