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

stage_service = importlib.import_module("src.services.admin.stage")
enums = importlib.import_module("shared.core.enums")


def _scalars_result(values: list):
    scalars = Mock()
    scalars.all.return_value = values
    result = Mock()
    result.scalars.return_value = scalars
    return result


class AdminStageMergeTests(IsolatedAsyncioTestCase):
    async def test_merge_group_stages_moves_items_and_stage_references(self) -> None:
        calls: list[str] = []

        target_item = SimpleNamespace(
            id=100,
            stage_id=10,
            name="A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        source_item_b = SimpleNamespace(
            id=101,
            stage_id=11,
            name="B",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        source_item_c = SimpleNamespace(
            id=102,
            stage_id=12,
            name="C",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        target_stage = SimpleNamespace(
            id=10,
            tournament_id=99,
            name="A",
            stage_type=enums.StageType.SWISS,
            is_active=False,
            is_completed=True,
            order=0,
            items=[target_item],
        )
        source_stage_b = SimpleNamespace(
            id=11,
            tournament_id=99,
            name="B",
            stage_type=enums.StageType.SWISS,
            is_active=True,
            is_completed=True,
            order=1,
        )
        source_stage_c = SimpleNamespace(
            id=12,
            tournament_id=99,
            name="C",
            stage_type=enums.StageType.SWISS,
            is_active=False,
            is_completed=True,
            order=2,
        )
        playoff_stage = SimpleNamespace(id=13, tournament_id=99, order=3)

        group_row = SimpleNamespace(stage_id=11)
        encounter_row = SimpleNamespace(stage_id=11)
        standing_row = SimpleNamespace(stage_id=12)
        challonge_row = SimpleNamespace(stage_id=12)

        async def fake_commit():
            calls.append("commit")

        async def fake_enqueue(_session, tournament_id):
            calls.append(f"enqueue:{tournament_id}")

        async def fake_publish(_session, tournament_id, reason):
            calls.append(f"publish:{tournament_id}:{reason}")

        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _scalars_result([source_stage_b, source_stage_c]),
                    _scalars_result([source_item_b, source_item_c]),
                    _scalars_result([]),
                    _scalars_result([]),
                    _scalars_result([group_row]),
                    _scalars_result([encounter_row]),
                    _scalars_result([standing_row]),
                    _scalars_result([challonge_row]),
                    _scalars_result([target_stage, playoff_stage]),
                ]
            ),
            delete=AsyncMock(),
            flush=AsyncMock(),
            commit=AsyncMock(side_effect=fake_commit),
        )

        with (
            patch.object(
                stage_service,
                "get_stage",
                AsyncMock(side_effect=[target_stage, "merged-stage"]),
            ),
            patch.object(
                stage_service,
                "enqueue_tournament_recalculation",
                AsyncMock(side_effect=fake_enqueue),
            ) as enqueue_recalc,
            patch.object(
                stage_service,
                "_publish_tournament_changed",
                AsyncMock(side_effect=fake_publish),
            ) as publish_changed,
        ):
            result = await stage_service.merge_group_stages(
                session,
                target_stage_id=target_stage.id,
                source_stage_ids=[source_stage_b.id, source_stage_c.id],
                target_name="Groups",
            )

        self.assertEqual("merged-stage", result)
        self.assertEqual("Groups", target_stage.name)
        self.assertTrue(target_stage.is_active)
        self.assertTrue(target_stage.is_completed)
        self.assertEqual(target_stage.id, source_item_b.stage_id)
        self.assertEqual(target_stage.id, source_item_c.stage_id)
        self.assertEqual(1, source_item_b.order)
        self.assertEqual(2, source_item_c.order)
        self.assertEqual(target_stage.id, group_row.stage_id)
        self.assertEqual(target_stage.id, encounter_row.stage_id)
        self.assertEqual(target_stage.id, standing_row.stage_id)
        self.assertEqual(target_stage.id, challonge_row.stage_id)
        self.assertEqual(0, target_stage.order)
        self.assertEqual(1, playoff_stage.order)
        session.delete.assert_any_await(source_stage_b)
        session.delete.assert_any_await(source_stage_c)
        enqueue_recalc.assert_awaited_once_with(session, target_stage.tournament_id)
        publish_changed.assert_awaited_once_with(
            session,
            target_stage.tournament_id,
            "structure_changed",
        )
        self.assertLess(calls.index("enqueue:99"), calls.index("commit"))
        self.assertLess(calls.index("publish:99:structure_changed"), calls.index("commit"))
