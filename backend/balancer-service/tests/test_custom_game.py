from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import (  # noqa: E402
    CasualTeamSide,
    HeroClass,
    MixParticipation,
    MixRoleSelectionMode,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain.member_rank import ResolvedRank  # noqa: E402
from shared.services.member_rank import MIX_ORDER  # noqa: E402
from shared.services.workspace_roster import RosterMember  # noqa: E402
from src.services.custom_game import _MAX_CO_HOSTS, CustomGameService  # noqa: E402


def _session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


def _row(**fields) -> SimpleNamespace:
    return SimpleNamespace(**fields)


def _roster_row(row_id: int, member_id: int, sort_order: int, **overrides) -> SimpleNamespace:
    """One lineup row. ``roles=None`` is the ALL_RANKED default; a list is EXPLICIT.

    ``roles`` is carried on the fake row itself so ``_roles_for_players`` below
    can answer the child-table read the service now makes, instead of every test
    wiring that repository by hand.
    """
    fields = {
        "id": row_id,
        "custom_game_id": 11,
        "workspace_member_id": member_id,
        "sort_order": sort_order,
        "participation": MixParticipation.POOL,
        "is_flex": False,
        "roles": None,
        "created_at": None,
    }
    fields.update(overrides)
    fields["role_selection_mode"] = (
        MixRoleSelectionMode.ALL_RANKED if fields["roles"] is None else MixRoleSelectionMode.EXPLICIT
    )
    return _row(**fields)


def _seat_row(spec) -> SimpleNamespace:
    """A frozen ``casual.player``: a bare member id, or ``(id, role, rank)``.

    Undo reads back the role and the balance-time rank the recording wrote;
    the rotation reader only cares who played, hence the short form.
    """
    if isinstance(spec, tuple):
        member_id, role, rank = spec
        return _row(workspace_member_id=member_id, role=role, rank=rank)
    return _row(workspace_member_id=spec, role=None, rank=0)


def _match(
    match_id: int,
    *,
    created_at: int,
    home: list,
    away: list,
    scores: tuple[int, int] = (1, 0),
    **overrides,
) -> SimpleNamespace:
    """One frozen ``casual.match`` with both scored sides and their seats."""
    fields = {
        "id": match_id,
        "created_at": created_at,
        "map_id": None,
        "recorded_by": 9,
        "points_per_win_applied": None,
        "teams": [
            _row(
                id=match_id * 100 + index,
                side=side,
                name=f"Team {index}",
                score=score,
                players=[_seat_row(spec) for spec in members],
            )
            for index, (side, members, score) in enumerate(
                ((CasualTeamSide.HOME, home, scores[0]), (CasualTeamSide.AWAY, away, scores[1])), start=1
            )
        ],
    }
    fields.update(overrides)
    return _row(**fields)


def _game(**overrides) -> SimpleNamespace:
    fields = {
        "id": 11,
        "workspace_id": 1,
        "host_user_id": 9,
        "name": "Scrim",
        "status": "draft",
        "points_per_win": None,
        "next_map_id": None,
        "discord_channel_id": None,
        "balancer_config_json": None,
        "balancer_config_version": 1,
        "balance_result_json": None,
        "balance_result_version": 1,
    }
    fields.update(overrides)
    return _row(**fields)


def _members(*member_ids: int) -> dict[int, RosterMember]:
    """The roster rows ``workspace_roster.list_roster`` would return."""
    return {
        member_id: RosterMember(
            member_id=member_id,
            player_id=member_id * 10,
            battle_tag=f"P{member_id}#1",
            display_name=f"P{member_id}",
        )
        for member_id in member_ids
    }


def _ranks(*member_ids: int) -> dict[tuple[int, str], ResolvedRank]:
    out: dict[tuple[int, str], ResolvedRank] = {}
    for member_id in member_ids:
        out[(member_id, "tank")] = ResolvedRank(2500, "workspace")
        out[(member_id, "dps")] = ResolvedRank(2400, "workspace")
        out[(member_id, "support")] = ResolvedRank(2300, "workspace")
    return out


class CustomGameServiceTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.games = MagicMock()
        self.roster = MagicMock()
        self.ranks = MagicMock()
        self.run_balance = AsyncMock(return_value={"variants": []})
        self.games.create = AsyncMock(side_effect=self._assign_id)
        self.games.get = AsyncMock()
        self.games.list_for_workspace = AsyncMock(return_value=[])
        self.roster.create_many = AsyncMock(side_effect=lambda _s, rows: rows)
        self.casual_teams = MagicMock()
        self.casual_teams.create_many = AsyncMock(side_effect=self._assign_casual_team_ids)
        self.casual_players = MagicMock()
        self.casual_players.create = AsyncMock(side_effect=lambda _s, row: row)
        self.casual_matches = MagicMock()
        self.casual_matches.create = AsyncMock(side_effect=self._assign_match_id)
        # No match history recorded unless a test says otherwise -- `balance`'s
        # rotation-priority read and `rotation()` itself both need this to resolve
        # to something awaitable by default.
        self.casual_matches.list_for_custom_game = AsyncMock(return_value=[])
        # Nothing to undo unless a test records something.
        self.casual_matches.get_for_game = AsyncMock(return_value=None)
        self.casual_matches.newest_id_for_game = AsyncMock(return_value=None)
        # The normalized child tables of a mix. Empty by default: no co-hosts, no
        # per-team name override, no own role mask -- exactly what a fresh mix has.
        self.co_hosts = MagicMock()
        self.co_hosts.user_ids_for_game = AsyncMock(return_value=[])
        self.co_hosts.add = AsyncMock()
        self.co_hosts.remove = AsyncMock()
        self.player_roles = MagicMock()
        self.player_roles.roles_for_players = AsyncMock(side_effect=self._roles_for_players)
        self.player_roles.replace_for_player = AsyncMock()
        self.team_names = MagicMock()
        self.team_names.mapping_for_game = AsyncMock(return_value={})
        self.team_names.set = AsyncMock()
        self.role_slots = MagicMock()
        self.role_slots.mapping_for_game = AsyncMock(return_value={})
        self.role_slots.replace = AsyncMock()
        self.roster.list_for_game = AsyncMock(return_value=[])
        self.roster.delete_for_game = AsyncMock()
        self.roster.get_by = AsyncMock(return_value=None)
        self.roster.delete = AsyncMock()
        # Every requested member exists in this workspace unless a test says otherwise.
        self.load_roster = AsyncMock(side_effect=lambda _s, *, workspace_id, member_ids: _members(*member_ids))
        # No workspace member resolves to a host name unless a test says
        # otherwise -- `transfer_host` treats an unresolved id as "not a member".
        self.load_hosts = AsyncMock(return_value={})
        # Nobody belongs to this workspace unless a test says otherwise --
        # `transfer_host`/`add_co_host` treat a non-member target as a 404. The
        # actor's own membership is settled at the RPC gate, so `_writable` only
        # reads the co-host grants.
        self.load_member_user_ids = AsyncMock(return_value=set())
        self.ranks.resolve = AsyncMock(return_value={})
        self.ranks.set_ranks = AsyncMock(return_value={})
        self.grid = object()
        self._grid_patch = patch(
            "src.services.custom_game.get_effective_division_grid",
            new=AsyncMock(return_value=self.grid),
        )
        self._grid_patch.start()
        self.addCleanup(self._grid_patch.stop)
        # No workspace-level roster default unless a test says otherwise --
        # `roster_shape`/`balance` then fall back to the built-in Overwatch 5v5
        # shape, matching every existing assertion below.
        self.workspace_roster_slots = AsyncMock(return_value=None)
        self._workspace_slots_patch = patch(
            "src.services.custom_game.get_workspace_roster_slots",
            new=self.workspace_roster_slots,
        )
        self._workspace_slots_patch.start()
        self.addCleanup(self._workspace_slots_patch.stop)
        self.service = CustomGameService(
            games=self.games,
            roster=self.roster,
            co_hosts=self.co_hosts,
            player_roles=self.player_roles,
            team_names=self.team_names,
            role_slots=self.role_slots,
            casual_matches=self.casual_matches,
            casual_teams=self.casual_teams,
            casual_players=self.casual_players,
            ranks=self.ranks,
            load_roster=self.load_roster,
            load_hosts=self.load_hosts,
            load_member_user_ids=self.load_member_user_ids,
            run_balance=self.run_balance,
        )
        self.session = _session()

    @staticmethod
    async def _assign_id(_session, row):
        if getattr(row, "id", None) is None:
            row.id = 11
        return row

    @staticmethod
    async def _assign_casual_team_ids(_session, rows):
        for index, row in enumerate(rows, start=101):
            row.id = index
        return rows

    @staticmethod
    async def _assign_match_id(_session, row):
        if getattr(row, "id", None) is None:
            row.id = 501
        return row

    async def _roles_for_players(self, _session, player_ids):
        """The explicit role order of whichever rows the test put in the roster."""
        wanted = set(player_ids)
        rows = self.roster.list_for_game.return_value or []
        return {row.id: list(row.roles) for row in rows if row.id in wanted and row.roles is not None}

    @staticmethod
    async def _assign_roster_ids(_session, rows):
        for index, row in enumerate(rows, start=101):
            row.id = index
        return rows

    async def test_create_roster_from_member_ids(self) -> None:
        game = await self.service.create(
            self.session,
            workspace_id=1,
            host_user_id=9,
            name="Scrim",
            actor_user_id=9,
            member_ids=[7, 8],
        )
        self.assertEqual(game.status, "draft")
        self.assertEqual(game.name, "Scrim")
        self.assertEqual(game.workspace_id, 1)
        self.assertEqual(game.host_user_id, 9)
        self.games.create.assert_awaited_once()
        rows = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.workspace_member_id for row in rows], [7, 8])
        self.assertEqual([row.sort_order for row in rows], [0, 1])

    async def test_create_without_members_is_an_empty_mix(self) -> None:
        await self.service.create(self.session, workspace_id=1, host_user_id=9, name="Scrim", actor_user_id=9)
        self.roster.create_many.assert_not_called()

    async def test_member_of_another_workspace_404(self) -> None:
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)
        with self.assertRaises(HTTPException) as ctx:
            await self.service.create(
                self.session,
                workspace_id=1,
                host_user_id=9,
                name="Scrim",
                actor_user_id=9,
                member_ids=[7, 8],
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.games.create.assert_not_called()

    async def test_create_clones_a_previous_mix(self) -> None:
        source = _game(
            id=5,
            status="completed",
            points_per_win=25,
            next_map_id=42,
            discord_channel_id=777,
            balancer_config_json={"MMR_DIFF_WEIGHT": 5},
            balance_result_json={"variants": []},
        )
        self.games.get.return_value = source
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, participation=MixParticipation.BENCHED, roles=["tank", "dps"], is_flex=True),
            _roster_row(2, 8, 1, participation=MixParticipation.MUST_PLAY),
        ]
        self.roster.create_many = AsyncMock(side_effect=self._assign_roster_ids)
        self.role_slots.mapping_for_game.return_value = {"tank": 2}
        self.team_names.mapping_for_game.return_value = {0: "Wolves", 1: "Ravens"}
        self.co_hosts.user_ids_for_game.return_value = [4, 9]

        game = await self.service.create(
            self.session,
            workspace_id=1,
            host_user_id=9,
            name="Scrim 2",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        rows = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.workspace_member_id for row in rows], [7, 8])
        self.assertEqual([row.sort_order for row in rows], [0, 1])
        # Last session's bench and pins are last session's; everybody starts in
        # the pool. The role setup is the part worth keeping.
        self.assertEqual([row.participation for row in rows], [MixParticipation.POOL, MixParticipation.POOL])
        self.assertEqual(
            [row.role_selection_mode for row in rows],
            [MixRoleSelectionMode.EXPLICIT, MixRoleSelectionMode.ALL_RANKED],
        )
        self.assertEqual([row.is_flex for row in rows], [True, False])
        self.player_roles.replace_for_player.assert_awaited_once_with(self.session, 101, ["tank", "dps"])
        self.role_slots.replace.assert_awaited_once_with(self.session, game.id, {"tank": 2})
        self.assertEqual(
            [call.args for call in self.team_names.set.await_args_list],
            [(self.session, game.id, 0, "Wolves"), (self.session, game.id, 1, "Ravens")],
        )
        # The new host is never also their own co-host.
        self.co_hosts.add.assert_awaited_once_with(self.session, game.id, 4)
        self.assertEqual(game.points_per_win, 25)
        self.assertEqual(game.discord_channel_id, 777)
        self.assertEqual(game.balancer_config_json, {"MMR_DIFF_WEIGHT": 5})
        # Nothing that describes a played session travels.
        self.assertEqual(game.status, "draft")
        self.assertIsNone(game.balance_result_json)
        self.assertIsNone(game.next_map_id)

    async def test_create_clone_drops_members_who_left_the_workspace(self) -> None:
        self.games.get.return_value = _game(id=5)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 8, 1)]
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)

        await self.service.create(
            self.session,
            workspace_id=1,
            host_user_id=9,
            name="Scrim 2",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        rows = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.workspace_member_id for row in rows], [7])

    async def test_create_clone_of_another_workspace_404(self) -> None:
        self.games.get.return_value = _game(id=5, workspace_id=2)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.create(
                self.session,
                workspace_id=1,
                host_user_id=9,
                name="Scrim 2",
                actor_user_id=9,
                clone_from_game_id=5,
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.games.create.assert_not_called()

    async def test_balance_calls_run_balance_and_stores_result(self) -> None:
        game = _game()
        roster = [_roster_row(1, 7, 0), _roster_row(2, 8, 1)]
        payload = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [{"uuid": "7"}]}},
                        {"roster": {"tank": [{"uuid": "8"}]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8)
        self.run_balance.return_value = payload

        with patch("shared.models.BalancerBalance") as balance_cls:
            out = await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
            balance_cls.assert_not_called()

        self.run_balance.assert_awaited_once()
        player_data, config_overrides, _progress, role_mask = self.run_balance.await_args.args
        self.assertIn("7", player_data["players"])
        self.assertIn("8", player_data["players"])
        self.assertIsNone(config_overrides)
        self.assertEqual(role_mask["tank"], 1)
        self.assertEqual(out.status, "balanced")
        self.assertIs(out.balance_result_json, payload)
        self.assertNotIn("tournament_id", payload)
        # Seat placement lives in the payload alone -- a seated row keeps the
        # participation the host set rather than mirroring the team it landed in.
        self.assertEqual(roster[0].participation, MixParticipation.POOL)
        self.assertEqual(roster[1].participation, MixParticipation.POOL)

    async def test_balance_resolves_with_mix_order_and_host_as_author(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        kwargs = self.ranks.resolve.await_args.kwargs
        self.assertEqual(kwargs["workspace_id"], 1)
        self.assertEqual(kwargs["order"], MIX_ORDER)
        self.assertEqual(kwargs["author_user_id"], 9)
        self.assertIs(kwargs["grid"], self.grid)
        # The resolver keys off member ids and needs the player behind each one
        # to reach an Overwatch snapshot.
        self.assertEqual(kwargs["members"], {7: 70})

    async def test_balance_names_players_from_the_roster(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 8, 1)]
        self.load_roster.side_effect = None
        self.load_roster.return_value = {
            7: RosterMember(member_id=7, player_id=70, battle_tag="Ana#1", display_name=None),
            8: RosterMember(member_id=8, player_id=80, battle_tag=None, display_name=None),
        }
        self.ranks.resolve.return_value = _ranks(7, 8)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        players = self.run_balance.await_args.args[0]["players"]
        self.assertEqual(players["7"]["identity"]["name"], "Ana#1")
        self.assertEqual(players["8"]["identity"]["name"], "player-8")

    async def test_completed_balance_409(self) -> None:
        self.games.get.return_value = _game(status="completed")
        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        self.assertEqual(ctx.exception.status_code, 409)
        self.run_balance.assert_not_called()
        self.ranks.resolve.assert_not_called()

    async def test_update_player_rejects_rank_value(self) -> None:
        """The per-game pin is gone: a correction belongs in the host's own book."""
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"rank_value": 1500},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_update_player_rejects_unknown_field(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"team_index": 1},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_update_player_rejects_unknown_role(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"roles": ["tank", "healer"]},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_update_player_keeps_stored_balance(self) -> None:
        """A lineup edit must not blow away the last balance -- only pressing
        Balance teams again should replace it."""
        game = _game(status="balanced", balance_result_json={"variants": []})
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]
        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"participation": MixParticipation.BENCHED},
            actor_user_id=9,
        )
        self.assertEqual(row.participation, MixParticipation.BENCHED)
        self.assertEqual(game.status, "balanced")
        self.assertEqual(game.balance_result_json, {"variants": []})
        self.assertEqual(row.sort_order, 0)

    async def test_update_player_pins_a_seat(self) -> None:
        game = _game()
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]
        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"participation": MixParticipation.MUST_PLAY},
            actor_user_id=9,
        )
        self.assertEqual(row.participation, MixParticipation.MUST_PLAY)
        # One field, three states: pinning cannot leave a row benched as well.

    async def test_update_player_toggles_is_flex(self) -> None:
        game = _game()
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]
        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"is_flex": True},
            actor_user_id=9,
        )
        self.assertTrue(row.is_flex)
        # A patch, not a replace: the bench switch is untouched.
        self.assertNotEqual(row.participation, MixParticipation.BENCHED)

    async def test_set_participation_moves_every_named_row_at_once(self) -> None:
        game = _game()
        seated = _roster_row(1, 7, 0)
        rested = _roster_row(2, 8, 1, participation=MixParticipation.MUST_PLAY)
        untouched = _roster_row(3, 9, 2)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [seated, rested, untouched]

        await self.service.set_participation(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            participation={
                7: MixParticipation.MUST_PLAY,
                8: MixParticipation.BENCHED,
            },
            actor_user_id=9,
        )

        self.assertEqual(seated.participation, MixParticipation.MUST_PLAY)
        self.assertEqual(rested.participation, MixParticipation.BENCHED)
        # A row the caller never mentioned is left exactly as it was.
        self.assertEqual(untouched.participation, MixParticipation.POOL)
        self.session.flush.assert_awaited_once()

    async def test_set_participation_404s_a_member_outside_the_mix(self) -> None:
        """All or nothing: one unknown member must not half-apply the verdict."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [row]

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_participation(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                participation={
                    7: MixParticipation.BENCHED,
                    404: MixParticipation.BENCHED,
                },
                actor_user_id=9,
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(row.participation, MixParticipation.POOL)

    async def test_set_participation_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_participation(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                participation={7: MixParticipation.BENCHED},
                actor_user_id=9,
            )

        self.assertEqual(ctx.exception.status_code, 409)

    async def test_balance_sends_must_play_to_the_solver(self) -> None:
        game = _game()
        roster = [_roster_row(1, 7, 0, participation=MixParticipation.MUST_PLAY), _roster_row(2, 8, 1)]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        player_data = self.run_balance.await_args.args[0]
        self.assertTrue(player_data["players"]["7"]["identity"]["mustPlay"])
        self.assertFalse(player_data["players"]["8"]["identity"]["mustPlay"])

    async def test_balance_sends_is_flex_to_the_solver(self) -> None:
        game = _game()
        roster = [_roster_row(1, 7, 0, is_flex=True), _roster_row(2, 8, 1)]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        player_data = self.run_balance.await_args.args[0]
        self.assertTrue(player_data["players"]["7"]["identity"]["isFullFlex"])
        self.assertFalse(player_data["players"]["8"]["identity"]["isFullFlex"])

    async def test_balance_skips_benched_rows(self) -> None:
        game = _game()
        roster = [_roster_row(1, 7, 0), _roster_row(2, 8, 1, participation=MixParticipation.BENCHED)]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": [{"roster": {"tank": [{"uuid": "7"}]}}]}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        player_data = self.run_balance.await_args.args[0]
        self.assertEqual(list(player_data["players"]), ["7"])
        # A benched row costs nothing to resolve, so it is not even looked up.
        self.assertEqual(self.ranks.resolve.await_args.kwargs["members"], {7: 70})
        self.assertEqual(roster[0].participation, MixParticipation.POOL)
        self.assertEqual(roster[1].participation, MixParticipation.BENCHED)

    async def test_balance_benches_players_left_out_of_the_result(self) -> None:
        """A player the solver could not seat (an uneven leftover, or a
        structural gap) is switched off the same way a manual bench would be,
        so the lineup reflects the result immediately."""
        game = _game()
        roster = [_roster_row(1, 7, 0), _roster_row(2, 8, 1), _roster_row(3, 9, 2)]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8, 9)
        self.run_balance.return_value = {
            "teams": [{"roster": {"tank": [{"uuid": "7"}, {"uuid": "8"}]}}],
            "benched_players": [{"uuid": "9", "name": "P9"}],
        }

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        # Only the solver's own overflow list benches a row.
        self.assertNotEqual(roster[0].participation, MixParticipation.BENCHED)
        self.assertNotEqual(roster[1].participation, MixParticipation.BENCHED)
        self.assertEqual(roster[2].participation, MixParticipation.BENCHED)

    async def test_balance_all_benched_422(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0, participation=MixParticipation.BENCHED)]
        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "empty_lineup")
        self.run_balance.assert_not_called()

    async def test_balance_solver_value_error_is_422_not_internal(self) -> None:
        """The solver raises plain ``ValueError`` for diagnosable input problems
        (e.g. too few players who can cover a required role). Left uncaught it
        reached the generic RPC handler and was reported as an opaque
        "internal error" instead of the actual, actionable reason."""
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.side_effect = ValueError(
            "Cannot form 2 full teams — not enough role coverage: 'tank' short by 1"
        )

        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("not enough role coverage", ctx.exception.detail)

    async def test_balance_unranked_player_422(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = {
            (7, "tank"): ResolvedRank(None, "none"),
            (7, "dps"): ResolvedRank(None, "none"),
            (7, "support"): ResolvedRank(None, "none"),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "missing_ranked_role")
        self.run_balance.assert_not_called()

    async def test_balance_uses_role_order_as_priority(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0, roles=["support", "dps"])]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        classes = self.run_balance.await_args.args[0]["players"]["7"]["stats"]["classes"]
        self.assertEqual(classes["support"]["priority"], 1)
        self.assertEqual(classes["dps"]["priority"], 2)
        self.assertNotIn("tank", classes)

    async def test_update_roster_keeps_surviving_row_state(self) -> None:
        game = _game()
        keep = _roster_row(1, 7, 0, participation=MixParticipation.BENCHED, roles=["dps"])
        drop = _roster_row(2, 8, 1)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [keep, drop]

        await self.service.update_roster(
            self.session, workspace_id=1, custom_game_id=11, member_ids=[9, 7], actor_user_id=9
        )

        self.roster.delete.assert_awaited_once_with(self.session, drop)
        created = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.workspace_member_id for row in created], [9])
        self.assertEqual(keep.participation, MixParticipation.BENCHED)
        self.assertEqual(keep.roles, ["dps"])
        self.assertEqual(keep.sort_order, 1)

    async def test_update_roster_keeps_stored_balance(self) -> None:
        """Adding or dropping a player must not blow away the last balance --
        only pressing Balance teams again should replace it."""
        game = _game(status="balanced", balance_result_json={"variants": []})
        keep = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [keep]

        await self.service.update_roster(
            self.session, workspace_id=1, custom_game_id=11, member_ids=[7, 9], actor_user_id=9
        )

        self.assertEqual(game.status, "balanced")
        self.assertEqual(game.balance_result_json, {"variants": []})
        self.assertEqual(keep.sort_order, 0)

    async def test_adding_players_materialises_the_hosts_own_ranks(self) -> None:
        """Joining a mix copies the effective rank into the host's book.

        Without this the number a lineup shows belongs to no layer the host can
        edit: the sheet writes the author layer, so a correction reads as a
        per-game edit while silently rewriting the host's book for every mix,
        and Clear has nothing to clear.
        """
        self.ranks.resolve.return_value = _ranks(7, 8)

        await self.service.create(
            self.session,
            workspace_id=1,
            host_user_id=9,
            name="Scrim",
            actor_user_id=9,
            member_ids=[7, 8],
        )

        seeded = {call.kwargs["workspace_member_id"]: call.kwargs for call in self.ranks.set_ranks.await_args_list}
        self.assertEqual(sorted(seeded), [7, 8])
        self.assertEqual(seeded[7]["author_user_id"], 9)
        self.assertEqual(seeded[7]["workspace_id"], 1)
        self.assertEqual(seeded[7]["ranks"], {"tank": 2500, "dps": 2400, "support": 2300})
        kwargs = self.ranks.resolve.await_args.kwargs
        self.assertEqual(kwargs["order"], MIX_ORDER)
        self.assertEqual(kwargs["author_user_id"], 9)
        self.assertIs(kwargs["grid"], self.grid)

    async def test_seeding_leaves_a_rank_the_host_already_owns_alone(self) -> None:
        """Re-adding somebody must not undo a correction the host already made."""
        self.ranks.resolve.return_value = {
            (7, "tank"): ResolvedRank(3000, "author"),
            (7, "dps"): ResolvedRank(2400, "workspace"),
            (7, "support"): ResolvedRank(None, "none"),
        }

        await self.service.create(
            self.session, workspace_id=1, host_user_id=9, name="Scrim", actor_user_id=9, member_ids=[7]
        )

        # Only the inherited role is copied; an unranked one stays unranked
        # rather than being invented from nothing.
        self.assertEqual(self.ranks.set_ranks.await_args.kwargs["ranks"], {"dps": 2400})

    async def test_seeding_skips_a_player_with_no_rank_anywhere(self) -> None:
        self.ranks.resolve.return_value = {}

        await self.service.create(
            self.session, workspace_id=1, host_user_id=9, name="Scrim", actor_user_id=9, member_ids=[7]
        )

        self.ranks.set_ranks.assert_not_awaited()

    async def test_update_roster_seeds_only_the_rows_it_created(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7, 8)

        await self.service.update_roster(
            self.session, workspace_id=1, custom_game_id=11, member_ids=[7, 8], actor_user_id=9
        )

        # 7 was already in the mix, so its book was seeded when it joined; only
        # the newcomer is resolved and written.
        self.assertEqual(self.ranks.resolve.await_args.kwargs["members"], {8: 80})
        self.assertEqual([call.kwargs["workspace_member_id"] for call in self.ranks.set_ranks.await_args_list], [8])

    async def test_record_outcome_terminal_409(self) -> None:
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                self.games.get.return_value = _game(status=status)
                with self.assertRaises(HTTPException) as ctx:
                    await self.service.record_outcome(
                        self.session,
                        workspace_id=1,
                        custom_game_id=11,
                        winner=1,
                        variant_index=0,
                        actor_user_id=9,
                    )
                self.assertEqual(ctx.exception.status_code, 409)
                self.session.flush.assert_not_called()
                self.session.flush.reset_mock()

    async def test_record_outcome_snapshots_a_casual_match_and_stays_open(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {
                            "roster": {
                                "tank": [self._seat("7", "Alpha", 3200, "tank")],
                                "dps": [self._seat("8", "Bravo", 2900, "dps")],
                            }
                        },
                        {
                            "roster": {
                                "tank": [self._seat("9", "Charlie", 2600, "tank")],
                                "dps": [self._seat("10", "Delta", 3000, "dps")],
                            }
                        },
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result)
        self.team_names.mapping_for_game.return_value = {0: "Wolves"}

        game = await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        # Repeatable: recording a result never closes the mix.
        self.assertEqual(game.status, "balanced")

        created_match = self.casual_matches.create.await_args.args[1]
        self.assertEqual(created_match.custom_game_id, 11)
        self.assertEqual(created_match.recorded_by, 9)

        created_teams = self.casual_teams.create_many.await_args.args[1]
        self.assertEqual([team.match_id for team in created_teams], [501, 501])
        self.assertEqual(
            [(team.side, team.name, team.score) for team in created_teams],
            [(CasualTeamSide.HOME, "Wolves", 1), (CasualTeamSide.AWAY, "Team 2", 0)],
        )

        created_players = [call.args[1] for call in self.casual_players.create.await_args_list]
        self.assertEqual(
            sorted(
                (row.workspace_member_id, row.team_id, row.rank, row.display_name_snapshot) for row in created_players
            ),
            [
                (7, 101, 3200, "Alpha"),
                (8, 101, 2900, "Bravo"),
                (9, 102, 2600, "Charlie"),
                (10, 102, 3000, "Delta"),
            ],
        )

    async def test_record_outcome_redeems_the_pin_of_whoever_played(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result)
        # 7 and 9 took a seat in this match; 8 is pinned for the next one and
        # never played, so its guarantee is still owed.
        pinned_played = _roster_row(1, 7, 0, participation=MixParticipation.MUST_PLAY)
        pinned_absent = _roster_row(2, 8, 1, participation=MixParticipation.MUST_PLAY)
        unpinned_played = _roster_row(3, 9, 2, participation=MixParticipation.POOL)
        self.roster.list_for_game.return_value = [pinned_played, pinned_absent, unpinned_played]

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        # Redeemed: the pin guaranteed one seat, and it just got it.
        self.assertEqual(pinned_played.participation, MixParticipation.POOL)
        # Untouched: never seated, never redeemed, keeps its guarantee.
        self.assertEqual(pinned_absent.participation, MixParticipation.MUST_PLAY)
        # Was never pinned in the first place.
        self.assertEqual(unpinned_played.participation, MixParticipation.POOL)

    async def test_record_outcome_writes_the_selected_map(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result)
        self.session.get = AsyncMock(return_value=_row(id=42, name="King's Row"))

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            map_id=42,
            actor_user_id=9,
        )

        created_match = self.casual_matches.create.await_args.args[1]
        self.assertEqual(created_match.map_id, 42)

    async def test_record_outcome_takes_the_next_map_and_clears_it(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        game = _game(status="balanced", balance_result_json=result, next_map_id=42)
        self.games.get.return_value = game

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        created_match = self.casual_matches.create.await_args.args[1]
        self.assertEqual(created_match.map_id, 42)
        # Consumed: the following match starts from a fresh roll, not a stale one.
        self.assertIsNone(game.next_map_id)

    async def test_record_outcome_explicit_map_beats_the_next_map(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        game = _game(status="balanced", balance_result_json=result, next_map_id=42)
        self.games.get.return_value = game
        self.session.get = AsyncMock(return_value=_row(id=5, name="Busan"))

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            map_id=5,
            actor_user_id=9,
        )

        created_match = self.casual_matches.create.await_args.args[1]
        self.assertEqual(created_match.map_id, 5)
        self.assertIsNone(game.next_map_id)

    async def test_record_outcome_unknown_map_404(self) -> None:
        self.games.get.return_value = _row(
            id=11,
            workspace_id=1,
            host_user_id=9,
            name="Scrim",
            status="balanced",
            config_json=None,
            balance_result_json={"variants": [{"teams": []}]},
        )
        self.session.get = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.record_outcome(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                winner=1,
                variant_index=0,
                map_id=999,
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.casual_matches.create.assert_not_called()

    async def test_record_outcome_draw_scores_zero_zero(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=None,
            variant_index=0,
            actor_user_id=9,
        )

        created_teams = self.casual_teams.create_many.await_args.args[1]
        self.assertEqual([team.score for team in created_teams], [0, 0])

    async def test_record_outcome_without_points_per_win_never_adjusts_ranks(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        self.ranks.set_ranks.assert_not_awaited()

    async def test_record_outcome_applies_points_per_win_with_fallback_to_balance_rating(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {
                            "roster": {
                                "tank": [self._seat("7", "Alpha", 3200, "tank")],
                                "dps": [self._seat("8", "Bravo", 2900, "dps")],
                            }
                        },
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result, points_per_win=25)
        # Member 9 has no author-layer entry yet -- the write must fall back to
        # their balance-time rating (2600) instead of dropping the adjustment.
        self.ranks.list_layer = AsyncMock(return_value={(7, "tank"): 2500, (8, "dps"): 2800})

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        calls = {
            (call.kwargs["workspace_member_id"], call.kwargs["author_user_id"], tuple(call.kwargs["ranks"].items()))
            for call in self.ranks.set_ranks.await_args_list
        }
        self.assertEqual(
            calls,
            {
                (7, 9, (("tank", 2525),)),
                (8, 9, (("dps", 2825),)),
                (9, 9, (("tank", 2575),)),
            },
        )

    async def test_record_outcome_skips_points_delta_on_a_draw(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result, points_per_win=25)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=None,
            variant_index=0,
            actor_user_id=9,
        )

        self.ranks.set_ranks.assert_not_awaited()

    async def test_record_outcome_freezes_the_points_it_applied(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result, points_per_win=25)
        self.ranks.list_layer = AsyncMock(return_value={})

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        self.assertEqual(self.casual_matches.create.await_args.args[1].points_per_win_applied, 25)

    async def test_record_outcome_freezes_nothing_on_a_draw(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced", balance_result_json=result, points_per_win=25)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=None,
            variant_index=0,
            actor_user_id=9,
        )

        self.assertIsNone(self.casual_matches.create.await_args.args[1].points_per_win_applied)

    async def test_undo_a_match_of_another_mix_404(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.undo_last_match(
                self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.session.delete.assert_not_awaited()

    async def test_undo_only_applies_to_the_newest_match(self) -> None:
        self.games.get.return_value = _game()
        self.casual_matches.get_for_game.return_value = _match(501, created_at=1, home=[7], away=[9])
        self.casual_matches.newest_id_for_game.return_value = 502

        with self.assertRaises(HTTPException) as ctx:
            await self.service.undo_last_match(
                self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Only the most recent match can be undone")
        self.session.delete.assert_not_awaited()

    async def test_undo_reverses_the_points_the_match_stored(self) -> None:
        match = _match(
            501,
            created_at=1,
            home=[(7, HeroClass.tank, 3200), (8, HeroClass.damage, 2900)],
            away=[(9, HeroClass.tank, 2600)],
            points_per_win_applied=25,
        )
        # The knob has since been turned up; the rollback must ignore it and
        # give back the 25 that was actually applied.
        self.games.get.return_value = _game(points_per_win=999)
        self.casual_matches.get_for_game.return_value = match
        self.casual_matches.newest_id_for_game.return_value = 501
        self.ranks.list_layer = AsyncMock(return_value={(7, "tank"): 2525, (8, "dps"): 2825, (9, "tank"): 2575})

        await self.service.undo_last_match(
            self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
        )

        calls = {
            (call.kwargs["workspace_member_id"], call.kwargs["author_user_id"], tuple(call.kwargs["ranks"].items()))
            for call in self.ranks.set_ranks.await_args_list
        }
        self.assertEqual(
            calls,
            {
                (7, 9, (("tank", 2500),)),
                (8, 9, (("dps", 2800),)),
                (9, 9, (("tank", 2600),)),
            },
        )
        self.session.delete.assert_awaited_once_with(match)

    async def test_undo_a_draw_deletes_without_touching_ranks(self) -> None:
        match = _match(
            501,
            created_at=1,
            home=[(7, HeroClass.tank, 3200)],
            away=[(9, HeroClass.tank, 2600)],
            scores=(0, 0),
        )
        self.games.get.return_value = _game(points_per_win=25)
        self.casual_matches.get_for_game.return_value = match
        self.casual_matches.newest_id_for_game.return_value = 501

        await self.service.undo_last_match(
            self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
        )

        self.ranks.set_ranks.assert_not_awaited()
        self.session.delete.assert_awaited_once_with(match)

    async def test_list_matches_returns_the_recorded_history(self) -> None:
        self.games.get.return_value = _game()
        matches = [object(), object()]
        self.casual_matches.list_for_custom_game = AsyncMock(return_value=matches)

        result = await self.service.list_matches(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(result, matches)
        self.casual_matches.list_for_custom_game.assert_awaited_once_with(self.session, 11)

    async def test_mix_stats_merges_the_current_roster_into_the_scoreboard(self) -> None:
        played_at = datetime(2026, 3, 1, 21, 30)
        self.casual_matches.seats_for_workspace = AsyncMock(
            return_value=[
                _row(
                    workspace_member_id=7,
                    role=HeroClass.damage,
                    match_id=1,
                    created_at=played_at,
                    own_score=2,
                    other_score=1,
                ),
                _row(
                    workspace_member_id=8,
                    role=None,
                    match_id=1,
                    created_at=played_at,
                    own_score=1,
                    other_score=2,
                ),
            ]
        )
        # Member 8 has left the workspace since that match: the roster read no
        # longer answers for them, but their seat still counted.
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)

        members = await self.service.mix_stats(self.session, workspace_id=1, since=None)

        self.casual_matches.seats_for_workspace.assert_awaited_once_with(self.session, 1, None)
        self.assertEqual(
            members,
            [
                {
                    "workspace_member_id": 7,
                    "display_name": "P7",
                    "battle_tag": "P7#1",
                    "games": 1,
                    "wins": 1,
                    "losses": 0,
                    "draws": 0,
                    "win_rate": 1.0,
                    "streak": 1,
                    "last_played_at": played_at.isoformat(),
                    # The canonical ``damage`` role reaches the wire as ``dps``.
                    "by_role": {"dps": {"games": 1, "wins": 1, "losses": 0, "draws": 0}},
                },
                {
                    "workspace_member_id": 8,
                    "display_name": None,
                    "battle_tag": None,
                    "games": 1,
                    "wins": 0,
                    "losses": 1,
                    "draws": 0,
                    "win_rate": 0.0,
                    "streak": -1,
                    "last_played_at": played_at.isoformat(),
                    # A seat recorded without a role lands in no bucket.
                    "by_role": {},
                },
            ],
        )

    async def test_set_points_per_win_stores_the_value(self) -> None:
        self.games.get.return_value = _game()

        game = await self.service.set_points_per_win(
            self.session, workspace_id=1, custom_game_id=11, points_per_win=25, actor_user_id=9
        )

        self.assertEqual(game.points_per_win, 25)

    async def test_set_points_per_win_touches_no_other_setting(self) -> None:
        self.games.get.return_value = _game(balancer_config_json={"population_size": 200})

        game = await self.service.set_points_per_win(
            self.session, workspace_id=1, custom_game_id=11, points_per_win=10, actor_user_id=9
        )

        self.assertEqual(game.points_per_win, 10)
        self.assertEqual(game.balancer_config_json, {"population_size": 200})
        self.team_names.set.assert_not_awaited()

    async def test_set_points_per_win_null_clears_it(self) -> None:
        self.games.get.return_value = _game(points_per_win=25)

        game = await self.service.set_points_per_win(
            self.session, workspace_id=1, custom_game_id=11, points_per_win=None, actor_user_id=9
        )

        self.assertIsNone(game.points_per_win)

    async def test_set_points_per_win_zero_clears_it(self) -> None:
        self.games.get.return_value = _game(points_per_win=25)

        game = await self.service.set_points_per_win(
            self.session, workspace_id=1, custom_game_id=11, points_per_win=0, actor_user_id=9
        )

        self.assertIsNone(game.points_per_win)

    async def test_set_points_per_win_rejects_out_of_range(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_points_per_win(
                self.session, workspace_id=1, custom_game_id=11, points_per_win=1001, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_set_next_map_stores_a_catalogue_map(self) -> None:
        self.games.get.return_value = _game()
        self.session.get = AsyncMock(return_value=_row(id=42, name="King's Row"))

        game = await self.service.set_next_map(
            self.session, workspace_id=1, custom_game_id=11, map_id=42, actor_user_id=9
        )

        self.assertEqual(game.next_map_id, 42)

    async def test_set_next_map_unknown_map_404(self) -> None:
        self.games.get.return_value = _game()
        self.session.get = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_next_map(
                self.session, workspace_id=1, custom_game_id=11, map_id=999, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_set_discord_channel_stores_the_snowflake(self) -> None:
        self.games.get.return_value = _game()

        game = await self.service.set_discord_channel(
            self.session, workspace_id=1, custom_game_id=11, channel_id=123456789012345678, actor_user_id=9
        )

        self.assertEqual(game.discord_channel_id, 123456789012345678)

    async def test_set_discord_channel_null_clears_it(self) -> None:
        self.games.get.return_value = _game(discord_channel_id=777)

        game = await self.service.set_discord_channel(
            self.session, workspace_id=1, custom_game_id=11, channel_id=None, actor_user_id=9
        )

        self.assertIsNone(game.discord_channel_id)

    async def test_discord_lineup_without_any_channel_409(self) -> None:
        """Neither the mix nor the workspace names one: nothing to post to."""
        self.games.get.return_value = _game(balance_result_json={"variants": [{"teams": []}]})
        self.session.scalar = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.discord_lineup(
                self.session, workspace_id=1, custom_game_id=11, variant_index=0, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Discord channel not configured")

    async def test_discord_lineup_falls_back_to_the_workspace_channel(self) -> None:
        """A mix with no channel of its own posts to the workspace-wide one --
        that setting is the default every host gets without touching anything."""
        self.games.get.return_value = _game(balance_result_json={"variants": [{"teams": []}]})
        self.team_names.mapping_for_game.return_value = {}
        self.casual_matches.activity_for_games = AsyncMock(return_value={})
        self.session.scalar = AsyncMock(return_value={"mix_discord_channel_id": "555"})

        channel_id, _embed = await self.service.discord_lineup(
            self.session, workspace_id=1, custom_game_id=11, variant_index=0, actor_user_id=9
        )

        self.assertEqual(channel_id, 555)

    async def test_discord_lineup_prefers_the_mixs_own_channel(self) -> None:
        """The per-mix override is an admin's deliberate redirect: it wins."""
        self.games.get.return_value = _game(discord_channel_id=777, balance_result_json={"variants": [{"teams": []}]})
        self.team_names.mapping_for_game.return_value = {}
        self.casual_matches.activity_for_games = AsyncMock(return_value={})
        self.session.scalar = AsyncMock(return_value={"mix_discord_channel_id": "555"})

        channel_id, _embed = await self.service.discord_lineup(
            self.session, workspace_id=1, custom_game_id=11, variant_index=0, actor_user_id=9
        )

        self.assertEqual(channel_id, 777)

    async def test_discord_lineup_unknown_variant_404(self) -> None:
        self.games.get.return_value = _game(discord_channel_id=777, balance_result_json={"variants": [{"teams": []}]})

        with self.assertRaises(HTTPException) as ctx:
            await self.service.discord_lineup(
                self.session, workspace_id=1, custom_game_id=11, variant_index=1, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Balance option not found")

    async def test_discord_lineup_describes_the_next_match_of_this_mix(self) -> None:
        """The match number continues the mix's history, and the map is read with
        its gamemode eagerly -- an async session cannot walk that lazily."""
        result = {
            "variants": [
                {"teams": []},
                {
                    "teams": [
                        {"roster": {"Tank": [{"uuid": "1", "name": "Ana", "assigned_rating": 3000}]}},
                        {"roster": {"Tank": [{"uuid": "2", "name": "Bob", "assigned_rating": 2900}]}},
                    ]
                },
            ]
        }
        self.games.get.return_value = _game(
            discord_channel_id=777, next_map_id=42, points_per_win=25, balance_result_json=result
        )
        self.team_names.mapping_for_game.return_value = {0: "Blue"}
        self.casual_matches.activity_for_games = AsyncMock(return_value={11: (3, datetime(2026, 1, 1, 20, 0))})
        self.session.scalar = AsyncMock(return_value=_row(id=42, name="Busan", gamemode=_row(name="Control")))

        channel_id, embed = await self.service.discord_lineup(
            self.session, workspace_id=1, custom_game_id=11, variant_index=1, actor_user_id=9
        )

        self.assertEqual(channel_id, 777)
        self.assertEqual(embed["title"], "Scrim — Match 4")
        self.assertEqual(embed["description"], "Map: Busan · Control")
        self.assertEqual([field["name"] for field in embed["fields"]], ["Blue", "Team 2"])
        self.assertEqual(embed["fields"][0]["value"], "Tank · Ana · 3000")
        self.assertEqual(embed["footer"], {"text": "Points per win: 25"})

    async def test_set_balancer_config_stores_validated_overrides(self) -> None:
        self.games.get.return_value = _game()

        game = await self.service.set_balancer_config(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            balancer_config={"population_size": 200, "generation_count": 300},
            actor_user_id=9,
        )

        self.assertEqual(game.balancer_config_json, {"population_size": 200, "generation_count": 300})

    async def test_set_balancer_config_drops_unknown_keys(self) -> None:
        """Same schema a saved tournament config is validated against: an
        unrecognised key must not reach the solver as a silent override."""
        self.games.get.return_value = _game()

        game = await self.service.set_balancer_config(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            balancer_config={"population_size": 200, "not_a_real_knob": 1},
            actor_user_id=9,
        )

        self.assertEqual(game.balancer_config_json, {"population_size": 200})

    async def test_set_balancer_config_cannot_reach_the_mixs_own_settings(self) -> None:
        """Solver overrides live in their own column now.

        ``points_per_win``, the team names and the role mask are stored facts of
        the mix, so replacing the solver knobs wholesale can no longer disturb
        them -- they are not in the same document any more.
        """
        game = _game(points_per_win=10)
        self.games.get.return_value = game

        await self.service.set_balancer_config(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            balancer_config={"population_size": 200},
            actor_user_id=9,
        )

        self.assertEqual(game.balancer_config_json, {"population_size": 200})
        self.assertEqual(game.points_per_win, 10)
        self.team_names.set.assert_not_awaited()
        self.role_slots.replace.assert_not_awaited()

    async def test_set_balancer_config_null_clears_only_the_solver_knobs(self) -> None:
        game = _game(points_per_win=10, balancer_config_json={"population_size": 200})
        self.games.get.return_value = game

        await self.service.set_balancer_config(
            self.session, workspace_id=1, custom_game_id=11, balancer_config=None, actor_user_id=9
        )

        self.assertIsNone(game.balancer_config_json)
        self.assertEqual(game.points_per_win, 10)

    async def test_balance_forwards_the_stored_balancer_config_to_the_solver(self) -> None:
        """End-to-end wiring: what ``set_balancer_config`` persisted is exactly
        what ``balance`` forwards to the solver -- no filtering step in between,
        because the mix's own settings never shared that column."""
        self.games.get.return_value = _game(points_per_win=10, balancer_config_json={"population_size": 200})
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        _player_data, config_overrides, _progress, _role_mask = self.run_balance.await_args.args
        self.assertEqual(config_overrides, {"population_size": 200})

    async def test_transfer_host_moves_ownership_to_a_workspace_member(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = {21}

        game = await self.service.transfer_host(
            self.session, workspace_id=1, custom_game_id=11, new_host_user_id=21, actor_user_id=9
        )

        self.assertEqual(game.host_user_id, 21)
        self.load_member_user_ids.assert_awaited_once_with(self.session, workspace_id=1, user_ids=[21])
        # The new host is never also a co-host of themselves.
        self.co_hosts.remove.assert_awaited_once_with(self.session, 11, 21)

    async def test_transfer_host_rejects_a_non_member_404(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = set()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.transfer_host(
                self.session, workspace_id=1, custom_game_id=11, new_host_user_id=404, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_transfer_host_requires_the_host_or_a_co_host_403(self) -> None:
        game = _game()
        self.games.get.return_value = game
        # Membership alone never grants a write: the caller is already known to
        # belong to this workspace by the time the service is reached.
        self.co_hosts.user_ids_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.transfer_host(
                self.session, workspace_id=1, custom_game_id=11, new_host_user_id=21, actor_user_id=99
            )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(game.host_user_id, 9)
        self.co_hosts.remove.assert_not_awaited()

    async def test_a_write_reads_the_grant_alone_not_the_roster(self) -> None:
        """A co-host's own membership is settled before the service is called.

        Re-deriving it here from ``workspace_member`` demanded a roster row an
        RBAC-only member (an admin who never plays) does not have, and revoked
        their write access on every mix they co-hosted.
        """
        self.games.get.return_value = _game()
        self.co_hosts.user_ids_for_game.return_value = [21]

        game = await self.service.set_points_per_win(
            self.session, workspace_id=1, custom_game_id=11, points_per_win=10, actor_user_id=21
        )

        self.assertEqual(game.points_per_win, 10)
        self.load_member_user_ids.assert_not_awaited()

    async def test_transfer_host_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.transfer_host(
                self.session, workspace_id=1, custom_game_id=11, new_host_user_id=21, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)

    async def test_transfer_host_to_self_is_a_noop(self) -> None:
        self.games.get.return_value = _game()

        game = await self.service.transfer_host(
            self.session, workspace_id=1, custom_game_id=11, new_host_user_id=9, actor_user_id=9
        )

        self.assertEqual(game.host_user_id, 9)
        self.load_member_user_ids.assert_not_awaited()

    async def test_transfer_host_dedupes_new_host_out_of_co_hosts(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = {21}
        self.co_hosts.user_ids_for_game.return_value = [21, 22]

        game = await self.service.transfer_host(
            self.session, workspace_id=1, custom_game_id=11, new_host_user_id=21, actor_user_id=9
        )

        self.assertEqual(game.host_user_id, 21)
        # Nobody is simultaneously the primary host and a co-host of themselves.
        self.co_hosts.remove.assert_awaited_once_with(self.session, 11, 21)

    async def test_add_co_host_grants_write_access(self) -> None:
        game = _game()
        self.games.get.return_value = game
        self.load_member_user_ids.return_value = {21}

        await self.service.add_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=9
        )
        self.co_hosts.add.assert_awaited_once_with(self.session, 11, 21)

        # The new co-host can now write this mix without being the host.
        self.co_hosts.user_ids_for_game.return_value = [21]
        renamed = await self.service.set_points_per_win(
            self.session, workspace_id=1, custom_game_id=11, points_per_win=10, actor_user_id=21
        )
        self.assertEqual(renamed.points_per_win, 10)

    async def test_add_co_host_rejects_a_non_member_404(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = set()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.add_co_host(
                self.session, workspace_id=1, custom_game_id=11, co_host_user_id=404, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_add_co_host_is_idempotent(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = {21}
        self.co_hosts.user_ids_for_game.return_value = [21]

        await self.service.add_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=9
        )

        self.co_hosts.add.assert_not_awaited()

    async def test_add_co_host_treats_the_current_host_as_a_noop(self) -> None:
        self.games.get.return_value = _game()

        await self.service.add_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=9, actor_user_id=9
        )

        self.co_hosts.add.assert_not_awaited()
        self.load_member_user_ids.assert_not_awaited()

    async def test_add_co_host_enforces_the_cap(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = {21}
        self.co_hosts.user_ids_for_game.return_value = list(range(300, 300 + _MAX_CO_HOSTS))

        with self.assertRaises(HTTPException) as ctx:
            await self.service.add_co_host(
                self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.co_hosts.add.assert_not_awaited()

    async def test_add_co_host_allowed_by_an_existing_co_host(self) -> None:
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = {22}
        self.co_hosts.user_ids_for_game.return_value = [21]

        await self.service.add_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=22, actor_user_id=21
        )

        self.co_hosts.add.assert_awaited_once_with(self.session, 11, 22)

    async def test_add_co_host_requires_the_host_or_a_co_host_403(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.add_co_host(
                self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=99
            )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_remove_co_host_revokes_write_access(self) -> None:
        self.games.get.return_value = _game()
        self.co_hosts.user_ids_for_game.return_value = [21]

        await self.service.remove_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=9
        )
        self.co_hosts.remove.assert_awaited_once_with(self.session, 11, 21)

        self.co_hosts.user_ids_for_game.return_value = []
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_points_per_win(
                self.session, workspace_id=1, custom_game_id=11, points_per_win=10, actor_user_id=21
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_remove_co_host_is_a_noop_for_an_absent_id(self) -> None:
        self.games.get.return_value = _game()
        self.co_hosts.user_ids_for_game.return_value = [21]

        await self.service.remove_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=404, actor_user_id=9
        )

        self.co_hosts.remove.assert_not_awaited()

    async def test_remove_co_host_needs_no_membership_of_its_target(self) -> None:
        """An account that has since left the workspace is still revocable.

        Resolving the target through a membership lookup first stranded the grant
        the moment the member row went away: the revoke silently no-opped and the
        row kept its write access.
        """
        self.games.get.return_value = _game()
        self.load_member_user_ids.return_value = set()
        self.co_hosts.user_ids_for_game.return_value = [21]

        await self.service.remove_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=9
        )

        self.co_hosts.remove.assert_awaited_once_with(self.session, 11, 21)

    async def test_remove_co_host_allows_self_removal(self) -> None:
        self.games.get.return_value = _game()
        self.co_hosts.user_ids_for_game.return_value = [21, 22]

        await self.service.remove_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=21
        )

        self.co_hosts.remove.assert_awaited_once_with(self.session, 11, 21)

    async def test_set_points_per_win_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_points_per_win(
                self.session, workspace_id=1, custom_game_id=11, points_per_win=25, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_set_points_per_win_requires_the_host(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_points_per_win(
                self.session, workspace_id=1, custom_game_id=11, points_per_win=25, actor_user_id=99
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_close_marks_the_mix_completed_without_a_result(self) -> None:
        self.games.get.return_value = _game(status="balanced")

        game = await self.service.close(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual(game.status, "completed")

    async def test_close_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")
        with self.assertRaises(HTTPException) as ctx:
            await self.service.close(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_set_team_names_stores_by_index(self) -> None:
        self.games.get.return_value = _game()

        await self.service.set_team_names(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            team_names={"0": "  Wolves  ", "1": "Bears"},
            actor_user_id=9,
        )

        self.assertEqual(
            [call.args[1:] for call in self.team_names.set.await_args_list],
            [(11, 0, "Wolves"), (11, 1, "Bears")],
        )

    async def test_set_team_names_touches_no_other_setting(self) -> None:
        game = _game(points_per_win=10)
        self.games.get.return_value = game

        await self.service.set_team_names(
            self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=9
        )

        self.assertEqual(game.points_per_win, 10)
        self.role_slots.replace.assert_not_awaited()

    async def test_set_team_names_blank_value_clears_that_index_only(self) -> None:
        self.games.get.return_value = _game()
        self.team_names.mapping_for_game.return_value = {0: "Wolves", 1: "Bears"}

        await self.service.set_team_names(
            self.session, workspace_id=1, custom_game_id=11, team_names={"0": "  "}, actor_user_id=9
        )

        # An empty override reverts index 0 to the computed default rather than
        # being rejected, and index 1 is never mentioned, so it is left alone.
        self.team_names.set.assert_awaited_once_with(self.session, 11, 0, None)

    async def test_set_team_names_rejects_a_non_numeric_index(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_team_names(
                self.session, workspace_id=1, custom_game_id=11, team_names={"first": "Wolves"}, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_set_team_names_rejects_an_out_of_range_index(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_team_names(
                self.session, workspace_id=1, custom_game_id=11, team_names={"8": "Wolves"}, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_set_team_names_rejects_a_name_over_the_length_cap(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_team_names(
                self.session, workspace_id=1, custom_game_id=11, team_names={"0": "x" * 61}, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_set_team_names_terminal_409(self) -> None:
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                self.games.get.return_value = _game(status=status)
                with self.assertRaises(HTTPException) as ctx:
                    await self.service.set_team_names(
                        self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=9
                    )
                self.assertEqual(ctx.exception.status_code, 409)

    async def test_set_team_names_requires_the_host(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_team_names(
                self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=99
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_set_role_mask_stores_the_override(self) -> None:
        self.games.get.return_value = _game()

        await self.service.set_role_mask(
            self.session, workspace_id=1, custom_game_id=11, role_mask={"flex": 6}, actor_user_id=9
        )

        self.role_slots.replace.assert_awaited_once_with(self.session, 11, {"flex": 6})

    async def test_set_role_mask_touches_no_other_setting(self) -> None:
        game = _game(points_per_win=10)
        self.games.get.return_value = game

        await self.service.set_role_mask(
            self.session, workspace_id=1, custom_game_id=11, role_mask={"tank": 1, "flex": 4}, actor_user_id=9
        )

        self.role_slots.replace.assert_awaited_once_with(self.session, 11, {"tank": 1, "flex": 4})
        self.assertEqual(game.points_per_win, 10)
        self.team_names.set.assert_not_awaited()

    async def test_set_role_mask_none_clears_the_override(self) -> None:
        self.games.get.return_value = _game()
        self.role_slots.mapping_for_game.return_value = {"flex": 6}

        await self.service.set_role_mask(
            self.session, workspace_id=1, custom_game_id=11, role_mask=None, actor_user_id=9
        )

        self.role_slots.replace.assert_awaited_once_with(self.session, 11, None)

    async def test_set_role_mask_rejects_an_invalid_shape(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_role_mask(
                self.session, workspace_id=1, custom_game_id=11, role_mask={"healer": 6}, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_set_role_mask_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_role_mask(
                self.session, workspace_id=1, custom_game_id=11, role_mask={"flex": 6}, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_set_role_mask_requires_the_host(self) -> None:
        self.games.get.return_value = _game()
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_role_mask(
                self.session, workspace_id=1, custom_game_id=11, role_mask={"flex": 6}, actor_user_id=99
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_roster_shape_reports_the_override_source(self) -> None:
        self.role_slots.mapping_for_game.return_value = {"flex": 6}

        shape = await self.service.roster_shape(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(shape.slots, {"flex": 6})
        self.assertEqual(shape.source, "tournament")

    async def test_roster_shape_falls_back_to_the_workspace_default(self) -> None:
        self.workspace_roster_slots.return_value = {"tank": 1, "flex": 5}

        shape = await self.service.roster_shape(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(shape.slots, {"tank": 1, "flex": 5})
        self.assertEqual(shape.source, "workspace")

    async def test_roster_shape_falls_back_to_the_builtin_default(self) -> None:
        shape = await self.service.roster_shape(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(shape.slots, {"tank": 1, "dps": 2, "support": 2})
        self.assertEqual(shape.source, "default")

    async def test_balance_uses_the_workspace_default_when_the_mix_has_no_override(self) -> None:
        self.workspace_roster_slots.return_value = {"flex": 6}
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        role_mask = self.run_balance.await_args.args[3]
        self.assertEqual(role_mask, {"flex": 6})

    async def test_balance_mix_override_wins_over_the_workspace_default(self) -> None:
        self.workspace_roster_slots.return_value = {"flex": 6}
        self.games.get.return_value = _game()
        self.role_slots.mapping_for_game.return_value = {"tank": 1, "flex": 4}
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        role_mask = self.run_balance.await_args.args[3]
        self.assertEqual(role_mask, {"tank": 1, "flex": 4})

    async def test_balance_forwards_only_the_solver_document(self) -> None:
        """The mix's own settings were never solver overrides; now they cannot
        even be mistaken for them -- ``balancer_config_json`` is forwarded as-is."""
        game = _game(balancer_config_json={"MMR_DIFF_WEIGHT": 5})
        self.games.get.return_value = game
        self.team_names.mapping_for_game.return_value = {0: "Wolves"}
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        config_overrides = self.run_balance.await_args.args[1]
        self.assertEqual(config_overrides, {"MMR_DIFF_WEIGHT": 5})

    def _seat(self, uuid: str, name: str, rating: float, role: str, **overrides: object) -> dict[str, object]:
        seat = {
            "uuid": uuid,
            "name": name,
            "assigned_rating": rating,
            "role_preferences": [role],
            "is_flex": False,
            "is_captain": False,
            "sub_role": None,
        }
        seat.update(overrides)
        return seat

    def _two_team_result(self) -> dict[str, object]:
        return {
            "variants": [
                {
                    "teams": [
                        {
                            "id": 1,
                            "average_mmr": 3050,
                            "roster": {
                                "tank": [self._seat("p1", "Alpha", 3200, "tank")],
                                "dps": [self._seat("p2", "Bravo", 2900, "dps")],
                            },
                        },
                        {
                            "id": 2,
                            "average_mmr": 2800,
                            "roster": {
                                "tank": [self._seat("p3", "Charlie", 2600, "tank")],
                                "dps": [self._seat("p4", "Delta", 3000, "dps")],
                            },
                        },
                    ],
                    "statistics": {
                        "composite_score": 0.87,
                        "mmr_std_dev": 10.0,
                        "max_total_rating_gap": 50,
                        "off_role_count": 0,
                    },
                    "benched_players": [],
                }
            ]
        }

    async def test_swap_seats_swaps_players_and_recomputes_stats(self) -> None:
        self.games.get.return_value = _game(balance_result_json=self._two_team_result())

        game = await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="p1",
            second_uuid="p3",
            actor_user_id=9,
        )

        teams = game.balance_result_json["variants"][0]["teams"]
        self.assertEqual(teams[0]["roster"]["tank"][0]["uuid"], "p3")
        self.assertEqual(teams[1]["roster"]["tank"][0]["uuid"], "p1")
        # Team 1 is now Charlie(2600)+Bravo(2900) = 5500/2 = 2750; team 2 is
        # now Alpha(3200)+Delta(3000) = 6200/2 = 3100.
        self.assertEqual(teams[0]["average_mmr"], 2750.0)
        self.assertEqual(teams[1]["average_mmr"], 3100.0)
        statistics = game.balance_result_json["variants"][0]["statistics"]
        self.assertEqual(statistics["max_total_rating_gap"], 700.0)
        self.assertAlmostEqual(statistics["mmr_std_dev"], 247.487, places=2)
        self.assertEqual(statistics["off_role_count"], 0)
        # The knee-score is population-relative to the solver's Pareto archive
        # for that run -- meaningless for a single hand-edited arrangement, so
        # a manual swap clears it rather than leaving a now-fabricated number.
        self.assertIsNone(statistics["composite_score"])

    async def test_swap_seats_counts_off_role_after_the_move(self) -> None:
        result = self._two_team_result()
        # Bravo actually prefers tank but was seated at dps -- already off-role
        # before the swap, and moving them must not silently "fix" that count.
        result["variants"][0]["teams"][0]["roster"]["dps"][0]["role_preferences"] = ["tank", "dps"]
        self.games.get.return_value = _game(balance_result_json=result)

        game = await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="p2",
            second_uuid="p4",
            actor_user_id=9,
        )

        statistics = game.balance_result_json["variants"][0]["statistics"]
        self.assertEqual(statistics["off_role_count"], 1)

    async def test_swap_seats_rejects_different_roles(self) -> None:
        self.games.get.return_value = _game(balance_result_json=self._two_team_result())
        with self.assertRaises(HTTPException) as ctx:
            await self.service.swap_seats(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=0,
                first_uuid="p1",
                second_uuid="p4",
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_swap_seats_rejects_the_same_team(self) -> None:
        result = self._two_team_result()
        result["variants"][0]["teams"][0]["roster"]["tank"].append(self._seat("p5", "Echo", 3100, "tank"))
        self.games.get.return_value = _game(balance_result_json=result)
        with self.assertRaises(HTTPException) as ctx:
            await self.service.swap_seats(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=0,
                first_uuid="p1",
                second_uuid="p5",
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_swap_seats_rejects_an_unknown_player(self) -> None:
        self.games.get.return_value = _game(balance_result_json=self._two_team_result())
        with self.assertRaises(HTTPException) as ctx:
            await self.service.swap_seats(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=0,
                first_uuid="p1",
                second_uuid="ghost",
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_swap_seats_rejects_an_out_of_range_variant(self) -> None:
        self.games.get.return_value = _game(balance_result_json=self._two_team_result())
        with self.assertRaises(HTTPException) as ctx:
            await self.service.swap_seats(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=3,
                first_uuid="p1",
                second_uuid="p3",
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_swap_seats_terminal_409(self) -> None:
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                self.games.get.return_value = _game(status=status, balance_result_json=self._two_team_result())
                with self.assertRaises(HTTPException) as ctx:
                    await self.service.swap_seats(
                        self.session,
                        workspace_id=1,
                        custom_game_id=11,
                        variant_index=0,
                        first_uuid="p1",
                        second_uuid="p3",
                        actor_user_id=9,
                    )
                self.assertEqual(ctx.exception.status_code, 409)

    async def test_swap_seats_requires_the_host(self) -> None:
        self.games.get.return_value = _game(balance_result_json=self._two_team_result())
        with self.assertRaises(HTTPException) as ctx:
            await self.service.swap_seats(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=0,
                first_uuid="p1",
                second_uuid="p3",
                actor_user_id=99,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_rotation_returns_empty_list_for_an_empty_pool(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = []

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(recommendations, [])

    async def test_rotation_ranks_pool_by_map_history_and_splits_at_seat_count(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2, pool of 3 -> exactly one seat short next map.
        self.games.get.return_value = _game()
        self.role_slots.mapping_for_game.return_value = {"tank": 1, "dps": 1}
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
        ]
        # Newest-first, as CasualMatchRepository.list_for_custom_game returns it.
        self.casual_matches.list_for_custom_game = AsyncMock(
            return_value=[
                _match(2, created_at=2, home=[9], away=[7]),  # 7 & 9 played, 8 sat
                _match(1, created_at=1, home=[7], away=[8]),  # 7 & 8 played, 9 sat
            ]
        )

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)
        by_id = {rec.member_id: rec for rec in recommendations}

        # 8 sat out the most recent map -- owed the next seat.
        self.assertEqual(by_id[8].status, RotationStatus.MUST_PLAY)
        # 7 played both maps in a row -- longest active streak rests.
        self.assertEqual(by_id[7].status, RotationStatus.SHOULD_REST)
        # 9 fills the remaining seat with no fatigue signal of its own.
        self.assertEqual(by_id[9].status, RotationStatus.NEUTRAL)

    async def test_rotation_ignores_maps_played_before_a_member_joined(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2, pool of 3 -> one seat short.
        self.games.get.return_value = _game()
        self.role_slots.mapping_for_game.return_value = {"tank": 1, "dps": 1}
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=5),  # joined after the only map recorded so far
        ]
        self.casual_matches.list_for_custom_game = AsyncMock(return_value=[_match(1, created_at=1, home=[7], away=[])])

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)
        by_id = {rec.member_id: rec for rec in recommendations}

        # 9 has no history yet (joined after the only recorded map) -- no
        # fatigue penalty, plain tie-break fills the last seat with it.
        self.assertEqual(by_id[9].games_played, 0)
        self.assertEqual(by_id[9].consecutive_sat, 0)
        self.assertEqual(by_id[9].status, RotationStatus.NEUTRAL)
        # 8 sat out the map it was eligible for -- owed the other seat.
        self.assertEqual(by_id[8].status, RotationStatus.MUST_PLAY)
        # 7 is the only one who actually played -- rests to make room.
        self.assertEqual(by_id[7].status, RotationStatus.SHOULD_REST)

    async def test_hard_delete_removes_the_game_row(self) -> None:
        game = _game()
        self.games.get.return_value = game
        self.games.delete = AsyncMock()

        await self.service.hard_delete(self.session, workspace_id=1, custom_game_id=11)

        self.games.delete.assert_awaited_once_with(self.session, game)

    async def test_hard_delete_404s_a_game_from_another_workspace(self) -> None:
        self.games.get.return_value = _game(workspace_id=2)
        self.games.delete = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.hard_delete(self.session, workspace_id=1, custom_game_id=11)
        self.assertEqual(ctx.exception.status_code, 404)
        self.games.delete.assert_not_awaited()
