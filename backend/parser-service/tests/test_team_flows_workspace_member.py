"""P5.3: ``team_flows.to_pydantic_player`` builds ``PlayerRead.user_id`` (a
required field) from ``player.to_dict()`` plus an explicit override, since
``Player.user_id`` was dropped in the contract step (iwrefac07) and
``to_dict()`` only reflects real ORM columns. This must keep resolving to
``player.workspace_member.player_id`` regardless of whether the "user" entity
was requested (workspace_member itself is always eager-loaded by
team_entities/player_entities; only the nested .player is entity-gated).
"""

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
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

team_flows = importlib.import_module("src.services.team.flows")


def _player(*, workspace_member_player_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "id": 1,
            "created_at": None,
            "updated_at": None,
            "name": "Roster Player",
            "sub_role": None,
            "rank": 1500,
            "role": "damage",
            "tournament_id": 7,
            "team_id": 9,
            "is_newcomer": False,
            "is_newcomer_role": False,
            "is_substitution": False,
            "related_player_id": None,
            "workspace_member_id": 555,
        },
        rank=1500,
        division=None,
        workspace_member=SimpleNamespace(player_id=workspace_member_player_id, player=None),
        tournament=None,
        team=None,
    )


class ToPydanticPlayerWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_user_id_resolved_from_workspace_member_without_user_entity(self) -> None:
        """No "user" entity requested: workspace_member is still loaded and
        user_id must still resolve correctly (only the nested .player/full
        UserRead stays gated)."""
        session = object()
        player = _player(workspace_member_player_id=42)

        result = await team_flows.to_pydantic_player(session, player, [])

        self.assertEqual(42, result.user_id)
        self.assertIsNone(result.user)

    async def test_user_id_resolved_from_workspace_member_with_user_entity(self) -> None:
        session = object()
        player = _player(workspace_member_player_id=77)
        player.workspace_member.player = SimpleNamespace(id=77)

        fake_user_read = team_flows.schemas.UserRead(id=77, name="Roster Player")
        with patch.object(team_flows.user_flows, "to_pydantic", AsyncMock(return_value=fake_user_read)):
            result = await team_flows.to_pydantic_player(session, player, ["user"])

        self.assertEqual(77, result.user_id)
        self.assertEqual(fake_user_read, result.user)
