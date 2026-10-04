"""Stage completion in achievement nodes: ``stage_completed`` and the bracket filters.

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_scrim_achievement_isolation as _scrim  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    _EngineTestCase,
)

from shared.core import enums  # noqa: E402

evaluator = _scrim.evaluator
models = _scrim.models
sa = _scrim.sa

HOME_KEY = (REAL_HOME_USER, REAL_TOURNAMENT_ID)


class _StageCase(_EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.teams = self.db.rostered_tournament(REAL_TOURNAMENT_ID)

    def stage(self, stage_type: enums.StageType, *, order: int, completed: bool) -> int:
        stage_id = self.db._id()
        self.db.insert(
            models.Stage.__table__,
            id=stage_id,
            tournament_id=REAL_TOURNAMENT_ID,
            name=f"stage {order}",
            stage_type=stage_type,
            order=order,
            max_rounds=1,
            is_completed=completed,
        )
        return stage_id

    def complete(self, stage_id: int) -> None:
        self.db.session.execute(
            sa.update(models.Stage.__table__).where(models.Stage.__table__.c.id == stage_id).values(is_completed=True)
        )
        self.db.session.commit()

    async def node(self, node_type: str, params: dict) -> set:
        tree = {"type": node_type, "params": params}
        return await evaluator.evaluate(self.db.shim, tree, await self.context(REAL_TOURNAMENT_ID))


class StageCompletedNodeTests(_StageCase):
    async def test_number_is_position_in_stage_order_not_the_raw_order_value(self) -> None:
        self.stage(enums.StageType.ROUND_ROBIN, order=5, completed=True)
        self.stage(enums.StageType.SINGLE_ELIMINATION, order=10, completed=False)
        self.db.session.commit()

        self.assertEqual(
            {HOME_KEY, (REAL_AWAY_USER, REAL_TOURNAMENT_ID)},
            await self.node("stage_completed", {"op": "<=", "value": 1}),
        )
        self.assertEqual(set(), await self.node("stage_completed", {"value": 2}))
        self.assertEqual(set(), await self.node("stage_completed", {"op": ">=", "value": 1}))
        # No stage 3 exists: that is not a finished stage 3.
        self.assertEqual(set(), await self.node("stage_completed", {"value": 3}))

    async def test_stageless_tournament_falls_back_to_is_finished(self) -> None:
        self.db.session.commit()
        self.assertEqual(set(), await self.node("stage_completed", {"value": 1}))

        self.db.session.execute(
            sa.update(models.Tournament.__table__)
            .where(models.Tournament.__table__.c.id == REAL_TOURNAMENT_ID)
            .values(is_finished=True)
        )
        self.db.session.commit()
        self.assertIn(HOME_KEY, await self.node("stage_completed", {"value": 1}))


class BracketNodesWaitForStageCompletionTests(_StageCase):
    async def test_standing_position_waits_for_its_stage(self) -> None:
        playoff = self.stage(enums.StageType.SINGLE_ELIMINATION, order=0, completed=False)
        self.db.insert(
            models.Standing.__table__,
            id=self.db._id(),
            tournament_id=REAL_TOURNAMENT_ID,
            stage_id=playoff,
            team_id=self.teams["home"],
            position=1,
            overall_position=1,
            matches=1,
            win=1,
            draw=0,
            lose=0,
            points=1.0,
        )
        self.db.session.commit()
        params = {"op": "==", "value": 1}

        self.assertEqual(set(), await self.node("standing_position", params))
        self.complete(playoff)
        self.assertEqual({HOME_KEY}, await self.node("standing_position", params))

    async def test_final_scoreline_waits_for_the_final_stage(self) -> None:
        playoff = self.stage(enums.StageType.SINGLE_ELIMINATION, order=0, completed=False)
        self.db.encounter(REAL_TOURNAMENT_ID, self.teams["home"], self.teams["away"], stage_id=playoff)
        self.db.session.commit()
        params = {"scores": [[2, 1]], "round_type": "final"}

        self.assertEqual(set(), await self.node("encounter_score", params))
        self.complete(playoff)
        self.assertEqual({HOME_KEY}, await self.node("encounter_score", params))
