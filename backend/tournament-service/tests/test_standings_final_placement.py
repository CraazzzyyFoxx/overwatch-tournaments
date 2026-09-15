"""Review item 11: the final is the bracket's last round, not the last played one.

Pure functions only — no database.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from src import models  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.standings import service  # noqa: E402


def _encounter(
    *,
    id: int,
    home_team_id: int,
    away_team_id: int,
    round: int,
    home_score: int = 0,
    away_score: int = 0,
    completed: bool = True,
) -> models.Encounter:
    return models.Encounter(
        id=id,
        created_at=datetime.now(UTC),
        updated_at=None,
        name=f"Match {id}",
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        round=round,
        best_of=3,
        tournament_id=64,
        stage_id=10,
        stage_item_id=None,
        closeness=None,
        has_logs=False,
        status=enums.EncounterStatus.COMPLETED if completed else enums.EncounterStatus.OPEN,
        result_status=enums.EncounterResultStatus.NONE,
    )


def _placements(rows: list) -> dict[int, int]:
    return {row.id: int(row.ranking) for row in rows}


class SingleEliminationFinalPlacementTest(TestCase):
    """4 teams, semis in round 1, final in round 2."""

    def _bracket(self, *, final_completed: bool) -> list[models.Encounter]:
        return [
            _encounter(id=1, home_team_id=1, away_team_id=4, round=1, home_score=2, away_score=0),
            _encounter(id=2, home_team_id=2, away_team_id=3, round=1, home_score=2, away_score=1),
            _encounter(
                id=3,
                home_team_id=1,
                away_team_id=2,
                round=2,
                home_score=2 if final_completed else 0,
                away_score=1 if final_completed else 0,
                completed=final_completed,
            ),
        ]

    def test_open_final_awards_no_first_or_second(self) -> None:
        placements = _placements(
            service.prepare_teams_for_playoffs_single_elimination(self._bracket(final_completed=False))
        )

        # Pre-fix the max *completed* positive round was the semi-final round,
        # so both semi winners were 1st and both losers 2nd.
        self.assertNotIn(1, placements.values())
        self.assertNotIn(2, placements.values())
        self.assertEqual(placements[1], 0)
        self.assertEqual(placements[2], 0)
        self.assertEqual(placements[3], 3)
        self.assertEqual(placements[4], 3)

    def test_completed_final_awards_exactly_one_first_and_second(self) -> None:
        placements = _placements(
            service.prepare_teams_for_playoffs_single_elimination(self._bracket(final_completed=True))
        )

        self.assertEqual(sorted(placements.values()).count(1), 1)
        self.assertEqual(sorted(placements.values()).count(2), 1)
        self.assertEqual(placements[1], 1)
        self.assertEqual(placements[2], 2)


class DoubleEliminationResetPlacementTest(TestCase):
    """Once a Grand Final Reset exists it, not the Grand Final, is the decider."""

    def _bracket(self, *, reset_completed: bool) -> list[models.Encounter]:
        return [
            # Upper bracket final.
            _encounter(id=1, home_team_id=1, away_team_id=2, round=1, home_score=2, away_score=0),
            # Lower bracket final.
            _encounter(id=2, home_team_id=3, away_team_id=4, round=-1, home_score=2, away_score=1),
            # Grand Final: the lower bracket champion won, so a reset is due.
            _encounter(id=3, home_team_id=1, away_team_id=3, round=2, home_score=1, away_score=2),
            _encounter(
                id=4,
                home_team_id=1,
                away_team_id=3,
                round=3,
                home_score=2 if reset_completed else 0,
                away_score=1 if reset_completed else 0,
                completed=reset_completed,
            ),
        ]

    def test_open_reset_awards_no_first_or_second(self) -> None:
        placements = _placements(
            service.prepare_teams_for_playoffs_double_elimination(self._bracket(reset_completed=False))
        )

        # Pre-fix the Grand Final was the max completed positive round and
        # crowned team 3 while the reset was still to be played.
        self.assertNotIn(1, placements.values())
        self.assertNotIn(2, placements.values())

    def test_completed_reset_decides_the_champion(self) -> None:
        placements = _placements(
            service.prepare_teams_for_playoffs_double_elimination(self._bracket(reset_completed=True))
        )

        self.assertEqual(placements[1], 1)
        self.assertEqual(placements[3], 2)
