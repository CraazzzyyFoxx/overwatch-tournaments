from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

enums = importlib.import_module("shared.core.enums")
swiss_rounds = importlib.import_module("src.services.standings.swiss_auto_round")


class SwissRoundWorkerTests(IsolatedAsyncioTestCase):
    async def test_generated_round_does_not_commit_or_recalculate_directly(self) -> None:
        stage_item = SimpleNamespace(id=501)
        stage = SimpleNamespace(id=77, is_active=True, items=[stage_item], max_rounds=5)
        encounters = [
            SimpleNamespace(
                home_team_id=1,
                away_team_id=2,
                round=1,
                status=enums.EncounterStatus.COMPLETED,
                result_status=enums.EncounterResultStatus.NONE,
            )
        ]
        skeleton = SimpleNamespace(pairings=[SimpleNamespace(round_number=2)])
        generated = [SimpleNamespace(id=101)]

        class _EncounterResult:
            def unique(self) -> _EncounterResult:
                return self

            def scalars(self) -> SimpleNamespace:
                return SimpleNamespace(all=lambda: encounters)

        session = SimpleNamespace(
            execute=AsyncMock(return_value=_EncounterResult()),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(swiss_rounds.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(swiss_rounds, "_collect_item_team_ids", Mock(return_value=[1, 2])),
            patch.object(swiss_rounds.stage_service, "_generate_stage_skeleton", AsyncMock(return_value=skeleton)),
            patch.object(swiss_rounds.stage_service, "_load_team_names", AsyncMock(return_value={1: "A", 2: "B"})),
            patch.object(
                swiss_rounds.stage_service,
                "_create_encounters_from_skeleton",
                AsyncMock(return_value=generated),
            ),
        ):
            result = await swiss_rounds.swiss_rounds_service.generate_next_swiss_round(
                session,
                tournament_id=999,
                stage_id=77,
                stage_item_id=501,
                expected_next_round=2,
            )

        self.assertEqual(generated, result)
        session.commit.assert_not_awaited()

    async def test_stale_round_is_idempotently_skipped(self) -> None:
        stage_item = SimpleNamespace(id=501)
        stage = SimpleNamespace(id=77, is_active=True, items=[stage_item], max_rounds=5)
        encounters = [
            SimpleNamespace(
                home_team_id=1,
                away_team_id=2,
                round=2,
                status=enums.EncounterStatus.OPEN,
                result_status=enums.EncounterResultStatus.NONE,
            )
        ]

        class _EncounterResult:
            def unique(self) -> _EncounterResult:
                return self

            def scalars(self) -> SimpleNamespace:
                return SimpleNamespace(all=lambda: encounters)

        session = SimpleNamespace(execute=AsyncMock(return_value=_EncounterResult()))

        with (
            patch.object(swiss_rounds.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(swiss_rounds, "_collect_item_team_ids", Mock(return_value=[1, 2])),
            patch.object(swiss_rounds.stage_service, "_generate_stage_skeleton", AsyncMock()) as generate,
        ):
            result = await swiss_rounds.swiss_rounds_service.generate_next_swiss_round(
                session,
                tournament_id=999,
                stage_id=77,
                stage_item_id=501,
                expected_next_round=2,
            )

        self.assertEqual([], result)
        generate.assert_not_awaited()

    async def test_generate_ready_rounds_does_not_enqueue_a_bracket_job(self) -> None:
        item = SimpleNamespace(id=501)
        stage = SimpleNamespace(id=77, is_active=True, items=[item], max_rounds=5)
        generated = [SimpleNamespace(id=101)]

        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [stage])),
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
                ]
            )
        )

        with (
            patch.object(swiss_rounds, "stage_item_ready_for_next_round", return_value=True),
            patch.object(swiss_rounds, "next_round_number", return_value=2),
            patch.object(
                swiss_rounds.swiss_rounds_service,
                "generate_next_swiss_round",
                AsyncMock(return_value=generated),
            ) as generate,
        ):
            result = await swiss_rounds.swiss_rounds_service.generate_ready_rounds(session, 999)

        self.assertEqual(generated, result)
        self.assertFalse(hasattr(swiss_rounds, "request_bracket_job"))
        generate.assert_awaited_once()
        self.assertEqual(77, generate.await_args.kwargs["stage_id"])
        self.assertIs(stage, generate.await_args.kwargs["stage"])
