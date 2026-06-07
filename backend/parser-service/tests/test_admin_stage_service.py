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
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

stage_service = importlib.import_module("src.services.admin.stage")
admin_schemas = importlib.import_module("src.schemas.admin.stage")
enums = importlib.import_module("shared.core.enums")


class AdminStageServiceTests(IsolatedAsyncioTestCase):
    async def test_generate_round_robin_encounters_per_group_item(self) -> None:
        stage = SimpleNamespace(
            id=7,
            tournament_id=99,
            stage_type=enums.StageType.ROUND_ROBIN,
            items=[
                SimpleNamespace(
                    id=10,
                    inputs=[
                        SimpleNamespace(slot=1, team_id=1),
                        SimpleNamespace(slot=2, team_id=2),
                    ],
                ),
                SimpleNamespace(
                    id=11,
                    inputs=[
                        SimpleNamespace(slot=1, team_id=3),
                        SimpleNamespace(slot=2, team_id=4),
                    ],
                ),
            ],
        )
        created_encounters: list = []

        def _fake_add(obj):
            # Simulate autoincrement: any added Encounter gets an id so that
            # persist_advancement_edges can build its local→id map.
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = len(created_encounters) + 100
            created_encounters.append(obj)

        session = SimpleNamespace(
            add=Mock(side_effect=_fake_add),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(
                stage_service,
                "_load_team_names",
                AsyncMock(
                    side_effect=[
                        {1: "Team One", 2: "Team Two"},
                        {3: "Team Three", 4: "Team Four"},
                    ]
                ),
            ),
            patch.object(
                stage_service.standings_service,
                "recalculate_for_tournament",
                AsyncMock(),
            ),
            patch.object(stage_service, "_publish_tournament_changed", AsyncMock()),
        ):
            encounters = await stage_service.generate_encounters(session, stage.id)

        self.assertEqual(2, len(encounters))
        self.assertEqual([10, 11], [encounter.stage_item_id for encounter in encounters])
        self.assertEqual([(1, 2), (3, 4)], [
            (encounter.home_team_id, encounter.away_team_id)
            for encounter in encounters
        ])
        self.assertEqual(
            ["Team One vs Team Two", "Team Three vs Team Four"],
            [encounter.name for encounter in encounters],
        )
        session.commit.assert_awaited_once_with()

    async def test_create_stage_item_creates_compat_group_and_recalculates_standings(self) -> None:
        stage = SimpleNamespace(
            id=7,
            tournament_id=99,
            stage_type=enums.StageType.ROUND_ROBIN,
        )
        existing_group_result = Mock()
        existing_group_result.scalar_one_or_none.return_value = None
        session = SimpleNamespace(
            execute=AsyncMock(return_value=existing_group_result),
            add=Mock(side_effect=lambda item: setattr(item, "id", getattr(item, "id", 123))),
            commit=AsyncMock(),
        )
        data = admin_schemas.StageItemCreate(
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "get_stage_item", AsyncMock(return_value="created")),
            patch.object(
                stage_service.standings_service,
                "recalculate_for_tournament",
                AsyncMock(),
            ) as recalculate,
            patch.object(stage_service, "_publish_tournament_changed", AsyncMock()),
        ):
            result = await stage_service.create_stage_item(session, stage.id, data)

        self.assertEqual("created", result)
        added_group = session.add.call_args_list[1].args[0]
        self.assertEqual("Group A", added_group.name)
        self.assertEqual(stage.id, added_group.stage_id)
        self.assertTrue(added_group.is_groups)
        recalculate.assert_awaited_once_with(session, stage.tournament_id)

    async def test_update_stage_item_input_swaps_with_existing_stage_team(self) -> None:
        stage = SimpleNamespace(id=7, tournament_id=99)
        stage_item = SimpleNamespace(id=10, stage=stage, stage_id=stage.id)
        current_input = SimpleNamespace(
            id=1,
            stage_item=stage_item,
            input_type=enums.StageItemInputType.FINAL,
            team_id=11,
            source_stage_item_id=None,
            source_position=None,
        )
        other_input = SimpleNamespace(
            id=2,
            stage_item=stage_item,
            input_type=enums.StageItemInputType.FINAL,
            team_id=22,
            source_stage_item_id=None,
            source_position=None,
        )
        current_result = Mock()
        current_result.scalar_one_or_none.return_value = current_input
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = SimpleNamespace(
            id=22, tournament_id=stage.tournament_id
        )
        existing_result = Mock()
        existing_result.scalar_one_or_none.return_value = other_input
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[current_result, team_result, existing_result]),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        data = admin_schemas.StageItemInputUpdate(
            input_type=enums.StageItemInputType.FINAL,
            team_id=22,
        )

        with patch.object(
            stage_service.standings_service,
            "recalculate_for_tournament",
            AsyncMock(),
        ) as recalculate, patch.object(
            stage_service,
            "_publish_tournament_changed",
            AsyncMock(),
        ):
            result = await stage_service.update_stage_item_input(session, current_input.id, data)

        self.assertIs(result, current_input)
        self.assertEqual(22, current_input.team_id)
        self.assertEqual(11, other_input.team_id)
        self.assertEqual(enums.StageItemInputType.FINAL, current_input.input_type)
        recalculate.assert_awaited_once_with(session, stage.tournament_id)
        session.commit.assert_awaited_once_with()
        session.refresh.assert_awaited_once_with(current_input)

    async def test_update_stage_item_input_finalizes_tentative_override(self) -> None:
        stage = SimpleNamespace(id=7, tournament_id=99)
        stage_item = SimpleNamespace(id=10, stage=stage, stage_id=stage.id)
        current_input = SimpleNamespace(
            id=1,
            stage_item=stage_item,
            input_type=enums.StageItemInputType.TENTATIVE,
            team_id=None,
            source_stage_item_id=55,
            source_position=2,
        )
        current_result = Mock()
        current_result.scalar_one_or_none.return_value = current_input
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = SimpleNamespace(
            id=33, tournament_id=stage.tournament_id
        )
        existing_result = Mock()
        existing_result.scalar_one_or_none.return_value = None
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[current_result, team_result, existing_result]),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        data = admin_schemas.StageItemInputUpdate(
            input_type=enums.StageItemInputType.FINAL,
            team_id=33,
        )

        with patch.object(
            stage_service.standings_service,
            "recalculate_for_tournament",
            AsyncMock(),
        ) as recalculate, patch.object(
            stage_service,
            "_publish_tournament_changed",
            AsyncMock(),
        ):
            result = await stage_service.update_stage_item_input(session, current_input.id, data)

        self.assertIs(result, current_input)
        self.assertEqual(enums.StageItemInputType.FINAL, current_input.input_type)
        self.assertEqual(33, current_input.team_id)
        self.assertIsNone(current_input.source_stage_item_id)
        self.assertIsNone(current_input.source_position)
        recalculate.assert_awaited_once_with(session, stage.tournament_id)

    async def test_seed_teams_publishes_structure_changed_event(self) -> None:
        stage = SimpleNamespace(
            id=7,
            tournament_id=99,
            items=[
                SimpleNamespace(id=10, order=0, inputs=[]),
                SimpleNamespace(id=11, order=1, inputs=[]),
            ],
        )
        teams = [
            SimpleNamespace(id=1, tournament_id=stage.tournament_id, avg_sr=3200, total_sr=3200),
            SimpleNamespace(id=2, tournament_id=stage.tournament_id, avg_sr=3100, total_sr=3100),
        ]
        teams_result = Mock()
        teams_result.scalars.return_value.all.return_value = teams
        session = SimpleNamespace(
            execute=AsyncMock(return_value=teams_result),
            add=Mock(),
            delete=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.standings_service, "recalculate_for_tournament", AsyncMock()),
            patch.object(stage_service, "_publish_tournament_changed", AsyncMock()) as publish_changed,
        ):
            await stage_service.seed_teams(session, stage.id, [1, 2], mode="snake_sr")

        publish_changed.assert_awaited_once_with(stage.tournament_id, "structure_changed")

    async def test_activate_and_generate_publishes_single_structure_changed_event(self) -> None:
        session = SimpleNamespace()
        stage = SimpleNamespace(id=7, tournament_id=99)
        encounters = [SimpleNamespace(id=101)]

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_auto_wire_from_groups", AsyncMock()),
            patch.object(stage_service, "activate_stage", AsyncMock(return_value=stage)) as activate_stage,
            patch.object(stage_service, "generate_encounters", AsyncMock(return_value=encounters)) as generate_encounters,
            patch.object(stage_service, "_publish_tournament_changed", AsyncMock()) as publish_changed,
        ):
            result_stage, result_encounters = await stage_service.activate_and_generate(session, stage.id, force=True)

        self.assertIs(result_stage, stage)
        self.assertEqual(encounters, result_encounters)
        activate_stage.assert_awaited_once_with(session, stage.id, notify=False)
        generate_encounters.assert_awaited_once_with(session, stage.id, notify=False)
        publish_changed.assert_awaited_once_with(stage.tournament_id, "structure_changed")

    async def test_auto_wire_splits_advancing_teams_for_double_elimination(self) -> None:
        playoff = SimpleNamespace(
            id=20,
            tournament_id=99,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=True,
        )
        source = SimpleNamespace(id=10, advance_count=4)
        session = SimpleNamespace()

        with (
            patch.object(stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(stage_service, "wire_from_groups", AsyncMock()) as wire,
        ):
            await stage_service._auto_wire_from_groups(session, playoff)

        # advance_count=4 split evenly → 2 Upper, 2 Lower (cross seeding).
        wire.assert_awaited_once_with(session, 20, 10, 2, top_lb=2, mode="cross", notify=False)

    async def test_auto_wire_odd_count_sends_extra_to_upper(self) -> None:
        playoff = SimpleNamespace(
            id=20,
            tournament_id=99,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=True,
        )
        source = SimpleNamespace(id=10, advance_count=3)
        session = SimpleNamespace()

        with (
            patch.object(stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(stage_service, "wire_from_groups", AsyncMock()) as wire,
        ):
            await stage_service._auto_wire_from_groups(session, playoff)

        # advance_count=3 → 2 Upper (extra), 1 Lower.
        wire.assert_awaited_once_with(session, 20, 10, 2, top_lb=1, mode="cross", notify=False)

    async def test_auto_wire_all_to_upper_when_split_disabled(self) -> None:
        playoff = SimpleNamespace(
            id=20,
            tournament_id=99,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=False,
        )
        source = SimpleNamespace(id=10, advance_count=4)
        session = SimpleNamespace()

        with (
            patch.object(stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(stage_service, "wire_from_groups", AsyncMock()) as wire,
        ):
            await stage_service._auto_wire_from_groups(session, playoff)

        wire.assert_awaited_once_with(session, 20, 10, 4, top_lb=0, mode="cross", notify=False)

    async def test_auto_wire_noop_without_advance_count(self) -> None:
        playoff = SimpleNamespace(
            id=20,
            tournament_id=99,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=True,
        )
        source = SimpleNamespace(id=10, advance_count=None)
        session = SimpleNamespace()

        with (
            patch.object(stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(stage_service, "wire_from_groups", AsyncMock()) as wire,
        ):
            await stage_service._auto_wire_from_groups(session, playoff)

        wire.assert_not_awaited()

    async def test_delete_stage_removes_encounters_and_standings(self) -> None:
        stage = SimpleNamespace(id=7, tournament_id=99)
        executed: list = []
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=lambda stmt: executed.append(stmt)),
            delete=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_publish_tournament_changed", AsyncMock()),
        ):
            await stage_service.delete_stage(session, stage.id)

        # The stage's matches and standings must be removed explicitly, since
        # their FKs to Stage are ON DELETE SET NULL (would otherwise orphan).
        sqls = [str(stmt) for stmt in executed]
        self.assertTrue(any("DELETE FROM tournament.encounter" in sql for sql in sqls))
        self.assertTrue(any("DELETE FROM tournament.standing" in sql for sql in sqls))
        session.delete.assert_awaited_once_with(stage)
        session.commit.assert_awaited_once_with()
