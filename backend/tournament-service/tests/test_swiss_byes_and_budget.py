"""Swiss bye bookkeeping per round and the search node budget.

Review items 17 (a bye is an event of one round, revocable with it) and 18
(the search cap bounds found options, not the work spent finding them).

Does not touch the database -- purely tests the pure-function shared library.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.services.bracket import swiss  # noqa: E402
from shared.services.bracket.swiss_settings import (  # noqa: E402
    record_swiss_bye,
    remove_swiss_bye_round,
    swiss_bye_counts,
    swiss_bye_team_ids,
)


class SwissByeRoundTests(TestCase):
    def test_recorded_bye_is_revoked_with_its_round(self) -> None:
        stage = SimpleNamespace(settings_json=None)

        record_swiss_bye(stage, 10, 7, round_number=3)
        record_swiss_bye(stage, 10, 9, round_number=4)

        self.assertEqual({7: 1, 9: 1}, swiss_bye_counts(stage, 10))

        remove_swiss_bye_round(stage, 10, 3)

        self.assertEqual({9: 1}, swiss_bye_counts(stage, 10))

    def test_legacy_bare_ids_still_count_and_survive_round_removal(self) -> None:
        stage = SimpleNamespace(settings_json={"swiss_byes": {"10": [5, 4]}})

        self.assertEqual({5: 1, 4: 1}, swiss_bye_counts(stage, 10))

        remove_swiss_bye_round(stage, 10, 3)

        self.assertEqual({5: 1, 4: 1}, swiss_bye_counts(stage, 10))

    def test_round_removal_keeps_other_scopes_and_legacy_entries(self) -> None:
        stage = SimpleNamespace(settings_json={"swiss_byes": {"10": [5], "20": [{"round": 3, "team_id": 8}]}})

        record_swiss_bye(stage, 10, 7, round_number=3)
        remove_swiss_bye_round(stage, 10, 3)

        self.assertEqual([5], swiss_bye_team_ids(stage, 10))
        self.assertEqual([8], swiss_bye_team_ids(stage, 20))


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
    def test_heavy_field_gives_up_instead_of_searching_forever(self) -> None:
        standings, played_pairs = _stress_field(26)

        started = time.perf_counter()
        with self.assertRaises(swiss.SwissPairingImpossibleError):
            swiss.generate_round(standings, played_pairs, round_number=5)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)

    def test_ordinary_round_is_unaffected_by_the_budget(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=1.0 if i <= 4 else 0.0) for i in range(1, 9)]
        played_pairs = {frozenset({1, 5}), frozenset({2, 6}), frozenset({3, 7}), frozenset({4, 8})}

        skeleton = swiss.generate_round(standings, played_pairs=played_pairs, round_number=2)

        self.assertIsNone(skeleton.bye_team_id)
        self.assertEqual(
            [(1, 3), (2, 4), (5, 7), (6, 8)],
            [(pairing.home_team_id, pairing.away_team_id) for pairing in skeleton.pairings],
        )
