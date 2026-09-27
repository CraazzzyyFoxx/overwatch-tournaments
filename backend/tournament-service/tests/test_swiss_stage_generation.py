from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

enums = importlib.import_module("shared.core.enums")
swiss = importlib.import_module("shared.services.bracket.swiss")
types = importlib.import_module("shared.services.bracket.types")
stage_service = importlib.import_module("src.services.admin.stage")


class SwissStageGenerationTests(IsolatedAsyncioTestCase):
    """The Swiss bookkeeping the generator writes through ``swiss_state``.

    Those functions each take the session and hit their own tables, so what is
    pinned here is the call the generator makes for the scope it generated.
    """

    def setUp(self) -> None:
        self.session = SimpleNamespace()
        self.stage = SimpleNamespace(id=77, stage_type=enums.StageType.SWISS, max_rounds=5)
        self.recorded = AsyncMock()
        self.stopped = AsyncMock()
        self.cleared = AsyncMock()
        patches = (
            patch.object(stage_service, "record_swiss_bye", self.recorded),
            patch.object(stage_service, "mark_swiss_scope_stopped", self.stopped),
            patch.object(stage_service, "clear_swiss_scope_stopped", self.cleared),
            patch.object(stage_service, "clear_swiss_byes", AsyncMock()),
            patch.object(stage_service, "swiss_bye_team_ids", AsyncMock(return_value=[])),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_generation_records_bye_for_scope(self) -> None:
        skeleton = types.BracketSkeleton(
            pairings=[types.Pairing(home_team_id=1, away_team_id=2, round_number=2)],
            total_rounds=1,
            bye_team_id=3,
        )

        with (
            patch.object(
                stage_service.stage_service,
                "_get_swiss_generation_context",
                AsyncMock(return_value=([swiss.SwissStanding(1, 1.0)], set(), 2)),
            ),
            patch.object(stage_service, "generate_bracket", return_value=skeleton),
        ):
            result = await stage_service.stage_service._generate_stage_skeleton(
                self.session,
                self.stage,
                [1, 2, 3],
                501,
            )

        self.assertIs(result, skeleton)
        self.recorded.assert_awaited_once_with(self.session, 77, 501, 3, round_number=2)
        self.stopped.assert_not_awaited()

    async def test_impossible_pairing_marks_scope_stopped(self) -> None:
        with (
            patch.object(
                stage_service.stage_service,
                "_get_swiss_generation_context",
                AsyncMock(return_value=([swiss.SwissStanding(1, 1.0)], set(), 2)),
            ),
            patch.object(
                stage_service,
                "generate_bracket",
                side_effect=swiss.SwissPairingImpossibleError,
            ),
        ):
            result = await stage_service.stage_service._generate_stage_skeleton(
                self.session,
                self.stage,
                [1, 2],
                501,
            )

        self.assertEqual([], result.pairings)
        self.stopped.assert_awaited_once_with(self.session, 77, 501)
        self.recorded.assert_not_awaited()

    async def test_full_circle_swiss_is_generated_as_a_round_robin(self) -> None:
        """max_rounds >= teams - 1 means every team meets every other, so the
        whole schedule is built at once instead of one paired round at a time —
        round-by-round pairing can corner itself into an unplayable round."""
        with patch.object(
            stage_service.stage_service,
            "_get_swiss_generation_context",
            AsyncMock(return_value=(None, None, 1)),
        ):
            result = await stage_service.stage_service._generate_stage_skeleton(
                self.session,
                self.stage,
                [1, 2, 3, 4, 5, 6],
                501,
            )

        self.assertEqual(5, result.total_rounds)
        self.assertEqual(15, len(result.pairings))
        pairs = {frozenset({pairing.home_team_id, pairing.away_team_id}) for pairing in result.pairings}
        self.assertEqual(15, len(pairs))
        # The shortcut plays the whole circle, so nothing is stopped: a scope
        # previously marked stopped is cleared instead.
        self.cleared.assert_awaited_once_with(self.session, 77, 501)
        self.stopped.assert_not_awaited()
