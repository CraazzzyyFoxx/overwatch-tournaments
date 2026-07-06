"""P5.3: parser-service's admin/team.py Player-creation sites must populate
``workspace_member_id`` (``Player.user_id`` was dropped in the contract step,
iwrefac07) so workspace-scoped analytics readers that INNER-JOIN on it don't
silently drop newly created roster rows.
"""

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


def _result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class AdminTeamWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_resolve_workspace_member_id_creates_member_from_tournament_workspace(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(return_value=_result(55)))
        created_member = SimpleNamespace(id=777)

        with patch.object(
            admin_team_service,
            "get_or_create_workspace_member",
            AsyncMock(return_value=created_member),
        ) as get_or_create:
            member_id = await admin_team_service._resolve_workspace_member_id(session, tournament_id=88, player_id=7)

        self.assertEqual(777, member_id)
        get_or_create.assert_awaited_once_with(session, workspace_id=55, player_id=7)

    async def test_resolve_workspace_member_id_raises_when_tournament_missing(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(return_value=_result(None)))

        with patch.object(admin_team_service, "get_or_create_workspace_member", AsyncMock()) as get_or_create:
            with self.assertRaises(Exception) as ctx:
                await admin_team_service._resolve_workspace_member_id(session, tournament_id=404, player_id=7)

        self.assertEqual(404, ctx.exception.status_code)
        get_or_create.assert_not_awaited()

    async def test_add_player_to_team_sets_workspace_member_id(self) -> None:
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = SimpleNamespace(id=3, tournament_id=88)
        user_result = Mock()
        user_result.scalar_one_or_none.return_value = SimpleNamespace(id=7)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[team_result, user_result]),
            add=Mock(side_effect=lambda player: setattr(player, "id", 501)),
            commit=AsyncMock(),
        )
        data = admin_schemas.PlayerCreate(
            name="Roster Player",
            user_id=7,
            team_id=3,
            tournament_id=999,  # overridden by team.tournament_id in the service
        )

        with (
            patch.object(
                admin_team_service,
                "_resolve_workspace_member_id",
                AsyncMock(return_value=4242),
            ) as resolve_member,
            patch.object(admin_team_service, "get_player", AsyncMock(return_value="created")),
        ):
            result = await admin_team_service.add_player_to_team(session, 3, data)

        self.assertEqual("created", result)
        resolve_member.assert_awaited_once_with(session, tournament_id=88, player_id=7)
        created_player = session.add.call_args.args[0]
        self.assertFalse(hasattr(created_player, "user_id"))
        self.assertEqual(4242, created_player.workspace_member_id)

    async def test_create_player_sets_workspace_member_id(self) -> None:
        user_result = Mock()
        user_result.scalar_one_or_none.return_value = SimpleNamespace(id=9)
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = SimpleNamespace(id=4, tournament_id=101)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[user_result, team_result]),
            add=Mock(side_effect=lambda player: setattr(player, "id", 502)),
            commit=AsyncMock(),
        )
        data = admin_schemas.PlayerCreate(
            name="New Player",
            user_id=9,
            team_id=4,
            tournament_id=101,
        )

        with (
            patch.object(
                admin_team_service,
                "_resolve_workspace_member_id",
                AsyncMock(return_value=9001),
            ) as resolve_member,
            patch.object(admin_team_service, "get_player", AsyncMock(return_value="created")),
        ):
            result = await admin_team_service.create_player(session, data)

        self.assertEqual("created", result)
        resolve_member.assert_awaited_once_with(session, tournament_id=101, player_id=9)
        created_player = session.add.call_args.args[0]
        self.assertFalse(hasattr(created_player, "user_id"))
        self.assertEqual(9001, created_player.workspace_member_id)
