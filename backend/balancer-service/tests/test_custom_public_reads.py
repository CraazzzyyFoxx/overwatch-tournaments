from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.rpc import custom  # noqa: E402


class _Broker:
    """Collects the handlers ``custom.register`` decorates, keyed by subject."""

    def __init__(self) -> None:
        self.ops: dict[str, Any] = {}

    def subscriber(self, subject: str):
        def decorate(fn):
            self.ops[subject] = fn
            return fn

        return decorate


class _Session:
    async def __aenter__(self) -> Any:
        return object()

    async def __aexit__(self, *_: Any) -> bool:
        return False


class CustomMixPublicReadTests(IsolatedAsyncioTestCase):
    """A mix board is readable with no identity at all; writing one is not.

    The gateway forwards no identity for the mix reads (``AuthNone`` in
    ``gateway/internal/balancer/routes.go``), so a handler that asks for an
    actor answers every signed-out visitor with ``unauthorized`` instead of the
    lobby board they came for.
    """

    def setUp(self) -> None:
        self.broker = _Broker()
        custom.register(self.broker, MagicMock())

    async def _call(self, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        with patch.object(custom, "_SF", _Session):
            return await self.broker.ops[subject](data, None)

    async def test_listing_and_scoring_a_workspace_mixes_needs_no_identity(self) -> None:
        service = MagicMock()
        service.list = AsyncMock(return_value=[])
        service.hosts = AsyncMock(return_value={})
        service.casual_matches.activity_for_games = AsyncMock(return_value={})
        service.team_names.mapping_for_games = AsyncMock(return_value={})
        service.workspace_discord_channel_id = AsyncMock(return_value=None)
        service.host_prefs.points_per_win_by_user = AsyncMock(return_value={})
        service.lobbies.list_for_games = AsyncMock(return_value={})
        service.mix_stats = AsyncMock(return_value=[])

        with patch.object(custom, "custom_game_service", service):
            listed = await self._call("rpc.balancer.custom.list", {"workspace_id": 7})
            scored = await self._call("rpc.balancer.custom.stats", {"workspace_id": 7})

        self.assertTrue(listed["ok"], listed)
        self.assertEqual([], listed["data"])
        self.assertTrue(scored["ok"], scored)
        self.assertEqual({"since": None, "members": []}, scored["data"])

    async def test_list_rows_leave_the_solver_document_out(self) -> None:
        """The list never touches a lobby's ``balance_result_json``: the column is
        deferred with ``raiseload`` there, and it is megabytes per balanced mix.
        The lobby row below has no such attribute, so any read of it fails the call."""
        row = SimpleNamespace(
            id=3,
            workspace_id=7,
            host_user_id=5,
            name="Friday mix",
            status="balanced",
            lobby_count=1,
            self_signup="pool",
            self_role_edit=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        lobby = SimpleNamespace(
            custom_game_id=3, lobby_index=0, selected_variant_index=2, next_map_id=None, balanced_at=None
        )
        service = MagicMock()
        service.list = AsyncMock(return_value=[row])
        service.hosts = AsyncMock(return_value={5: "Host"})
        service.casual_matches.activity_for_games = AsyncMock(return_value={})
        service.team_names.mapping_for_games = AsyncMock(return_value={3: {1: "Ravens"}})
        service.lobbies.list_for_games = AsyncMock(return_value={3: [lobby]})
        service.workspace_discord_channel_id = AsyncMock(return_value=None)
        service.host_prefs.points_per_win_by_user = AsyncMock(return_value={5: 25})

        with patch.object(custom, "custom_game_service", service):
            listed = await self._call("rpc.balancer.custom.list", {"workspace_id": 7})

        self.assertTrue(listed["ok"], listed)
        [item] = listed["data"]
        self.assertNotIn("balance_result", item)
        self.assertNotIn("selected_variant_index", item)
        self.assertEqual({"1": "Ravens"}, item["settings"]["team_names"])
        self.assertEqual(25, item["settings"]["points_per_win"])
        # From plan A, unchanged by the lobby cutover.
        self.assertEqual("pool", item["self_signup"])
        self.assertIs(True, item["self_role_edit"])
        self.assertEqual(1, item["lobby_count"])
        self.assertEqual(
            [{"lobby_index": 0, "selected_variant_index": 2, "next_map_id": None, "balanced_at": None}],
            item["lobbies"],
        )

    async def test_detail_read_says_where_every_player_sits_and_what_each_lobby_shows(self) -> None:
        """The board never derives lobby membership itself: the server reads it
        off each lobby's selected option, and says whether that option's lineup
        has been recorded yet."""
        from src.domain.balancer.result_serializer import lobby_document

        def seat(uuid: str) -> dict[str, Any]:
            return {"uuid": uuid, "name": f"P{uuid}", "assigned_rating": 2500, "role_preferences": ["tank"]}

        game = SimpleNamespace(
            id=3,
            workspace_id=7,
            host_user_id=5,
            name="Friday mix",
            status="balanced",
            lobby_count=2,
            self_signup="closed",
            self_role_edit=False,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        document = lobby_document([{"teams": [{"roster": {"tank": [seat("7")]}}, {"roster": {"tank": [seat("8")]}}]}])
        balanced_at = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)
        lobbies = [
            SimpleNamespace(
                custom_game_id=3,
                lobby_index=0,
                selected_variant_index=0,
                next_map_id=None,
                balanced_at=balanced_at,
                balance_result_json=document,
            ),
            SimpleNamespace(
                custom_game_id=3,
                lobby_index=1,
                selected_variant_index=0,
                next_map_id=None,
                balanced_at=balanced_at,
                balance_result_json=None,
            ),
        ]
        rows = [
            SimpleNamespace(
                id=1,
                workspace_member_id=7,
                sort_order=0,
                participation="pool",
                role_selection_mode="all_ranked",
                is_flex=False,
                lobby_pin=None,
            ),
            SimpleNamespace(
                id=2,
                workspace_member_id=9,
                sort_order=1,
                participation="pool",
                role_selection_mode="all_ranked",
                is_flex=False,
                lobby_pin=1,
            ),
        ]

        service = MagicMock()
        service.get = AsyncMock(return_value=game)
        service.roster.list_for_game = AsyncMock(return_value=rows)
        service.lobbies.list_for_game = AsyncMock(return_value=lobbies)
        service.team_names.mapping_for_game = AsyncMock(return_value={})
        service.workspace_discord_channel_id = AsyncMock(return_value=None)
        service.host_points_per_win = AsyncMock(return_value=0)
        service.roster_shape = AsyncMock(
            return_value=SimpleNamespace(model_dump=lambda: {"slots": {"tank": 1}, "source": "default"})
        )
        service.co_hosts.user_ids_for_game = AsyncMock(return_value=[])
        service.hosts = AsyncMock(return_value={5: "Host"})
        service.casual_matches.activity_for_games = AsyncMock(return_value={})
        # Lobby 0 recorded a match after it was balanced; lobby 1 never did.
        service.casual_matches.activity_for_lobbies = AsyncMock(
            return_value={0: (2, datetime(2026, 1, 1, 22, 0, tzinfo=UTC))}
        )
        service.members = AsyncMock(return_value={})
        service.player_roles.roles_for_players = AsyncMock(return_value={})
        service.ranks.list_layer_rows = AsyncMock(return_value=[])
        service.ranks.resolve = AsyncMock(return_value={})

        with (
            patch.object(custom, "custom_game_service", service),
            patch.object(custom, "get_effective_division_grid", AsyncMock(return_value=object())),
        ):
            read = await self._call("rpc.balancer.custom.get", {"workspace_id": 7, "custom_game_id": 3})

        self.assertTrue(read["ok"], read)
        data = read["data"]
        self.assertNotIn("balance_result", data)
        by_member = {row["workspace_member_id"]: row for row in data["players"]}
        # 7 sits in lobby A's selected option; 9 is pinned to B but seated nowhere.
        self.assertEqual(0, by_member[7]["current_lobby"])
        self.assertIsNone(by_member[9]["current_lobby"])
        self.assertEqual(1, by_member[9]["lobby_pin"])
        self.assertEqual([0, 1], [lobby["lobby_index"] for lobby in data["lobbies"]])
        self.assertEqual(2, data["lobbies"][0]["matches_count"])
        self.assertTrue(data["lobbies"][0]["lineup_recorded"])
        self.assertEqual(0, data["lobbies"][1]["matches_count"])
        self.assertFalse(data["lobbies"][1]["lineup_recorded"])
        self.assertIsNotNone(data["lobbies"][0]["balance_result"])

    async def test_writing_one_still_requires_an_authenticated_actor(self) -> None:
        service = MagicMock()
        service.close = AsyncMock()

        with patch.object(custom, "custom_game_service", service):
            closed = await self._call("rpc.balancer.custom.close", {"workspace_id": 7, "custom_game_id": 3})

        self.assertFalse(closed["ok"], closed)
        self.assertEqual("unauthorized", closed["error"]["code"])
        service.close.assert_not_awaited()
