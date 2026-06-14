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
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

enums = importlib.import_module("shared.core.enums")
swiss_rounds = importlib.import_module("src.services.admin.swiss_rounds")


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
            def scalars(self) -> SimpleNamespace:
                return SimpleNamespace(all=lambda: encounters)

        session = SimpleNamespace(
            execute=AsyncMock(return_value=_EncounterResult()),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(swiss_rounds.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(swiss_rounds.stage_service, "_collect_item_team_ids", Mock(return_value=[1, 2])),
            patch.object(swiss_rounds.stage_service, "_generate_stage_skeleton", AsyncMock(return_value=skeleton)),
            patch.object(swiss_rounds.stage_service, "_load_team_names", AsyncMock(return_value={1: "A", 2: "B"})),
            patch.object(
                swiss_rounds.stage_service,
                "_create_encounters_from_skeleton",
                AsyncMock(return_value=generated),
            ),
        ):
            result = await swiss_rounds.generate_next_swiss_round(
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
            def scalars(self) -> SimpleNamespace:
                return SimpleNamespace(all=lambda: encounters)

        session = SimpleNamespace(execute=AsyncMock(return_value=_EncounterResult()))

        with (
            patch.object(swiss_rounds.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(swiss_rounds.stage_service, "_collect_item_team_ids", Mock(return_value=[1, 2])),
            patch.object(swiss_rounds.stage_service, "_generate_stage_skeleton", AsyncMock()) as generate,
        ):
            result = await swiss_rounds.generate_next_swiss_round(
                session,
                tournament_id=999,
                stage_id=77,
                stage_item_id=501,
                expected_next_round=2,
            )

        self.assertEqual([], result)
        generate.assert_not_awaited()
