"""P5.2c: parser-service's ``services.team.service`` Player-creation sites
(``create_player`` async + ``create_player_sync``) must populate
``workspace_member_id`` (alongside the retained ``user_id``) so
workspace-scoped analytics readers that INNER-JOIN on it don't silently
drop newly created roster rows (e.g. log-import substitution creation).
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

team_service = importlib.import_module("src.services.team.service")
enums = importlib.import_module("src.core.enums")


class TeamServiceWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_resolve_workspace_member_id_uses_tournament_workspace(self) -> None:
        workspace_result = Mock()
        workspace_result.scalar_one.return_value = 55
        session = SimpleNamespace(execute=AsyncMock(return_value=workspace_result))
        created_member = SimpleNamespace(id=777)

        with patch.object(
            team_service,
            "get_or_create_workspace_member",
            AsyncMock(return_value=created_member),
        ) as get_or_create:
            member_id = await team_service._resolve_workspace_member_id(
                session, tournament_id=88, player_id=7
            )

        self.assertEqual(777, member_id)
        get_or_create.assert_awaited_once_with(session, workspace_id=55, player_id=7)

    async def test_create_player_sets_workspace_member_id_and_user_id(self) -> None:
        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        user = SimpleNamespace(id=42)
        tournament = SimpleNamespace(id=88)
        team = SimpleNamespace(id=3)

        with patch.object(
            team_service,
            "_resolve_workspace_member_id",
            AsyncMock(return_value=999),
        ) as resolve_member:
            player = await team_service.create_player(
                session,
                name="Sub Player",
                rank=3000,
                role=enums.HeroClass.tank,
                user=user,
                tournament=tournament,
                team=team,
                is_substitution=True,
                related_player_id=10,
            )

        resolve_member.assert_awaited_once_with(session, tournament_id=88, player_id=42)
        self.assertEqual(42, player.user_id)
        self.assertEqual(999, player.workspace_member_id)
        session.add.assert_called_once_with(player)
        session.commit.assert_awaited_once()

    def test_resolve_workspace_member_id_sync_creates_new_member(self) -> None:
        workspace_result = Mock()
        workspace_result.scalar_one.return_value = 55

        insert_result = Mock()
        insert_result.scalar_one_or_none.return_value = 4242

        session = Mock()
        session.execute.side_effect = [workspace_result, insert_result]
        session.flush = Mock()

        member_id = team_service._resolve_workspace_member_id_sync(
            session, tournament_id=88, player_id=7
        )

        self.assertEqual(4242, member_id)
        session.flush.assert_called_once()

    def test_resolve_workspace_member_id_sync_falls_back_to_existing_row_on_conflict(self) -> None:
        workspace_result = Mock()
        workspace_result.scalar_one.return_value = 55

        insert_result = Mock()
        insert_result.scalar_one_or_none.return_value = None  # ON CONFLICT DO NOTHING fired

        existing_result = Mock()
        existing_result.scalar_one_or_none.return_value = 111

        session = Mock()
        session.execute.side_effect = [workspace_result, insert_result, existing_result]

        member_id = team_service._resolve_workspace_member_id_sync(
            session, tournament_id=88, player_id=7
        )

        self.assertEqual(111, member_id)

    def test_create_player_sync_sets_workspace_member_id_and_user_id(self) -> None:
        session = Mock()
        session.add = Mock()
        session.commit = Mock()
        user = SimpleNamespace(id=42)
        tournament = SimpleNamespace(id=88)
        team = SimpleNamespace(id=3)

        with patch.object(
            team_service,
            "_resolve_workspace_member_id_sync",
            Mock(return_value=555),
        ) as resolve_member:
            player = team_service.create_player_sync(
                session,
                name="Sync Player",
                rank=3000,
                role=enums.HeroClass.support,
                user=user,
                tournament=tournament,
                team=team,
            )

        resolve_member.assert_called_once_with(session, tournament_id=88, player_id=42)
        self.assertEqual(42, player.user_id)
        self.assertEqual(555, player.workspace_member_id)
        session.add.assert_called_once_with(player)
        session.commit.assert_called_once_with()
