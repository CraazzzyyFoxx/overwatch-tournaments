"""Review items 12 and 13: the overall table honours the stage's own ranking
and ranks teams, not participation rows.

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


def _stage(*, id: int, order: int) -> models.Stage:
    return models.Stage(
        id=id,
        created_at=datetime.now(UTC),
        updated_at=None,
        tournament_id=64,
        name=f"Group {id}",
        description=None,
        stage_type=enums.StageType.ROUND_ROBIN,
        max_rounds=5,
        order=order,
        is_active=True,
        is_completed=False,
        settings_json=None,
    )


def _standing(
    *,
    id: int,
    team_id: int,
    stage: models.Stage,
    position: int,
    points: float = 2.0,
    tb: float | None = None,
) -> models.Standing:
    return models.Standing(
        id=id,
        created_at=datetime.now(UTC),
        updated_at=None,
        tournament_id=64,
        team_id=team_id,
        stage_id=stage.id,
        stage_item_id=None,
        position=position,
        overall_position=0,
        matches=3,
        win=2,
        draw=0,
        lose=1,
        points=points,
        buchholz=None,
        full_buchholz=None,
        tie_group=None,
        tb=tb,
        score_differential=None,
        stage=stage,
    )


class OverallOrderFollowsStagePositionTest(TestCase):
    def test_stage_position_beats_raw_tiebreak_metrics(self) -> None:
        stage = _stage(id=10, order=0)
        # The stage already applied the configured tiebreak order: team 1 is
        # first even though team 2 has the better head-to-head value.
        first = _standing(id=1, team_id=1, stage=stage, position=1, tb=0.0)
        second = _standing(id=2, team_id=2, stage=stage, position=2, tb=5.0)

        service.calculate_overall_positions([first, second], [stage])

        # Pre-fix the overall sort re-ranked by tb and put team 2 first.
        self.assertEqual(first.overall_position, 1)
        self.assertEqual(second.overall_position, 2)


class OverallRanksTeamsNotRowsTest(TestCase):
    def test_team_with_two_group_stages_takes_one_place(self) -> None:
        group = _stage(id=10, order=0)
        playoff_group = _stage(id=11, order=1)
        a_early = _standing(id=1, team_id=1, stage=group, position=1)
        a_late = _standing(id=2, team_id=1, stage=playoff_group, position=1)
        b_only = _standing(id=3, team_id=2, stage=group, position=2)

        service.calculate_overall_positions([a_early, a_late, b_only], [group, playoff_group])

        # Pre-fix team 1 occupied two of the three places.
        a_positions = [row.overall_position for row in (a_early, a_late) if row.overall_position > 0]
        self.assertEqual(len(a_positions), 1)
        self.assertGreater(b_only.overall_position, 0)
        # The kept row is the one from the latest stage.
        self.assertEqual(a_late.overall_position, 1)
        self.assertEqual(a_early.overall_position, 0)
        # No place is skipped: two teams, places 1 and 2.
        self.assertEqual(sorted(a_positions + [b_only.overall_position]), [1, 2])
