"""P5.3: tournament-service Player-creation sites must populate
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
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

schemas = importlib.import_module("src.schemas")
admin_team_service = importlib.import_module("src.services.admin.team")


def _result(value):
    """A fake Result answering both the repository shape
    (``.unique().scalars().first()``) and the older ``.scalar_one_or_none()``."""
    result = Mock()
    result.scalar_one_or_none.return_value = value
    result.unique.return_value = result
    result.scalars.return_value = SimpleNamespace(
        first=lambda: value,
        all=lambda: [value] if value is not None else [],
    )
    return result


class AdminTeamWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_resolve_workspace_member_id_delegates_to_the_shared_helper(self) -> None:
        session = SimpleNamespace()

        with patch.object(
            admin_team_service,
            "resolve_workspace_member_id",
            AsyncMock(return_value=777),
        ) as resolve:
            member_id = await admin_team_service.team_service._resolve_workspace_member_id(
                session, tournament_id=88, player_id=7
            )

        self.assertEqual(777, member_id)
        resolve.assert_awaited_once_with(session, tournament_id=88, player_id=7)

    async def test_resolve_workspace_member_id_raises_when_tournament_missing(self) -> None:
        """The shared helper answers ``None`` for a tournament it cannot resolve
        a workspace for; this service's own 404 is what wraps it."""
        session = SimpleNamespace()

        with patch.object(admin_team_service, "resolve_workspace_member_id", AsyncMock(return_value=None)):
            with self.assertRaises(Exception) as ctx:
                await admin_team_service.team_service._resolve_workspace_member_id(
                    session, tournament_id=404, player_id=7
                )

        self.assertEqual(404, ctx.exception.status_code)

    async def test_add_player_to_team_sets_workspace_member_id(self) -> None:
        team_result = _result(SimpleNamespace(id=3, tournament_id=88))
        user_result = _result(SimpleNamespace(id=7))
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[team_result, user_result]),
            add=Mock(side_effect=lambda player: setattr(player, "id", 501)),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )
        data = schemas.PlayerCreate(
            name="Roster Player",
            user_id=7,
            team_id=3,
            tournament_id=999,  # overridden by team.tournament_id in the service
        )

        with (
            patch.object(
                admin_team_service.team_service,
                "_resolve_workspace_member_id",
                AsyncMock(return_value=4242),
            ) as resolve_member,
            patch.object(admin_team_service.team_service, "_publish_structure_changed", AsyncMock()),
            patch.object(admin_team_service.team_service, "get_player", AsyncMock(return_value="created")),
        ):
            result = await admin_team_service.team_service.add_player_to_team(session, 3, data)

        self.assertEqual("created", result)
        resolve_member.assert_awaited_once_with(session, tournament_id=88, player_id=7)
        created_player = session.add.call_args.args[0]
        self.assertFalse(hasattr(created_player, "user_id"))
        self.assertEqual(4242, created_player.workspace_member_id)

    async def test_create_player_sets_workspace_member_id(self) -> None:
        user_result = _result(SimpleNamespace(id=9))
        team_result = _result(SimpleNamespace(id=4, tournament_id=101))
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[user_result, team_result]),
            add=Mock(side_effect=lambda player: setattr(player, "id", 502)),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )
        data = schemas.PlayerCreate(
            name="New Player",
            user_id=9,
            team_id=4,
            tournament_id=101,
        )

        with (
            patch.object(
                admin_team_service.team_service,
                "_resolve_workspace_member_id",
                AsyncMock(return_value=9001),
            ) as resolve_member,
            patch.object(admin_team_service.team_service, "_publish_structure_changed", AsyncMock()),
            patch.object(admin_team_service.team_service, "get_player", AsyncMock(return_value="created")),
        ):
            result = await admin_team_service.team_service.create_player(session, data)

        self.assertEqual("created", result)
        resolve_member.assert_awaited_once_with(session, tournament_id=101, player_id=9)
        created_player = session.add.call_args.args[0]
        self.assertFalse(hasattr(created_player, "user_id"))
        self.assertEqual(9001, created_player.workspace_member_id)
