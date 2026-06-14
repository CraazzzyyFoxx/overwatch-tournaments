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
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

enums = importlib.import_module("shared.core.enums")
swiss = importlib.import_module("shared.services.bracket.swiss")
swiss_settings = importlib.import_module("shared.services.bracket.swiss_settings")
types = importlib.import_module("shared.services.bracket.types")
stage_service = importlib.import_module("src.services.admin.stage")


class SwissStageGenerationTests(IsolatedAsyncioTestCase):
    async def test_generation_records_bye_for_scope(self) -> None:
        stage = SimpleNamespace(
            id=77,
            stage_type=enums.StageType.SWISS,
            max_rounds=5,
            settings_json={},
        )
        skeleton = types.BracketSkeleton(
            pairings=[
                types.Pairing(
                    home_team_id=1,
                    away_team_id=2,
                    round_number=2,
                )
            ],
            total_rounds=1,
            bye_team_id=3,
        )

        with (
            patch.object(
                stage_service,
                "_get_swiss_generation_context",
                AsyncMock(return_value=([swiss.SwissStanding(1, 1.0)], set(), 2)),
            ),
            patch.object(stage_service, "generate_bracket", return_value=skeleton),
        ):
            result = await stage_service._generate_stage_skeleton(
                SimpleNamespace(),
                stage,
                [1, 2, 3],
                501,
            )

        self.assertIs(result, skeleton)
        self.assertEqual([3], swiss_settings.swiss_bye_team_ids(stage, 501))

    async def test_impossible_pairing_marks_scope_stopped(self) -> None:
        stage = SimpleNamespace(
            id=77,
            stage_type=enums.StageType.SWISS,
            max_rounds=5,
            settings_json={},
        )

        with (
            patch.object(
                stage_service,
                "_get_swiss_generation_context",
                AsyncMock(return_value=([swiss.SwissStanding(1, 1.0)], set(), 2)),
            ),
            patch.object(
                stage_service,
                "generate_bracket",
                side_effect=swiss.SwissPairingImpossibleError,
            ),
        ):
            result = await stage_service._generate_stage_skeleton(
                SimpleNamespace(),
                stage,
                [1, 2],
                501,
            )

        self.assertEqual([], result.pairings)
        self.assertTrue(swiss_settings.swiss_scope_stopped(stage, 501))
