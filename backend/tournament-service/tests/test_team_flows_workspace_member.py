"""P5.3: ``team_flows.flows_service.to_pydantic_player`` builds ``PlayerRead.user_id`` (a
required field) from ``player.to_dict()`` plus an explicit override, since
``Player.user_id`` was dropped in the contract step (iwrefac07) and
``to_dict()`` only reflects real ORM columns. This must keep resolving to
``player.workspace_member.player_id`` regardless of whether the "user" entity
was requested (workspace_member itself is always eager-loaded by
team_entities/player_entities; only the nested .player is entity-gated).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from shared.schemas.identity import PersonDisplayRead
from shared.schemas.role import RoleRef

team_flows = importlib.import_module("src.services.team.flows")


async def _displays(_session, players):
    return {p.id: PersonDisplayRead.build(canonical="Canon#1", snapshot=p.name) for p in players}


def _player(*, workspace_member_player_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="Roster Player",
        to_dict=lambda: {
            "id": 1,
            "created_at": None,
            "updated_at": None,
            "name": "Roster Player",
            "rank": 1500,
            "tournament_id": 7,
            "team_id": 9,
            "is_newcomer": False,
            "is_newcomer_role": False,
            "is_substitution": False,
            "related_player_id": None,
            "workspace_member_id": 555,
        },
        rank=1500,
        role_ref=RoleRef(dimension="player_role", role="damage"),
        workspace_member=SimpleNamespace(player_id=workspace_member_player_id),
        tournament=None,
        team=None,
    )


@patch.object(team_flows, "player_displays", _displays)
class ToPydanticPlayerWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_user_id_resolved_from_workspace_member_without_user_entity(self) -> None:
        """No "user" entity requested: workspace_member is still loaded and
        user_id must still resolve correctly (only the nested .player/full
        UserRead stays gated)."""
        session = object()
        player = _player(workspace_member_player_id=42)

        result = await team_flows.flows_service.to_pydantic_player(session, player, [], grid=None)

        self.assertEqual(42, result.user_id)
        self.assertIsNone(result.user)
        shown = result.display
        self.assertEqual(("Roster Player", None, "Canon#1"), (shown.name, shown.tag, shown.canonical))

    async def test_user_id_resolved_from_workspace_member_with_user_entity(self) -> None:
        session = object()
        player = _player(workspace_member_player_id=77)
        # `player_to_read` serializes this through the plain sync `user_to_read`,
        # so the stand-in must carry every column `UserRead` requires -- there is
        # no longer an awaited service method to intercept with a canned read.
        player.workspace_member.player = SimpleNamespace(id=77, name="Roster Player")

        expected_user_read = team_flows.schemas.UserRead(id=77, name="Roster Player")
        result = await team_flows.flows_service.to_pydantic_player(session, player, ["user"], grid=None)

        self.assertEqual(77, result.user_id)
        self.assertEqual(expected_user_read, result.user)
