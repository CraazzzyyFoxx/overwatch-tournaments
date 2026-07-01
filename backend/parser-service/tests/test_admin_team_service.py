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

admin_schemas = importlib.import_module("src.schemas.admin.team")
admin_team_service = importlib.import_module("src.services.admin.team")


class AdminTeamServiceTests(IsolatedAsyncioTestCase):
    def test_team_child_relationships_rely_on_database_delete_cascades(self) -> None:
        self.assertTrue(admin_team_service.models.Team.players.property.passive_deletes)
        self.assertTrue(admin_team_service.models.Team.standings.property.passive_deletes)
        self.assertTrue(admin_team_service.models.Team.challonge.property.passive_deletes)

    async def test_create_team_defaults_balancer_name_to_name_when_omitted(self) -> None:
        tournament_result = Mock()
        tournament_result.scalar_one_or_none.return_value = SimpleNamespace(id=68)
        captain_result = Mock()
        captain_result.scalar_one_or_none.return_value = SimpleNamespace(id=1)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[tournament_result, captain_result]),
            add=Mock(side_effect=lambda team: setattr(team, "id", 1977)),
            commit=AsyncMock(),
        )
        data = admin_schemas.TeamCreate(
            name="Test 1",
            tournament_id=68,
            captain_id=1,
        )

        with patch.object(admin_team_service, "get_team", AsyncMock(return_value="created")):
            result = await admin_team_service.create_team(session, data)

        self.assertEqual("created", result)
        created_team = session.add.call_args.args[0]
        self.assertEqual("Test 1", created_team.balancer_name)
        session.commit.assert_awaited_once_with()

    async def test_update_team_defaults_null_balancer_name_to_current_name(self) -> None:
        team = SimpleNamespace(
            id=1977,
            name="Test 1",
            balancer_name="Old balancer name",
            players=[],
        )
        result = Mock()
        result.scalar_one_or_none.return_value = team
        session = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            commit=AsyncMock(),
        )
        data = admin_schemas.TeamUpdate(balancer_name=None)

        with patch.object(admin_team_service, "get_team", AsyncMock(return_value=team)):
            updated_team = await admin_team_service.update_team(session, 1977, data)

        self.assertIs(team, updated_team)
        self.assertEqual("Test 1", team.balancer_name)
        session.commit.assert_awaited_once_with()

    async def test_update_team_rejects_captain_outside_roster(self) -> None:
        team = SimpleNamespace(
            id=1977,
            name="Test 1",
            balancer_name="Test 1",
            captain_id=1,
            players=[
                SimpleNamespace(workspace_member=SimpleNamespace(player_id=1)),
                SimpleNamespace(workspace_member=SimpleNamespace(player_id=2)),
            ],
        )
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = team
        captain_result = Mock()
        captain_result.scalar_one_or_none.return_value = SimpleNamespace(id=5)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[team_result, captain_result]),
            commit=AsyncMock(),
        )
        data = admin_schemas.TeamUpdate(captain_id=5)

        with self.assertRaises(Exception) as ctx:
            await admin_team_service.update_team(session, 1977, data)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("roster", ctx.exception.detail)
        session.commit.assert_not_awaited()

    async def test_delete_player_removes_substitution_descendants(self) -> None:
        player = SimpleNamespace(id=10, related_player_id=None)
        substitute = SimpleNamespace(id=11, related_player_id=10)
        nested_substitute = SimpleNamespace(id=12, related_player_id=11)

        player_result = Mock()
        player_result.scalar_one_or_none.return_value = player
        first_children_result = Mock()
        first_children_result.scalars.return_value.all.return_value = [substitute]
        second_children_result = Mock()
        second_children_result.scalars.return_value.all.return_value = [nested_substitute]
        third_children_result = Mock()
        third_children_result.scalars.return_value.all.return_value = []
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    player_result,
                    first_children_result,
                    second_children_result,
                    third_children_result,
                ]
            ),
            delete=AsyncMock(),
            commit=AsyncMock(),
        )

        await admin_team_service.delete_player(session, 10)

        self.assertEqual(
            [substitute, nested_substitute, player],
            [call.args[0] for call in session.delete.await_args_list],
        )
        session.commit.assert_awaited_once_with()

    async def test_create_player_rejects_related_player_from_another_team(self) -> None:
        user_result = Mock()
        user_result.scalar_one_or_none.return_value = SimpleNamespace(id=7)
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = SimpleNamespace(id=3, tournament_id=88)
        related_player_result = Mock()
        related_player_result.scalar_one_or_none.return_value = SimpleNamespace(
            id=19,
            team_id=99,
            tournament_id=88,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[user_result, team_result, related_player_result]),
            add=Mock(),
            commit=AsyncMock(),
        )
        data = admin_schemas.PlayerCreate(
            name="Sub",
            user_id=7,
            team_id=3,
            tournament_id=88,
            is_substitution=True,
            related_player_id=19,
        )

        with self.assertRaises(Exception) as ctx:
            await admin_team_service.create_player(session, data)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("same team", ctx.exception.detail)
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    async def test_update_player_rejects_related_player_from_another_tournament(self) -> None:
        player = SimpleNamespace(
            id=21,
            user=SimpleNamespace(id=7),
            team=SimpleNamespace(id=3, tournament_id=88),
            team_id=3,
            tournament_id=88,
        )
        player_result = Mock()
        player_result.scalar_one_or_none.return_value = player
        related_player_result = Mock()
        related_player_result.scalar_one_or_none.return_value = SimpleNamespace(
            id=22,
            team_id=3,
            tournament_id=99,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[player_result, related_player_result]),
            commit=AsyncMock(),
        )
        data = admin_schemas.PlayerUpdate(
            is_substitution=True,
            related_player_id=22,
        )

        with self.assertRaises(Exception) as ctx:
            await admin_team_service.update_player(session, 21, data)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("same tournament", ctx.exception.detail)
        session.commit.assert_not_awaited()
