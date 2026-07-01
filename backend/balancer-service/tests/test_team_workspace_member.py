"""P5.3: balancer-service's ``bulk_create_from_balancer`` finalize-roster
Player-creation site must populate ``workspace_member_id`` (``Player.user_id``
was dropped in the contract step, iwrefac07) so workspace-scoped analytics
readers that INNER-JOIN on it don't silently drop newly created roster rows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.services import team as team_service  # noqa: E402
from src.schemas.team import BalancerTeam, BalancerTeamMember  # noqa: E402


def _result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class BulkCreateFromBalancerWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_new_player_gets_workspace_member_id(self) -> None:
        tournament = SimpleNamespace(id=88, workspace_id=55)
        captain_user = SimpleNamespace(id=7)
        member_user = SimpleNamespace(id=42)
        created_team = SimpleNamespace(id=3, name="Roster", tournament_id=88)
        created_member = SimpleNamespace(id=9001)

        # execute() call order inside bulk_create_from_balancer:
        # 1) load tournament, 2) find existing team by name -> None,
        # 3) player-already-in-tournament check -> None,
        # 4) player-exists-globally check -> None (newcomer),
        # 5) player-exists-for-role check -> None (newcomer role)
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _result(tournament),
                    _result(None),
                    _result(None),
                    _result(None),
                    _result(None),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        def fake_add(entity):
            if isinstance(entity, team_service.models.Team):
                entity.id = created_team.id
                entity.name = created_team.name

        session.add.side_effect = fake_add

        payload = [
            BalancerTeam(
                uuid=uuid4(),
                avgSr=3000,
                name="Roster#0000",
                totalSr=3000,
                members=[
                    BalancerTeamMember(
                        uuid=uuid4(),
                        name="Roster#0000",
                        role="tank",
                        rank=3000,
                    )
                ],
            )
        ]

        with (
            patch.object(
                team_service.user_svc,
                "find_by_battle_tag",
                AsyncMock(side_effect=[captain_user, member_user]),
            ),
            patch.object(
                team_service,
                "get_or_create_workspace_member",
                AsyncMock(return_value=created_member),
            ) as get_or_create,
        ):
            await team_service.bulk_create_from_balancer(session, 88, payload)

        get_or_create.assert_awaited_once_with(session, workspace_id=55, player_id=42)
        player_calls = [
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], team_service.models.Player)
        ]
        self.assertEqual(1, len(player_calls))
        created_player = player_calls[0]
        self.assertFalse(hasattr(created_player, "user_id"))
        self.assertEqual(9001, created_player.workspace_member_id)
