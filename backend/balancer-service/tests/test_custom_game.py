from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import ANY, AsyncMock, MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


import sqlalchemy as sa  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from shared import models  # noqa: E402
from shared.core.enums import (  # noqa: E402
    MixParticipation,
    MixRoleSelectionMode,
    MixStatus,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.core.social import SocialProvider  # noqa: E402
from shared.disciplines import DISCIPLINES  # noqa: E402
from shared.division_grid import ladder_grid  # noqa: E402
from shared.domain.member_rank import ResolvedRank  # noqa: E402
from shared.domain.roles import UnknownRole  # noqa: E402
from shared.domain.roster_shape import RosterShape  # noqa: E402
from shared.domain.team_format import TeamFormat, slot_shape  # noqa: E402
from shared.schemas.identity import PlayerIdentityRead  # noqa: E402
from shared.schemas.role import RoleRef  # noqa: E402
from shared.schemas.roster_slots import RosterShapeRead  # noqa: E402
from shared.services import (
    discord_messages,  # noqa: E402
    ontology,  # noqa: E402
)
from shared.services.discord_errors import DiscordUnavailable  # noqa: E402
from shared.services.member_rank import MIX_ORDER  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from shared.tests.test_team_format import OW_5V5, _module_ontology  # noqa: E402
from src.domain.balancer.result_serializer import lobby_document  # noqa: E402
from src.domain.mix_lobbies import seated_member_ids, with_captains  # noqa: E402
from src.domain.mix_ranker import Ranker  # noqa: E402
from src.domain.mix_self_service import MAX_ROSTER  # noqa: E402
from src.services import custom_game as custom_game_module
from src.services.custom_game import _MAX_CO_HOSTS, CustomGameService  # noqa: E402
from src.services.mix_rounds import MixResultDraft  # noqa: E402
from src.services.workspace_roster import RosterMember  # noqa: E402
from tests.mix_ranker_fakes import in_memory_ranker  # noqa: E402


def _session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
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
        "lobby_pin": None,
        "away": False,
        "created_at": None,
        "updated_at": None,
    }
    fields.update(overrides)
    fields["role_selection_mode"] = (
        MixRoleSelectionMode.ALL_RANKED if fields["roles"] is None else MixRoleSelectionMode.EXPLICIT
    )
    return _row(**fields)


def _round(
    round_id: int,
    *,
    created_at: int,
    first: list[int],
    second: list[int],
    scores: tuple[float, float] = (1.0, 0.0),
    busy: Sequence[int] = (),
    lobby_index: int = 0,
    points_per_win_applied: int | None = None,
) -> SimpleNamespace:
    """One recorded round as ``CustomGameRoundRepository.list_for_custom_game`` returns it."""
    return _row(
        encounter_id=round_id,
        lobby_index=lobby_index,
        points_per_win_applied=points_per_win_applied,
        encounter=_row(
            id=round_id,
            created_at=created_at,
            teams=[_row(slot=1, name="Team 1", score=scores[0]), _row(slot=2, name="Team 2", score=scores[1])],
            games=[_row(map_id=None)],
            result_audit=[_row(actor_user_id=70)],
        ),
        members=[_row(workspace_member_id=m, busy=False) for m in (*first, *second)]
        + [_row(workspace_member_id=m, busy=True) for m in busy],
    )


def _seats(first: list[tuple], second: list[tuple], scores: tuple[float, float] = (1.0, 0.0)) -> list[SimpleNamespace]:
    """``CustomGameRoundRepository.seats`` rows for one round; a seat is ``(member, role, rank[, delta])``."""
    rows = []
    for slot, (team, own, other) in enumerate(((first, scores[0], scores[1]), (second, scores[1], scores[0])), start=1):
        for member, role, rank, *delta in team:
            rows.append(
                _row(
                    slot=slot,
                    workspace_member_id=member,
                    role=role,
                    rank=rank,
                    rank_delta_applied=delta[0] if delta else None,
                    own_score=own,
                    other_score=other,
                )
            )
    return rows


def _game(**overrides) -> SimpleNamespace:
    fields = {
        "id": 11,
        "workspace_id": 1,
        "host_user_id": 9,
        "name": "Scrim",
        "status": "draft",
        "lobby_count": 1,
        "self_signup": "closed",
        "self_role_edit": False,
        "hero_ban_preset": None,
        "hero_fearless": False,
        "hero_ban_seconds": None,
        "hero_pick_seconds": None,
        "hero_free_order": False,
        "hero_captains_only": False,
        "team_formation": "balance",
        "draft_pick_seconds": 30,
        "general_voice_channel_id": None,
        "discipline": "overwatch",
        "scoring_rule_id": 5,
        "created_at": None,
        "updated_at": None,
    }
    fields.update(overrides)
    return _row(**fields)


def _lobby(lobby_index: int = 0, **overrides) -> SimpleNamespace:
    """One ``mix.lobby`` row: everything one match is about."""
    fields = {
        "custom_game_id": 11,
        "lobby_index": lobby_index,
        "selected_variant_index": 0,
        "balance_result_json": None,
        "balance_result_version": 1,
        "next_map_id": None,
        "lobby_code": None,
        "balanced_at": None,
        "live_encounter_id": None,
        "team1_voice_channel_id": None,
        "team2_voice_channel_id": None,
    }
    fields.update(overrides)
    return _row(**fields)


def _channel(channel_id: str, name: str, kind: str, **overrides) -> dict[str, object]:
    """One row of ``DiscordClient.guild_channels``."""
    return {
        "id": channel_id,
        "name": name,
        "type": kind,
        "category_id": None,
        "missing_permissions": None,
        **overrides,
    }


def _discord(*channels: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(guild_channels=AsyncMock(return_value=list(channels)))


def _seated(*teams: list[tuple[int, str]]) -> dict[str, object]:
    """One balanced option of a lobby: each team's seats as ``(member_id, name)``."""
    return lobby_document(
        [
            {
                "teams": [
                    {"roster": {"tank": [{"uuid": str(member_id), "name": name} for member_id, name in team]}}
                    for team in teams
                ]
            }
        ]
    )


def _prefs(**overrides) -> SimpleNamespace:
    """The host's solver and rating knobs, never the mix's team format."""
    fields = {
        "config_json": {},
        "points_per_win": None,
        "rating_mode": "points",
        "hero_ban_presets": {},
        "formation_defaults": {},
    }
    fields.update(overrides)
    return _row(**fields)


def _members(*member_ids: int) -> dict[int, RosterMember]:
    """The roster rows ``workspace_roster.list_roster`` would return."""
    return {
        member_id: RosterMember(
            member_id=member_id,
            player_id=member_id * 10,
            identity=PlayerIdentityRead.of(SocialProvider.BATTLENET, f"P{member_id}#1"),
            display_name=f"P{member_id}",
        )
        for member_id in member_ids
    }


def _ranks(*member_ids: int) -> dict[tuple[int, str], ResolvedRank]:
    out: dict[tuple[int, str], ResolvedRank] = {}
    for member_id in member_ids:
        out[(member_id, "tank")] = ResolvedRank(2500, "workspace")
        out[(member_id, "damage")] = ResolvedRank(2400, "workspace")
        out[(member_id, "support")] = ResolvedRank(2300, "workspace")
    return out


def _auth(user_id: int = 42, *, denied: bool = False) -> SimpleNamespace:
    """The gateway-rehydrated identity a self-service call carries."""
    return SimpleNamespace(
        id=user_id,
        is_superuser=False,
        can_capability=lambda _resource, _action, workspace_id=None: not denied,
    )


class _MessageRepo:
    """``discord_message`` as a list, standing in for the real repository.

    Only what a mix does with it: claim a row, read a subject's rows back and
    move one through the guarded ``mark_*`` states. Everything above it -- which
    rows get a delete command, what a command carries -- is the real
    ``shared.services.discord_messages``, which is the half worth testing.
    """

    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []
        self._next_id = 100

    def add(self, **fields) -> SimpleNamespace:
        """A message this mix already sent, as the database would have it."""
        self._next_id += 1
        row = _row(
            **{
                "id": self._next_id,
                "channel": "discord_channel",
                "target": "555",
                "kind": "mix.signup",
                "workspace_id": 1,
                "notification_id": None,
                "payload_json": None,
                "error": None,
                **fields,
            }
        )
        self.rows.append(row)
        return row

    async def claim(self, _session, *, dedupe_key=None, **fields) -> int:
        return self.add(status="pending", **fields).id

    async def for_subject(self, _session, subject, *, slot=None, statuses=None) -> list[SimpleNamespace]:
        return [
            row
            for row in self.rows
            if row.subject == subject
            and (slot is None or row.slot == slot)
            and (statuses is None or row.status in statuses)
        ]

    async def get(self, _session, row_id) -> SimpleNamespace | None:
        return next((row for row in self.rows if row.id == row_id), None)

    async def mark_deleting(self, _session, row_id) -> bool:
        row = await self.get(_session, row_id)
        if row.status not in ("pending", "posted"):
            return False
        row.status = "deleting"
        return True

    async def mark_deleted(self, _session, row_id) -> bool:
        row = await self.get(_session, row_id)
        if row.status not in ("pending", "posted", "deleting", "failed"):
            return False
        row.status = "deleted"
        return True


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
        self.mix_rounds = MagicMock()
        # No round history recorded unless a test says otherwise -- `balance`'s
        # rotation-priority read and `rotation()` itself both need this to resolve
        # to something awaitable by default.
        self.mix_rounds.list_for_custom_game = AsyncMock(return_value=[])
        # Nothing to undo unless a test records something.
        self.mix_rounds.get_for_game = AsyncMock(return_value=None)
        self.mix_rounds.newest_id_for_lobby = AsyncMock(return_value=None)
        self.mix_rounds.activity_for_lobbies = AsyncMock(return_value={})
        self.mix_rounds.seats = AsyncMock(return_value=[])
        self.mix_rounds.delete_round = AsyncMock()
        # Start answers with the open encounter it wrote; Record writes the result onto it.
        self.open_match = AsyncMock(return_value=_row(id=900))
        self.write_result = AsyncMock()
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
        # ``mix.lobby`` as a dict keyed by lobby_index: a fresh
        # mix has exactly one row, and a test that needs lobby B assigns
        # ``self.lobby_rows[1] = _lobby(1, ...)``.
        self.lobby_rows: dict[int, SimpleNamespace] = {0: _lobby(0)}
        self.lobbies = MagicMock()
        self.lobbies.list_for_game = AsyncMock(
            side_effect=lambda _s, _gid: [self.lobby_rows[index] for index in sorted(self.lobby_rows)]
        )
        self.lobbies.get = AsyncMock(side_effect=lambda _s, _gid, index: self.lobby_rows.get(index))
        self.lobbies.create = AsyncMock(side_effect=lambda _s, row: self.lobby_rows.setdefault(row.lobby_index, row))
        self.lobbies.delete = AsyncMock(side_effect=lambda _s, row: self.lobby_rows.pop(row.lobby_index, None))
        # No lobby's match is timed or in its ban room unless a test says otherwise.
        self.lobbies.live_started_at = AsyncMock(return_value={})
        self.lobbies.pregame_ids = AsyncMock(return_value=frozenset())
        # The host's own row: solver knobs, roster shape and points per win.
        # Nobody has saved one unless a test says otherwise -- the mix then
        # balances on the engine defaults, fields the workspace/built-in roster
        # shape and records matches without touching any rank.
        self.host_prefs = MagicMock()
        self.host_prefs.get_by_user = AsyncMock(return_value=None)
        # The map catalogue: every id resolves unless a test says otherwise.
        self.maps = MagicMock()
        self.maps.exists = AsyncMock(return_value=True)
        self.maps.get_map_with_mode = AsyncMock(return_value=None)
        self.maps.count = AsyncMock(return_value=2)
        self.roster.list_for_game = AsyncMock(return_value=[])
        self.roster.get_by = AsyncMock(return_value=None)
        self.roster.delete = AsyncMock()
        # A single-row insert: `self_join` seats one player, unlike the host's
        # bulk `create_many`, and needs an id for the role child table.
        self.roster.create = AsyncMock(side_effect=lambda _s, row: row)
        # The self-service identity chain: auth account -> players.user ->
        # workspace_member. Linked and enrolled unless a test says otherwise.
        self.players = MagicMock()
        self.players.get_by_auth_user_id = AsyncMock(return_value=_row(id=70, auth_user_id=42))
        self.players.get_id_by_auth_user_id = AsyncMock(return_value=70)
        self.workspace_members = MagicMock()
        self.workspace_members.get_by_player = AsyncMock(return_value=None)
        # Nobody linked a Discord unless a test says otherwise.
        self.workspace_members.discord_ids = AsyncMock(return_value=[])
        # The workspace saved no balancer config (no mix channel, no voices) unless a test says otherwise.
        self.workspace_configs = MagicMock()
        self.workspace_configs.get_by_workspace = AsyncMock(return_value=None)
        self.workspace_configs.config_with_guild = AsyncMock(return_value=None)
        # Both required OAuth links present unless a test removes one.
        self.load_missing_links = AsyncMock(return_value=frozenset())
        self.enroll_member = AsyncMock(
            side_effect=lambda _s, *, workspace_id, player_id: _row(id=7, player_id=player_id)
        )
        self.grant_player_role = AsyncMock()
        self.emit = AsyncMock()
        self._emit_patch = patch("src.services.custom_game.emit_pickup_mix_changed", new=self.emit)
        self._emit_patch.start()
        self.addCleanup(self._emit_patch.stop)
        # The one table every Discord message of this mix lives in. Empty by
        # default: the mix has never posted anything.
        self.messages = _MessageRepo()
        self._messages_patch = patch.object(discord_messages, "repository", self.messages)
        self._messages_patch.start()
        self.addCleanup(self._messages_patch.stop)
        # Every requested member exists in this workspace unless a test says otherwise.
        self.load_roster = AsyncMock(
            side_effect=lambda _s, *, workspace_id, provider, member_ids: _members(*member_ids)
        )
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
        # The workspace grid feeds only a ladderless game's rank resolution (mocked above); its tiers are bare
        # numbers, which is why the seat badge does not come from it (see test_self_state_badges_...).
        self.grid = SimpleNamespace(resolve_division=lambda _rank: _row(name="Division 1", slug="division-1"))
        self._grid_patch = patch(
            "src.services.custom_game.get_effective_division_grid",
            new=AsyncMock(return_value=self.grid),
        )
        self.grid_lookup = self._grid_patch.start()
        self.addCleanup(self._grid_patch.stop)
        self.slot_shape = AsyncMock(return_value=RosterShape(entries=(("tank", 1), ("damage", 2), ("support", 2))))
        self.format_lookup = AsyncMock(return_value=(OW_5V5, "custom_game"))
        self.format_read = AsyncMock(
            return_value=SimpleNamespace(
                roster_shape=RosterShapeRead.from_shape(self.slot_shape.return_value, source="custom_game")
            )
        )
        for target, mock in (
            ("custom_game_slot_shape", self.slot_shape),
            ("custom_game_format", self.format_lookup),
            ("team_format_read", self.format_read),
            ("copy_for_custom_game", AsyncMock()),
        ):
            patcher = patch(f"src.services.custom_game.{target}", new=mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        ontology_patch = patch(
            "src.services.custom_game.CatalogRoleRepository.ontology",
            new=AsyncMock(return_value=_module_ontology("overwatch")),
        )
        ontology_patch.start()
        self.addCleanup(ontology_patch.stop)
        # The real ranker over dicts: the hidden book advances on every recorded
        # match and is empty unless a test seeds ``self.ranker.hidden.book``.
        self.ranker = in_memory_ranker()
        self.scoring_rules = MagicMock()
        self.scoring_rules.create = AsyncMock(side_effect=lambda _s, row: setattr(row, "id", 5) or row)
        self.scoring_rules.get = AsyncMock(return_value=None)
        self.scoring_rules.delete = AsyncMock()
        self.drafts = SimpleNamespace(
            active_lobby_pools=AsyncMock(return_value={}),
            active_for_custom_game=AsyncMock(return_value=[]),
            first_clock_starts=AsyncMock(return_value={}),
        )
        self.service = CustomGameService(
            games=self.games,
            workspaces=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(disciplines_enabled=["overwatch"]))),
            roster=self.roster,
            co_hosts=self.co_hosts,
            lobbies=self.lobbies,
            player_roles=self.player_roles,
            team_names=self.team_names,
            mix_rounds=self.mix_rounds,
            open_match=self.open_match,
            write_result=self.write_result,
            maps=self.maps,
            host_prefs=self.host_prefs,
            ranks=self.ranks,
            scoring_rules=self.scoring_rules,
            load_roster=self.load_roster,
            load_hosts=self.load_hosts,
            load_member_user_ids=self.load_member_user_ids,
            run_balance=self.run_balance,
            players=self.players,
            workspace_members=self.workspace_members,
            workspace_configs=self.workspace_configs,
            load_missing_links=self.load_missing_links,
            enroll_member=self.enroll_member,
            grant_player_role=self.grant_player_role,
            ranker=self.ranker,
            drafts=self.drafts,
        )
        self.session = _session()

        async def resolve_catalog_role(_session, *, code, workspace_id, **_kwargs):
            if code not in ("tank", "damage", "support"):
                raise UnknownRole(code)
            return models.CatalogRole(code=code, parent_role_id=None, workspace_id=None)

        self.catalog_resolve = AsyncMock(side_effect=resolve_catalog_role)
        self.enterContext(patch.object(ontology._roles, "resolve", self.catalog_resolve))

    async def test_entity_read_resolves_owner_but_explicit_workspace_still_isolates(self) -> None:
        game = _game(workspace_id=2)
        self.games.get.return_value = game
        self.assertIs(
            await self.service.get(self.session, workspace_id=None, custom_game_id=game.id),
            game,
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service.get(self.session, workspace_id=1, custom_game_id=game.id)
        self.assertEqual(ctx.exception.status_code, 404)
        self.co_hosts.user_ids_for_game.assert_not_awaited()

    def _discord_links(self, by_member: dict[int, str]) -> None:
        """The one batched read behind ``discord_mentions``: member id -> snowflake."""
        self.workspace_members.discord_ids.return_value = list(by_member.items())

    def _channel(self, channel_id: str) -> None:
        """The workspace's mix channel, as its balancer blob stores it."""
        self.workspace_configs.get_by_workspace.return_value = _row(config_json={"mix_discord_channel_id": channel_id})

    def _voice_config(self, blob: dict[str, object] | None, guild_id: str | None) -> None:
        """The one row behind ``voice_config``: the workspace's balancer blob and its guild."""
        self.workspace_configs.config_with_guild.return_value = (blob, guild_id)

    def _voice_reads(self, blob: dict[str, object] | None, guild_id: str | None, links: dict[int, str]) -> None:
        """The two reads a move makes: the workspace's voice config, then the seats' Discord links."""
        self._voice_config(blob, guild_id)
        self._discord_links(links)

    @staticmethod
    async def _assign_id(_session, row):
        if getattr(row, "id", None) is None:
            row.id = 11
        return row

    def _draft(self) -> MixResultDraft:
        return self.write_result.await_args.args[1]

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
            discipline="overwatch",
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
        await self.service.create(
            self.session, workspace_id=1, discipline="overwatch", host_user_id=9, name="Scrim", actor_user_id=9
        )
        self.roster.create_many.assert_not_called()

    async def test_create_opens_the_mixs_own_wins_rule(self) -> None:
        game = await self.service.create(
            self.session, workspace_id=1, discipline="overwatch", host_user_id=9, name="Scrim", actor_user_id=9
        )

        rule = self.scoring_rules.create.await_args.args[1]
        self.assertEqual((rule.workspace_id, rule.preset, rule.game_formula), (1, "wins", "win"))
        self.assertEqual(rule.end_formula, "games >= best_of or max_wins * 2 > best_of")
        self.assertEqual(game.scoring_rule_id, 5)

    async def test_member_of_another_workspace_404(self) -> None:
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)
        with self.assertRaises(HTTPException) as ctx:
            await self.service.create(
                self.session,
                workspace_id=1,
                discipline="overwatch",
                host_user_id=9,
                name="Scrim",
                actor_user_id=9,
                member_ids=[7, 8],
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.games.create.assert_not_called()

    async def test_create_clones_a_previous_mix(self) -> None:
        source = _game(id=5, status="completed")
        self.games.get.return_value = source
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, participation=MixParticipation.BENCHED, roles=["tank", "damage"], is_flex=True),
            _roster_row(2, 8, 1, participation=MixParticipation.MUST_PLAY),
        ]
        self.roster.create_many = AsyncMock(side_effect=self._assign_roster_ids)
        self.team_names.mapping_for_game.return_value = {0: "Wolves", 1: "Ravens"}
        self.co_hosts.user_ids_for_game.return_value = [4, 9]

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
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
        self.player_roles.replace_for_player.assert_awaited_once_with(
            self.session, 101, ["tank", "damage"], discipline="overwatch"
        )
        # No shape and no points knob travel: they are not the mix's to copy,
        # they live on the host's account and the new mix already reads them.
        self.assertEqual(
            [call.args for call in self.team_names.set.await_args_list],
            [(self.session, game.id, 0, "Wolves"), (self.session, game.id, 1, "Ravens")],
        )
        # The new host is never also their own co-host.
        self.co_hosts.add.assert_awaited_once_with(self.session, game.id, 4)
        # Nothing that describes a played session travels.
        self.assertEqual(game.status, "draft")
        created = self.lobbies.create.await_args.args[1]
        self.assertEqual(created.lobby_index, 0)
        self.assertIsNone(created.balance_result_json)
        self.assertIsNone(created.next_map_id)

    async def test_create_clone_drops_members_who_left_the_workspace(self) -> None:
        self.games.get.return_value = _game(id=5)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 8, 1)]
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)

        await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Scrim 2",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        rows = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.workspace_member_id for row in rows], [7])

    async def test_create_clone_copies_the_role_edit_switch_but_closes_signup(self) -> None:
        """A clone is a NEW session: whoever the host let edit their own roles
        keeps that, but the signup window reopens by hand, never by inheritance."""
        source = _game(id=5, self_signup="pool", self_role_edit=True)
        self.games.get.return_value = source
        self.roster.list_for_game.return_value = []

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Rematch",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertTrue(game.self_role_edit)
        self.assertEqual(game.self_signup, "closed")

    async def test_create_starts_with_the_hosts_ban_default_for_its_game(self) -> None:
        self.host_prefs.get_by_user.return_value = _prefs(
            hero_ban_presets={"overwatch": "hero_classic", "deadlock": "deadlock_hero_bans"}
        )

        game = await self.service.create(
            self.session, workspace_id=1, discipline="overwatch", host_user_id=9, name="Scrim", actor_user_id=9
        )

        self.assertEqual("hero_classic", game.hero_ban_preset)

    async def test_create_clone_keeps_its_sources_ban_preset_over_the_host_default(self) -> None:
        self.games.get.return_value = _game(id=5, hero_ban_preset=None)
        self.roster.list_for_game.return_value = []
        self.host_prefs.get_by_user.return_value = _prefs(hero_ban_presets={"overwatch": "hero_classic"})

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Rematch",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertIsNone(game.hero_ban_preset)

    async def test_create_clone_copies_the_lobby_layout(self) -> None:
        """Two lobbies and who is pinned where are how this host runs the
        session; the matchups and the history are last session's."""
        self.games.get.return_value = _game(id=5, lobby_count=2)
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, lobby_pin=1),
            _roster_row(2, 8, 1),
        ]
        self.roster.create_many = AsyncMock(side_effect=self._assign_roster_ids)

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Scrim 2",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertEqual(game.lobby_count, 2)
        rows = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.lobby_pin for row in rows], [1, None])
        created = [call.args[1] for call in self.lobbies.create.await_args_list]
        self.assertEqual([lobby.lobby_index for lobby in created], [0, 1])
        self.assertTrue(all(lobby.balance_result_json is None for lobby in created))

    async def test_create_clone_of_another_workspace_404(self) -> None:
        self.games.get.return_value = _game(id=5, workspace_id=2)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.create(
                self.session,
                workspace_id=1,
                discipline="overwatch",
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
        # The matchup is a fact about a lobby, not about the mix: a single-lobby
        # mix is simply lobby 0, so the document, the pager and the moment it
        # was balanced land on that row.
        lobby = self.lobby_rows[0]
        self.assertIs(lobby.balance_result_json, payload)
        self.assertEqual(lobby.selected_variant_index, 0)
        self.assertIsNotNone(lobby.balanced_at)
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
        self.assertIs(kwargs["grid"], ladder_grid("overwatch"))
        # The resolver keys off member ids and needs the player behind each one
        # to reach an Overwatch snapshot.
        self.assertEqual(kwargs["members"], {7: 70})

    async def test_balance_names_players_from_the_roster(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 8, 1)]
        self.load_roster.side_effect = None
        self.load_roster.return_value = {
            7: RosterMember(
                member_id=7,
                player_id=70,
                identity=PlayerIdentityRead.of(SocialProvider.BATTLENET, "Ana#1"),
                display_name=None,
            ),
            8: RosterMember(member_id=8, player_id=80, identity=None, display_name=None),
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
                patch={"roles": [{"dimension": "player_role", "role": role} for role in ("tank", "healer")]},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("unknown_role", ctx.exception.detail)
        self.player_roles.replace_for_player.assert_not_awaited()

    async def test_mix_role_ref_rejects_another_disciplines_dimension(self) -> None:
        self.games.get.return_value = _game(discipline="lol")
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"roles": [{"dimension": "player_role", "role": "support"}]},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("role_dimension_mismatch", ctx.exception.detail)
        self.catalog_resolve.assert_not_awaited()
        self.player_roles.replace_for_player.assert_not_awaited()

    async def test_mix_role_ref_rejects_a_sub_role_even_with_a_supplied_parent(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.catalog_resolve.side_effect = None
        self.catalog_resolve.return_value = models.CatalogRole(code="support_main", parent_role_id=10)
        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"roles": [{"dimension": "player_role", "role": "support_main", "parent": "support"}]},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("unknown_role", ctx.exception.detail)
        self.assertIsNone(self.catalog_resolve.await_args.kwargs["workspace_id"])
        self.player_roles.replace_for_player.assert_not_awaited()

    async def test_update_player_keeps_stored_balance(self) -> None:
        """A lineup edit must not blow away the last balance -- only pressing
        Balance teams again should replace it."""
        game = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": []})
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
        self.assertEqual(self.lobby_rows[0].balance_result_json, {"variants": []})
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

    async def test_update_player_refuses_full_flex_in_a_game_without_it_but_clears_a_stored_one(self) -> None:
        row = _roster_row(1, 7, 0, is_flex=True)
        self.games.get.return_value = _game(discipline="deadlock")
        self.roster.list_for_game.return_value = [row]

        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"roles": [{"dimension": "agent", "role": "agent"}], "is_flex": True},
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "full_flex_unsupported")
        # Refused before anything is written: the role order is untouched too.
        self.player_roles.replace_for_player.assert_not_awaited()

        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"is_flex": False},
            actor_user_id=9,
        )
        self.assertFalse(row.is_flex)

    async def test_update_player_pins_a_player_to_a_lobby(self) -> None:
        game = _game(lobby_count=2)
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]

        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"lobby_pin": 1},
            actor_user_id=9,
        )

        self.assertEqual(row.lobby_pin, 1)

    async def test_update_player_clears_a_pin_back_to_auto(self) -> None:
        game = _game(lobby_count=2)
        row = _roster_row(1, 7, 0, lobby_pin=0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]

        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"lobby_pin": None},
            actor_user_id=9,
        )

        self.assertIsNone(row.lobby_pin)

    async def test_update_player_refuses_a_pin_in_a_one_lobby_mix_422(self) -> None:
        """There is nothing to pin to: the mix runs one lobby."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [row]

        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"lobby_pin": 1},
                actor_user_id=9,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(row.lobby_pin)

    async def test_set_lobby_count_four_opens_the_three_missing_lobbies(self) -> None:
        game = _game()
        self.games.get.return_value = game

        await self.service.set_lobby_count(
            self.session, workspace_id=1, custom_game_id=11, lobby_count=4, actor_user_id=9
        )

        self.assertEqual(game.lobby_count, 4)
        self.assertEqual(sorted(self.lobby_rows), [0, 1, 2, 3])
        self.assertIsNone(self.lobby_rows[3].balance_result_json)

    async def test_set_lobby_count_down_drops_the_lobbies_past_it_and_their_pins(self) -> None:
        """Shrinking loses the dropped lobbies' matchups and frees the pins that
        named them: a pin to a lobby that no longer exists would silently exclude
        that player from the next balance. A pin to a surviving lobby stays."""
        game = _game(lobby_count=4)
        for index in (1, 2, 3):
            self.lobby_rows[index] = _lobby(index, balance_result_json={"variants": []})
        dropped = _roster_row(1, 7, 0, lobby_pin=2)
        kept = _roster_row(2, 8, 1, lobby_pin=1)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [dropped, kept]

        await self.service.set_lobby_count(
            self.session, workspace_id=1, custom_game_id=11, lobby_count=2, actor_user_id=9
        )

        self.assertEqual(game.lobby_count, 2)
        self.assertEqual(sorted(self.lobby_rows), [0, 1])
        self.assertIsNone(dropped.lobby_pin)
        self.assertEqual(kept.lobby_pin, 1)

    async def test_set_lobby_count_to_the_current_value_changes_nothing(self) -> None:
        game = _game()
        self.games.get.return_value = game

        await self.service.set_lobby_count(
            self.session, workspace_id=1, custom_game_id=11, lobby_count=1, actor_user_id=9
        )

        self.lobbies.create.assert_not_awaited()
        self.lobbies.delete.assert_not_awaited()

    async def test_set_lobby_count_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_lobby_count(
                self.session, workspace_id=1, custom_game_id=11, lobby_count=2, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 409)

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

    async def test_self_join_seats_a_newcomer_in_the_pool(self) -> None:
        """The signup mode decides where they land; the row is an ordinary
        roster row, so the board and the host sheet need no second list."""
        seated: list = []
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.side_effect = lambda _s, _game_id: list(seated)
        self.roster.create.side_effect = lambda _s, row: seated.append(row) or row
        self.workspace_members.get_by_player.side_effect = [None, _row(id=7, player_id=70)]

        state = await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        [created] = seated
        self.assertEqual(created.workspace_member_id, 7)
        self.assertEqual(created.participation, MixParticipation.POOL)
        self.assertEqual(created.role_selection_mode, MixRoleSelectionMode.ALL_RANKED)
        self.assertEqual(created.sort_order, 0)
        self.enroll_member.assert_awaited_once()
        self.grant_player_role.assert_awaited_once_with(self.session, user_id=42, workspace_id=1, role_name="player")
        self.assertEqual(self.emit.await_args.kwargs["change"], "roster")
        self.assertEqual(state["seat"]["participation"], MixParticipation.POOL)
        self.assertEqual(state["policy"]["join_blocker"], "already_joined")

    async def test_self_join_benched_mode_parks_the_newcomer(self) -> None:
        self.games.get.return_value = _game(self_signup="benched")
        self.roster.list_for_game.return_value = []

        await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        (_session_arg, created), _kwargs = self.roster.create.await_args
        self.assertEqual(created.participation, MixParticipation.BENCHED)

    async def test_self_join_is_idempotent_and_never_unbenches(self) -> None:
        """A host benched them on purpose; clicking Join again must not walk
        that back, and must not 409 either."""
        row = _roster_row(1, 7, 0, participation=MixParticipation.BENCHED)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        state = await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.roster.create.assert_not_awaited()
        self.assertEqual(row.participation, MixParticipation.BENCHED)
        self.assertEqual(state["seat"]["participation"], MixParticipation.BENCHED)
        self.assertEqual(state["policy"]["join_blocker"], "already_joined")

    async def test_self_join_a_lost_race_answers_with_the_seated_state(self) -> None:
        """Two clicks land on uq_custom_game_player_member; the loser reports
        the row the winner wrote instead of a 500."""
        seated = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.side_effect = [[], [seated], [seated]]
        self.roster.create.side_effect = IntegrityError("insert", {}, Exception("duplicate key"))
        self.workspace_members.get_by_player.side_effect = [None, _row(id=7, player_id=70)]

        state = await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(state["policy"]["join_blocker"], "already_joined")
        self.assertIsNotNone(state["seat"])

    async def test_self_join_without_battlenet_403(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []
        self.load_missing_links.return_value = frozenset({"battlenet"})

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "battlenet_not_linked")
        self.roster.create.assert_not_awaited()

    async def test_self_join_when_the_host_closed_signup_409(self) -> None:
        self.games.get.return_value = _game(self_signup="closed")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "signup_closed")

    async def test_self_join_on_a_finished_mix_409(self) -> None:
        self.games.get.return_value = _game(status="completed", self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "mix_closed")

    async def test_self_join_on_a_full_roster_409(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = [
            _roster_row(index + 1, index + 100, index) for index in range(MAX_ROSTER)
        ]

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "roster_full")

    async def test_self_join_denied_for_this_account_403(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(denied=True), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "self_join_denied")

    async def test_self_leave_works_without_account_links(self) -> None:
        """Unlinking Battle.net must not trap somebody in tonight's lineup."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.side_effect = [[row], []]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.load_missing_links.return_value = frozenset({"discord", "battlenet"})

        state = await self.service.self_leave(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.roster.delete.assert_awaited_once_with(self.session, row)
        self.assertIsNone(state["seat"])
        self.assertEqual(self.emit.await_args.kwargs["change"], "roster")

    async def test_self_leave_when_not_on_the_roster_404(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_leave(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "not_on_roster")

    async def test_self_update_reorders_the_players_own_roles(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        await self.service.self_update(
            self.session,
            custom_game_id=11,
            auth_user=_auth(),
            patch={
                "roles": [{"dimension": "player_role", "role": role} for role in ("support", "tank")],
                "is_flex": True,
            },
            workspace_id=1,
        )

        self.player_roles.replace_for_player.assert_awaited_once_with(
            self.session, 1, ["support", "tank"], discipline="overwatch"
        )
        self.assertEqual(row.role_selection_mode, MixRoleSelectionMode.EXPLICIT)
        self.assertTrue(row.is_flex)

    async def test_self_update_rejects_participation_422(self) -> None:
        """Bench and must-play are the host's call, whatever the switch says."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_update(
                self.session,
                custom_game_id=11,
                auth_user=_auth(),
                patch={"participation": MixParticipation.MUST_PLAY},
                workspace_id=1,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(row.participation, MixParticipation.POOL)

    async def test_self_update_needs_the_hosts_switch_409(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=False)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_update(
                self.session, custom_game_id=11, auth_user=_auth(), patch={"is_flex": True}, workspace_id=1
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "role_edit_off")
        self.assertFalse(row.is_flex)

    async def test_self_update_refuses_full_flex_in_a_game_without_it_422(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(discipline="deadlock", self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_update(
                self.session, custom_game_id=11, auth_user=_auth(), patch={"is_flex": True}, workspace_id=1
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "full_flex_unsupported")
        self.assertFalse(row.is_flex)
        self.emit.assert_not_awaited()

    async def test_self_state_reports_every_role_rank_and_the_unranked_ones(self) -> None:
        """The bot labels all 16 select options, so all three roles carry a
        number or an explicit null; `unranked_roles` narrows that to what the
        player actually plays."""
        row = _roster_row(1, 7, 0, roles=["tank", "support"])
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.ranks.resolve.return_value = {(7, "tank"): ResolvedRank(3100, "author")}

        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(state["seat"]["ranks"], {"tank": 3100, "damage": None, "support": None})
        self.assertEqual(
            state["seat"]["roles"],
            [RoleRef(dimension="player_role", role=role).model_dump() for role in ("tank", "support")],
        )
        self.assertEqual(state["unranked_roles"], ["support"])
        self.assertEqual(state["self_signup"], "pool")
        self.assertIs(state["self_role_edit"], True)

    async def test_self_state_badges_each_ranked_role_with_its_overwatch_rank(self) -> None:
        """The badge is the Overwatch rank the value lands in, not the platform
        grid's numbered tier: "Diamond 4" means something in Discord, "Division 1" does not."""
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.ranks.resolve.return_value = {(7, "tank"): ResolvedRank(3100, "author")}

        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(
            state["seat"]["divisions"],
            {"tank": {"name": "Diamond 4", "slug": "diamond-4"}, "damage": None, "support": None},
        )

    async def test_lol_self_state_badges_resolve_on_its_ladder_not_the_organisers_grid(self) -> None:
        from shared.division_grid import DivisionGrid, DivisionTier

        self.games.get.return_value = _game(self_signup="pool", discipline="lol")
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.ranks.resolve.return_value = {(7, "support"): ResolvedRank(3100, "author")}
        self.grid_lookup.return_value = DivisionGrid(
            version_id=77,
            tiers=(
                DivisionTier(
                    id=1, slug="veteran", number=9, name="Veteran", rank_min=3000, rank_max=None, icon_url="/v.png"
                ),
                DivisionTier(
                    id=2, slug="novice", number=10, name="Novice", rank_min=0, rank_max=2999, icon_url="/n.png"
                ),
            ),
        )
        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(state["seat"]["divisions"]["support"], {"name": "Grandmaster", "slug": "grandmaster"})

    async def test_self_state_names_the_games_roles_for_the_bot(self) -> None:
        """R3-1: the seat panel builds its role UI from these -- LoL's five positions with Full flex, Deadlock's one
        role without (a one-role game has no role form at all)."""
        self.games.get.return_value = _game(self_signup="pool", discipline="lol")
        lol = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.games.get.return_value = _game(self_signup="pool", discipline="deadlock")
        deadlock = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(("lol", True), (lol["discipline"], lol["discipline_flex"]))
        self.assertEqual(["top", "jungle", "mid", "bot", "support"], [role["code"] for role in lol["discipline_roles"]])
        self.assertEqual(
            ("deadlock", [{"code": "agent", "label": "Agent"}], False),
            (deadlock["discipline"], deadlock["discipline_roles"], deadlock["discipline_flex"]),
        )

    async def test_self_state_says_which_lobby_this_player_sits_in(self) -> None:
        """Where a player sits is the same derivation the board shows -- the
        seats of each lobby's selected option -- so the panel and the bot read
        it instead of parsing a solver document of their own."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", lobby_count=2)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.lobby_rows[1] = _lobby(
            1,
            balance_result_json=lobby_document(
                [
                    {
                        "teams": [
                            {"roster": {"tank": [{"uuid": "7", "name": "You"}]}},
                            {"roster": {"tank": [{"uuid": "8", "name": "Them"}]}},
                        ]
                    }
                ]
            ),
        )

        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(state["lobby_count"], 2)
        self.assertEqual(state["seat"]["current_lobby"], 1)

    async def test_self_state_of_a_player_nobody_balanced_in_waits_for_a_seat(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", lobby_count=2)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertIsNone(state["seat"]["current_lobby"])

    async def test_self_state_of_a_mix_in_another_workspace_404(self) -> None:
        self.games.get.return_value = _game(workspace_id=2)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_self_current_answers_for_the_newest_mix_still_running(self) -> None:
        """``/mix`` names no id: the newest mix that is not over is the one meant."""
        self.games.list_for_workspace = AsyncMock(
            return_value=[_game(id=13, status="cancelled"), _game(id=12), _game(id=11)]
        )
        self.games.get.return_value = _game(id=12)

        state = await self.service.self_current(self.session, workspace_id=1, auth_user=_auth())

        self.assertEqual(state["custom_game_id"], 12)
        self.games.get.assert_awaited_with(self.session, 12, options=())

    async def test_self_current_without_an_open_mix_404(self) -> None:
        self.games.list_for_workspace = AsyncMock(
            return_value=[_game(id=13, status="completed"), _game(id=12, status="cancelled")]
        )

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_current(self.session, workspace_id=1, auth_user=_auth())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_set_self_service_writes_both_switches(self) -> None:
        game = _game()
        self.games.get.return_value = game

        await self.service.set_self_service(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            patch={"self_signup": "benched", "self_role_edit": True},
            actor_user_id=9,
        )

        self.assertEqual(game.self_signup, "benched")
        self.assertTrue(game.self_role_edit)

    async def test_set_self_service_requires_the_host_403(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_self_service(
                self.session, workspace_id=1, custom_game_id=11, patch={"self_signup": "pool"}, actor_user_id=8
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_signup_post_opens_the_window_and_queues_a_cardless_send(self) -> None:
        """The bot renders the card from ``discord_view``: the row carries no
        card and no payload, the command only names it."""
        game = _game(name="Friday mix")
        self.games.get.return_value = game
        self._channel("555")

        channel_id, commands = await self.service.signup_post(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            self_signup="benched",
            actor_user_id=9,
        )

        self.assertEqual(channel_id, 555)
        self.assertEqual(game.self_signup, "benched")
        [post] = commands
        self.assertEqual((post.action, post.message_ref), ("send", self.messages.rows[-1].id))
        self.assertIsNone(self.messages.rows[-1].payload_json)

    async def test_signup_post_claims_the_row_the_command_names(self) -> None:
        """The message exists as a row before the bot hears about it: without
        one there is nothing for the outcome -- or a later delete -- to land on."""
        self.games.get.return_value = _game()
        self._channel("555")

        _channel_id, [post] = await self.service.signup_post(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            self_signup="pool",
            actor_user_id=9,
        )

        [row] = self.messages.rows
        self.assertEqual(post.message_ref, row.id)
        self.assertEqual((row.subject, row.slot, row.kind), ("mix:11", "signup", "mix.signup"))
        self.assertEqual((row.channel, row.target, row.status), ("discord_channel", "555", "pending"))
        self.assertEqual(row.workspace_id, 1)

    async def test_posting_again_deletes_the_previous_card_first(self) -> None:
        """Two live cards counting two rosters is the outcome to avoid, and the
        delete leads so the channel never shows both at once."""
        self.games.get.return_value = _game()
        self._channel("555")
        previous = self.messages.add(subject="mix:11", slot="signup", status="posted")
        refused = self.messages.add(subject="mix:11", slot="signup", status="failed")
        other_mix = self.messages.add(subject="mix:12", slot="signup", status="posted")

        _channel_id, commands = await self.service.signup_post(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            self_signup="pool",
            actor_user_id=9,
        )

        self.assertEqual(
            [("delete", previous.id), ("send", self.messages.rows[-1].id)],
            [(command.action, command.message_ref) for command in commands],
        )
        self.assertEqual(previous.status, "deleting")
        # A refusal is no message in the channel, so it is left alone: it stays
        # on the page as the receipt of what Discord said. Another mix's card is
        # not ours either.
        self.assertEqual(refused.status, "failed")
        self.assertEqual(other_mix.status, "posted")

    async def test_signup_post_without_a_workspace_channel_409(self) -> None:
        """Same refusal as posting a lineup: there is nowhere to post to."""
        game = _game()
        self.games.get.return_value = game

        with self.assertRaises(HTTPException) as ctx:
            await self.service.signup_post(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                self_signup="pool",
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Discord channel not configured")
        self.assertEqual(game.self_signup, "closed")
        self.assertEqual([], self.messages.rows)

    async def test_signup_post_requires_the_host_403(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.signup_post(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                self_signup="pool",
                actor_user_id=8,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_discord_view_lists_the_roster_at_the_ranks_the_balancer_uses(self) -> None:
        """Live, not a snapshot: the signup facts are read from the roster every
        time, under the names the balancer shows and at the numbers it balances
        with -- the first named role's, or the best one for "any role". Only Full
        Flex rows are flex; an "any role" row counts on its best role."""
        self.games.get.return_value = _game(
            name="Friday mix", self_signup="pool", updated_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        )
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, roles=["tank"]),
            _roster_row(
                2, 8, 1, roles=["damage", "support"], away=True, updated_at=datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
            ),
            _roster_row(3, 9, 2, participation=MixParticipation.BENCHED),
            _roster_row(4, 10, 3, roles=["support"], is_flex=True, participation=MixParticipation.BENCHED),
        ]
        self.load_hosts.return_value = {9: "Foxx"}
        self.ranks.resolve.return_value = {
            **_ranks(7, 10),
            (8, "damage"): ResolvedRank(2200, "author"),
            (9, "support"): ResolvedRank(2700, "author"),
        }

        view = await self.service.discord_view(self.session, 11, [], board_url_base="https://owt.example/")

        self.assertEqual(
            {key: view[key] for key in ("custom_game_id", "workspace_id", "status", "board_url", "lineups")},
            {
                "custom_game_id": 11,
                "workspace_id": 1,
                "status": "draft",
                "board_url": "https://owt.example/balancer/mix/11",
                "lineups": [],
            },
        )
        self.assertEqual(
            view["signup"],
            {
                "mix_name": "Friday mix",
                "host_name": "Foxx",
                "self_signup": "pool",
                "status": "draft",
                "lobby_count": 1,
                "players": [
                    {"name": "P7", "role": "tank", "benched": False, "rank": 2500, "away": False},
                    {"name": "P8", "role": "damage", "benched": False, "rank": 2200, "away": True},
                    {"name": "P9", "role": "support", "benched": True, "rank": 2700, "away": False},
                    {"name": "P10", "role": "flex", "benched": True, "rank": 2300, "away": False},
                ],
                # The one lobby a fresh mix has, with no lineup yet.
                "lobbies": [{"lobby_index": 0, "state": "idle", "live_started_at": None}],
                # The newest change of the mix or its roster: stable while nothing moves.
                "updated_at": "2026-10-02T09:30:00+00:00",
            },
        )
        kwargs = self.ranks.resolve.await_args.kwargs
        self.assertEqual((kwargs["order"], kwargs["author_user_id"]), (MIX_ORDER, 9))

    async def test_discord_view_of_an_unknown_mix_404(self) -> None:
        self.games.get.return_value = None

        with self.assertRaises(HTTPException) as ctx:
            await self.service.discord_view(self.session, 11, [], board_url_base="https://owt.example")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_discord_view_names_the_games_roles_and_each_lobbys_stage(self) -> None:
        """R3-1/R3-4: the bot builds its role UI from the game's own roles and prints every lobby's stage -- the
        detail read's derivation -- with the clock of a running match (pre-game too) or a live draft's first pick."""
        self.games.get.return_value = _game(discipline="lol", lobby_count=3)
        self.lobby_rows[0] = _lobby(0, live_encounter_id=900)
        self.lobby_rows[1] = _lobby(1)
        self.lobby_rows[2] = _lobby(2, live_encounter_id=901)
        started = datetime(2026, 10, 23, 18, 0, tzinfo=UTC)
        first_pick = datetime(2026, 10, 23, 18, 5, tzinfo=UTC)
        self.lobbies.live_started_at.return_value = {900: started, 901: started}
        self.lobbies.pregame_ids.return_value = frozenset({901})
        self.drafts.active_lobby_pools.return_value = {1: (31, "live", frozenset())}
        self.drafts.first_clock_starts.return_value = {31: first_pick}

        view = await self.service.discord_view(self.session, 11, [], board_url_base="https://owt.example")

        self.assertEqual(("lol", True), (view["discipline"], view["discipline_flex"]))
        self.assertEqual(
            [
                {"code": "top", "label": "Top"},
                {"code": "jungle", "label": "Jungle"},
                {"code": "mid", "label": "Mid"},
                {"code": "bot", "label": "Bot"},
                {"code": "support", "label": "Support"},
            ],
            view["discipline_roles"],
        )
        self.assertEqual(
            [
                {"lobby_index": 0, "state": "live", "live_started_at": started.isoformat()},
                {"lobby_index": 1, "state": "draft_live", "live_started_at": first_pick.isoformat()},
                {"lobby_index": 2, "state": "pregame", "live_started_at": started.isoformat()},
            ],
            view["signup"]["lobbies"],
        )

    async def test_deleting_one_post_marks_only_that_one(self) -> None:
        self.games.get.return_value = _game()
        signup = self.messages.add(subject="mix:11", slot="signup", status="posted")
        lineup = self.messages.add(subject="mix:11", slot="lineup:0:1", status="posted")

        _game_row, commands = await self.service.delete_discord_post(
            self.session, workspace_id=1, custom_game_id=11, post_id=lineup.id, actor_user_id=9
        )

        self.assertEqual([("delete", lineup.id)], [(command.action, command.message_ref) for command in commands])
        self.assertEqual(lineup.status, "deleting")
        self.assertEqual(signup.status, "posted")

    async def test_deleting_another_mixs_post_404(self) -> None:
        """One table for the whole platform: an id this mix does not own is not
        a message its host gets to delete."""
        self.games.get.return_value = _game()
        stranger = self.messages.add(subject="mix:12", slot="signup", status="posted")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.delete_discord_post(
                self.session, workspace_id=1, custom_game_id=11, post_id=stranger.id, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(stranger.status, "posted")

    async def test_deleting_a_post_requires_the_host_403(self) -> None:
        self.games.get.return_value = _game()
        row = self.messages.add(subject="mix:11", slot="signup", status="posted")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.delete_discord_post(
                self.session, workspace_id=1, custom_game_id=11, post_id=row.id, actor_user_id=8
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_hard_delete_takes_every_post_of_the_mix_down(self) -> None:
        """The messages do not cascade off the game row, and a card advertising
        a mix that no longer exists is worse than no card."""
        self.games.get.return_value = _game()
        self.games.delete = AsyncMock()
        signup = self.messages.add(subject="mix:11", slot="signup", status="posted")
        lineup = self.messages.add(subject="mix:11", slot="lineup:0:1", status="pending")
        refused = self.messages.add(subject="mix:11", slot="lineup:0:2", status="failed")
        other_mix = self.messages.add(subject="mix:12", slot="signup", status="posted")

        commands = await self.service.hard_delete(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(
            [("delete", signup.id), ("delete", lineup.id)],
            [(command.action, command.message_ref) for command in commands],
        )
        # Discord never saw the refused one, so it is closed without a command.
        self.assertEqual(refused.status, "deleted")
        self.assertEqual(other_mix.status, "posted")
        self.games.delete.assert_awaited_once()

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
            "players": {"7": {"name": "P7"}, "8": {"name": "P8"}, "9": {"name": "P9"}},
            "variants": [{"teams": [{"roster": {"tank": ["7", "8"]}}], "statistics": {}, "benched": ["9"]}],
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
            (7, "damage"): ResolvedRank(None, "none"),
            (7, "support"): ResolvedRank(None, "none"),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "missing_ranked_role")
        self.run_balance.assert_not_called()

    async def test_balance_uses_role_order_as_priority(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0, roles=["support", "damage"])]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        classes = self.run_balance.await_args.args[0]["players"]["7"]["stats"]["classes"]
        self.assertEqual(classes["support"]["priority"], 1)
        self.assertEqual(classes["damage"]["priority"], 2)
        self.assertNotIn("tank", classes)

    async def test_balance_of_one_lobby_leaves_out_the_other_lobbys_players(self) -> None:
        """Лобби A играет: его места и закреплённые за ним не попадают в баланс B."""
        game = _game(status="balanced", lobby_count=2)
        roster = [
            _roster_row(1, 7, 0),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2, lobby_pin=0),
            _roster_row(4, 10, 3),
        ]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8, 9, 10)
        self.lobby_rows[1] = _lobby(1)
        self.lobby_rows[0] = _lobby(
            0,
            balanced_at=datetime(2026, 3, 1, 21, 0),
            balance_result_json=lobby_document(
                [
                    {
                        "teams": [
                            {"id": 1, "roster": {"tank": [self._seat("8", "P8", 2500, "tank")]}},
                            {"id": 2, "roster": {"tank": [self._seat("10", "P10", 2400, "tank")]}},
                        ],
                        "statistics": {},
                        "benched_players": [],
                    }
                ]
            ),
        )

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, lobby_index=1, actor_user_id=9)

        # 8 и 10 сидят в выбранном варианте лобби A, 9 закреплён за A -- остаётся 7.
        self.assertEqual(list(self.run_balance.await_args.args[0]["players"]), ["7"])
        self.assertIsNotNone(self.lobby_rows[1].balance_result_json)
        self.assertIsNotNone(self.lobby_rows[1].balanced_at)
        # Документ соседнего лобби не переписан.
        self.assertEqual(self.lobby_rows[0].balanced_at, datetime(2026, 3, 1, 21, 0))

    async def test_balance_of_a_one_lobby_mix_keeps_the_whole_pool(self) -> None:
        """У микса одно лобби: ни чужой документ, ни залежавшийся пин не сужают пул."""
        self.games.get.return_value = _game(lobby_count=1)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 8, 1, lobby_pin=1)]
        self.ranks.resolve.return_value = _ranks(7, 8)
        self.lobby_rows[1] = _lobby(
            1,
            balance_result_json=lobby_document(
                [
                    {
                        "teams": [
                            {"id": 1, "roster": {"tank": [self._seat("7", "P7", 2500, "tank")]}},
                            {"id": 2, "roster": {"tank": [self._seat("8", "P8", 2400, "tank")]}},
                        ],
                        "statistics": {},
                        "benched_players": [],
                    }
                ]
            ),
        )

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual(sorted(self.run_balance.await_args.args[0]["players"]), ["7", "8"])
        self.assertIsNotNone(self.lobby_rows[0].balance_result_json)

    async def test_balance_of_a_two_lobby_mix_leaves_the_unseated_waiting(self) -> None:
        """Невлезший в лобби игрок ждёт соседнее, а не уходит в бенч: бенч выкинул
        бы его и из кандидатов второго лобби."""
        game = _game(lobby_count=2)
        roster = [_roster_row(1, 7, 0), _roster_row(2, 8, 1), _roster_row(3, 9, 2)]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8, 9)
        self.lobby_rows[1] = _lobby(1)
        self.run_balance.return_value = {
            "players": {"7": {"name": "P7"}, "8": {"name": "P8"}, "9": {"name": "P9"}},
            "variants": [{"teams": [{"roster": {"tank": ["7", "8"]}}], "statistics": {}, "benched": ["9"]}],
        }

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9)

        self.assertEqual([row.participation for row in roster], [MixParticipation.POOL] * 3)

    async def test_balance_of_both_lobbies_fills_each_with_its_own_half(self) -> None:
        """«Перемешать оба»: один прогон движка на лобби, ровно на своих игроках."""
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1),))
        game = _game(lobby_count=2)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2),
            _roster_row(4, 10, 3),
        ]
        self.ranks.resolve.return_value = _ranks(7, 8, 9, 10)
        self.lobby_rows[1] = _lobby(1)

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9)

        self.assertEqual(self.run_balance.await_count, 2)
        first, second = (call.args[0]["players"] for call in self.run_balance.await_args_list)
        # Силы равны, поэтому деление идёт по входному порядку -- и ни один игрок
        # не попадает в оба лобби.
        self.assertEqual(set(first), {"7", "9"})
        self.assertEqual(set(second), {"8", "10"})
        for lobby in self.lobby_rows.values():
            self.assertIsNotNone(lobby.balance_result_json)
            self.assertIsNotNone(lobby.balanced_at)
            self.assertEqual(lobby.selected_variant_index, 0)
        self.assertEqual(game.status, "balanced")

    async def test_balance_of_both_lobbies_needs_two_lobbies(self) -> None:
        self.games.get.return_value = _game(lobby_count=1)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "single_lobby")
        self.run_balance.assert_not_called()

    async def test_balance_of_both_lobbies_refuses_a_pool_that_fills_only_one(self) -> None:
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1),))
        self.games.get.return_value = _game(lobby_count=2)
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2),
        ]
        self.ranks.resolve.return_value = _ranks(7, 8, 9)
        self.lobby_rows[1] = _lobby(1)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "not_enough_players")
        self.run_balance.assert_not_called()

    async def test_update_roster_keeps_surviving_row_state(self) -> None:
        game = _game()
        keep = _roster_row(1, 7, 0, participation=MixParticipation.BENCHED, roles=["damage"])
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
        self.assertEqual(keep.roles, ["damage"])
        self.assertEqual(keep.sort_order, 1)

    async def test_update_roster_keeps_stored_balance(self) -> None:
        """Adding or dropping a player must not blow away the last balance --
        only pressing Balance teams again should replace it."""
        game = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": []})
        keep = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [keep]

        await self.service.update_roster(
            self.session, workspace_id=1, custom_game_id=11, member_ids=[7, 9], actor_user_id=9
        )

        self.assertEqual(game.status, "balanced")
        self.assertEqual(self.lobby_rows[0].balance_result_json, {"variants": []})
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
            discipline="overwatch",
            host_user_id=9,
            name="Scrim",
            actor_user_id=9,
            member_ids=[7, 8],
        )

        seeded = {call.kwargs["workspace_member_id"]: call.kwargs for call in self.ranks.set_ranks.await_args_list}
        self.assertEqual(sorted(seeded), [7, 8])
        self.assertEqual(seeded[7]["author_user_id"], 9)
        self.assertEqual(seeded[7]["workspace_id"], 1)
        self.assertEqual(seeded[7]["ranks"], {"tank": 2500, "damage": 2400, "support": 2300})
        kwargs = self.ranks.resolve.await_args.kwargs
        self.assertEqual(kwargs["order"], MIX_ORDER)
        self.assertEqual(kwargs["author_user_id"], 9)
        # The game's own ladder, never the workspace grid: the 1-20 system default read every OW rank >= 2000 as its
        # top tier and seeded 2000 into the host's book.
        self.assertIs(kwargs["grid"], ladder_grid("overwatch"))
        self.grid_lookup.assert_not_awaited()

    async def test_seeding_leaves_a_rank_the_host_already_owns_alone(self) -> None:
        """Re-adding somebody must not undo a correction the host already made."""
        self.ranks.resolve.return_value = {
            (7, "tank"): ResolvedRank(3000, "author"),
            (7, "damage"): ResolvedRank(2400, "workspace"),
            (7, "support"): ResolvedRank(None, "none"),
        }

        await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Scrim",
            actor_user_id=9,
            member_ids=[7],
        )

        # Only the inherited role is copied; an unranked one stays unranked
        # rather than being invented from nothing.
        self.assertEqual(self.ranks.set_ranks.await_args.kwargs["ranks"], {"damage": 2400})

    async def test_seeding_skips_a_player_with_no_rank_anywhere(self) -> None:
        self.ranks.resolve.return_value = {}

        await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Scrim",
            actor_user_id=9,
            member_ids=[7],
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
                        actor_user_id=9,
                    )
                self.assertEqual(ctx.exception.status_code, 409)
                self.session.flush.assert_not_called()
                self.session.flush.reset_mock()

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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)
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
            actor_user_id=9,
        )

        # Redeemed: the pin guaranteed one seat, and it just got it.
        self.assertEqual(pinned_played.participation, MixParticipation.POOL)
        # Untouched: never seated, never redeemed, keeps its guarantee.
        self.assertEqual(pinned_absent.participation, MixParticipation.MUST_PLAY)
        # Was never pinned in the first place.
        self.assertEqual(unpinned_played.participation, MixParticipation.POOL)

    async def test_record_outcome_draw_has_no_winner(self) -> None:
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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=None,
            actor_user_id=9,
        )

        self.assertIsNone(self._draft().winner)

    async def test_record_outcome_without_a_host_points_knob_never_adjusts_ranks(self) -> None:
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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            actor_user_id=9,
        )

        self.ranks.set_ranks.assert_not_awaited()

    async def test_record_outcome_applies_the_hosts_points_with_fallback_to_balance_rating(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {
                            "roster": {
                                "tank": [self._seat("7", "Alpha", 3200, "tank")],
                                "damage": [self._seat("8", "Bravo", 2900, "damage")],
                            }
                        },
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)
        # The HOST's knob, off the host's own account row -- not the mix's and
        # not the recording co-host's.
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)
        # Member 9 has no author-layer entry yet -- the write must fall back to
        # their balance-time rating (2600) instead of dropping the adjustment.
        self.ranks.list_layer = AsyncMock(return_value={(7, "tank"): 2500, (8, "damage"): 2800})

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
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
                (8, 9, (("damage", 2825),)),
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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=None,
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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)
        self.ranks.list_layer = AsyncMock(return_value={})

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=1,
            actor_user_id=9,
        )

        self.host_prefs.get_by_user.assert_awaited_with(self.session, 9)
        self.assertEqual(self._draft().points_per_win_applied, 25)

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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            winner=None,
            actor_user_id=9,
        )

        self.assertIsNone(self._draft().points_per_win_applied)

    def _one_v_one(self) -> dict[str, object]:
        return {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 2400, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2400, "tank")]}},
                    ]
                }
            ]
        }

    async def test_record_outcome_by_ranker_moves_each_seat_and_freezes_its_delta(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=lobby_document(self._one_v_one()["variants"]), live_encounter_id=900
        )
        # The points knob is still stored; the ranker ignores it.
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25, rating_mode="ranker")
        self.ranks.list_layer = AsyncMock(return_value={(7, "tank"): 2400, (9, "tank"): 2400})

        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9)

        moved = {
            call.kwargs["workspace_member_id"]: call.kwargs["ranks"]["tank"]
            for call in self.ranks.set_ranks.await_args_list
        }
        self.assertGreater(moved[7], 2400)
        self.assertLess(moved[9], 2400)
        self.assertEqual({7: moved[7] - 2400, 9: moved[9] - 2400}, self._draft().rank_deltas)
        self.assertIsNone(self._draft().points_per_win_applied)

    async def test_record_outcome_in_points_mode_still_advances_the_hidden_ratings(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=lobby_document(self._one_v_one()["variants"]), live_encounter_id=900
        )
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)
        self.ranks.list_layer = AsyncMock(return_value={})

        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9)

        book = self.ranker.hidden.book
        self.assertGreater(book[(7, 1)][0], book[(9, 1)][0])
        self.assertEqual({}, self._draft().rank_deltas)

    async def test_undo_gives_back_each_ranker_delta_and_rebuilds_the_hidden_book(self) -> None:
        match = _round(501, created_at=1, first=[7], second=[9])
        self.mix_rounds.seats.return_value = _seats([(7, "tank", 2400, 31)], [(9, "tank", 2400, -28)])
        self.games.get.return_value = _game()
        # Switched back to points since: undo still gives back what was frozen.
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)
        self.mix_rounds.get_for_game.return_value = match
        self.mix_rounds.newest_id_for_lobby.return_value = 501
        self.ranks.list_layer = AsyncMock(return_value={(7, "tank"): 2431, (9, "tank"): 2372})
        self.ranker.hidden.book = {(7, 1): (5.0, 24.0), (9, 1): (-5.0, 24.0)}

        await self.service.undo_last_match(
            self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
        )

        calls = {
            (call.kwargs["workspace_member_id"], tuple(call.kwargs["ranks"].items()))
            for call in self.ranks.set_ranks.await_args_list
        }
        self.assertEqual(calls, {(7, (("tank", 2400),)), (9, (("tank", 2400),))})
        # The undone match was the whole history, so the rebuilt book is empty.
        self.assertEqual(self.ranker.hidden.book, {})

    async def _record_a_balanced_deadlock_round(self, prefs: SimpleNamespace) -> dict[int, int]:
        """Balance a two-player Deadlock mix, record a team-1 win; ``member -> agent rank written to the host's book``.

        ``slot_shape`` runs for real on the Deadlock module's 6v6 preset (only its database load is stubbed), and the
        solver stand-in seats one player per team in the bucket the mask names, the way the engine keys a roster by
        the mask's codes. The bucket is the whole point: a seat in an open slot moves no rank book.
        """
        self.games.get.return_value = _game(discipline="deadlock")
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 9, 1)]
        self.ranks.resolve.return_value = {
            (7, "agent"): ResolvedRank(2400, "workspace"),
            (9, "agent"): ResolvedRank(2400, "workspace"),
        }
        self.ranks.list_layer = AsyncMock(return_value={(7, "agent"): 2400, (9, "agent"): 2400})
        self.host_prefs.get_by_user.return_value = prefs
        six = TeamFormat.from_preset("deadlock", DISCIPLINES["deadlock"].preset())
        self.slot_shape.return_value = slot_shape(six, _module_ontology("deadlock"))

        async def solve(payload, _config, _progress, role_mask):
            (bucket,) = role_mask
            teams = [
                {"roster": {bucket: [self._seat(uuid, f"P{uuid}", 2400, bucket, all_ratings={bucket: 2400})]}}
                for uuid in sorted(payload["players"])
            ]
            return lobby_document([{"teams": teams}])

        self.run_balance.side_effect = solve
        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        await self.service.start_match(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9)
        return {
            call.kwargs["workspace_member_id"]: call.kwargs["ranks"]["agent"]
            for call in self.ranks.set_ranks.await_args_list
        }

    async def test_a_deadlock_round_moves_the_hosts_agent_rank_by_points(self) -> None:
        moved = await self._record_a_balanced_deadlock_round(_prefs(points_per_win=25))

        self.assertEqual(moved, {7: 2425, 9: 2375})

    async def test_a_deadlock_round_moves_the_hosts_agent_rank_by_the_ranker(self) -> None:
        moved = await self._record_a_balanced_deadlock_round(_prefs(rating_mode="ranker"))

        self.assertEqual(set(moved), {7, 9})
        self.assertGreater(moved[7], 2400)
        self.assertLess(moved[9], 2400)

    async def test_a_deadlock_lineup_stored_before_the_fix_records_without_moving_a_rank(self) -> None:
        # Not retroactive: a stored lineup still keyed by the open slot records as it did, moving nothing.
        stored = [
            {
                "teams": [
                    {"roster": {"flex": [self._seat("7", "P7", 2400, "flex")]}},
                    {"roster": {"flex": [self._seat("9", "P9", 2400, "flex")]}},
                ]
            }
        ]
        self.games.get.return_value = _game(discipline="deadlock", status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(stored))
        self.host_prefs.get_by_user.return_value = _prefs(rating_mode="ranker")
        self.ranks.list_layer = AsyncMock(return_value={(7, "agent"): 2400, (9, "agent"): 2400})

        await self.service.start_match(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)
        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9)

        self.write_result.assert_awaited_once()
        self.ranks.set_ranks.assert_not_awaited()

    async def test_balance_by_ranker_feeds_effective_ratings_and_keeps_the_open_ones(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.host_prefs.get_by_user.return_value = _prefs(rating_mode="ranker")
        # A confident hidden tank rating far above the open 2500; nothing hidden for damage.
        self.ranker.hidden.book = {(7, 1): (Ranker().initial(3500).mu, 3.0)}
        self.run_balance.return_value = lobby_document(
            [
                {
                    "teams": [
                        {
                            "roster": {
                                "tank": [
                                    self._seat("7", "P7", 3400, "tank", all_ratings={"tank": 3400, "damage": 2400})
                                ]
                            }
                        }
                    ]
                }
            ]
        )

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        classes = self.run_balance.await_args.args[0]["players"]["7"]["stats"]["classes"]
        self.assertGreater(classes["tank"]["rank"], 3000)
        self.assertEqual(classes["damage"]["rank"], 2400)
        stored = self.lobby_rows[0].balance_result_json["players"]["7"]
        self.assertEqual(stored["open_ratings"], {"tank": 2500, "damage": 2400})

    async def test_undo_a_match_of_another_mix_404(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.undo_last_match(
                self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.mix_rounds.delete_round.assert_not_awaited()

    async def test_undo_only_applies_to_the_newest_match(self) -> None:
        self.games.get.return_value = _game()
        self.mix_rounds.get_for_game.return_value = _round(501, created_at=1, first=[7], second=[9])
        self.mix_rounds.newest_id_for_lobby.return_value = 502

        with self.assertRaises(HTTPException) as ctx:
            await self.service.undo_last_match(
                self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Only the most recent match of this lobby can be undone")
        self.mix_rounds.delete_round.assert_not_awaited()

    async def test_undo_reverses_the_points_the_match_stored(self) -> None:
        match = _round(501, created_at=1, first=[7, 8], second=[9], points_per_win_applied=25)
        self.mix_rounds.seats.return_value = _seats([(7, "tank", 3200), (8, "damage", 2900)], [(9, "tank", 2600)])
        # The host's knob has since been turned up; the rollback must ignore it
        # and give back the 25 that was actually applied.
        self.games.get.return_value = _game()
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=999)
        self.mix_rounds.get_for_game.return_value = match
        self.mix_rounds.newest_id_for_lobby.return_value = 501
        self.ranks.list_layer = AsyncMock(return_value={(7, "tank"): 2525, (8, "damage"): 2825, (9, "tank"): 2575})

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
                (8, 9, (("damage", 2800),)),
                (9, 9, (("tank", 2600),)),
            },
        )
        self.mix_rounds.delete_round.assert_awaited_once_with(self.session, 501)
        self.mix_rounds.seats.assert_awaited_once_with(self.session, workspace_id=1, encounter_id=501)

    async def test_undo_a_draw_deletes_without_touching_ranks(self) -> None:
        round_ = _round(501, created_at=1, first=[7], second=[9], scores=(0.0, 0.0))
        self.games.get.return_value = _game()
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)
        self.mix_rounds.get_for_game.return_value = round_
        self.mix_rounds.newest_id_for_lobby.return_value = 501
        self.mix_rounds.seats.return_value = _seats([(7, "tank", 3200)], [(9, "tank", 2600)], scores=(0.0, 0.0))

        await self.service.undo_last_match(
            self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
        )

        self.ranks.set_ranks.assert_not_awaited()
        self.mix_rounds.delete_round.assert_awaited_once_with(self.session, 501)

    async def test_list_matches_returns_the_recorded_history(self) -> None:
        self.games.get.return_value = _game()
        matches = [object(), object()]
        self.mix_rounds.list_for_custom_game = AsyncMock(return_value=matches)

        result = await self.service.list_matches(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(result, matches)
        self.mix_rounds.list_for_custom_game.assert_awaited_once_with(self.session, 11)

    async def test_mix_stats_merges_the_current_roster_into_the_scoreboard(self) -> None:
        played_at = datetime(2026, 3, 1, 21, 30)
        recorded_at = datetime(2026, 3, 1, 21, 45)
        self.mix_rounds.seats = AsyncMock(
            return_value=[
                _row(
                    workspace_member_id=7,
                    role="damage",
                    encounter_id=1,
                    custom_game_id=11,
                    created_at=played_at,
                    recorded_at=recorded_at,
                    own_score=2.0,
                    other_score=1.0,
                ),
                _row(
                    workspace_member_id=8,
                    role=None,
                    encounter_id=1,
                    custom_game_id=11,
                    created_at=played_at,
                    recorded_at=recorded_at,
                    own_score=1.0,
                    other_score=2.0,
                ),
            ]
        )
        # Member 8 has left the workspace since that match: the roster read no
        # longer answers for them, but their seat still counted.
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)

        scoreboard = await self.service.mix_stats(self.session, workspace_id=1, discipline="overwatch", since=None)

        self.mix_rounds.seats.assert_awaited_once_with(self.session, workspace_id=1, discipline="overwatch", since=None)
        # The roster is read under the discipline's own identity provider.
        self.assertEqual(self.load_roster.await_args.kwargs["provider"], SocialProvider.BATTLENET)
        self.assertEqual(
            scoreboard,
            {
                "members": [
                    {
                        "workspace_member_id": 7,
                        # The global player: what the client merges one person's rows across communities by.
                        "player_id": 70,
                        "display_name": "P7",
                        "identity": {"provider": "battlenet", "handle": "P7#1"},
                        "games": 1,
                        "wins": 1,
                        "losses": 0,
                        "draws": 0,
                        "win_rate": 1.0,
                        "streak": 1,
                        "last_played_at": played_at.isoformat(),
                        # ``by_role`` is keyed by the canonical role code.
                        "by_role": {"damage": {"games": 1, "wins": 1, "losses": 0, "draws": 0}},
                        "form": [
                            {
                                "outcome": "win",
                                "match_id": 1,
                                "played_at": played_at.isoformat(),
                                "recorded_at": recorded_at.isoformat(),
                            }
                        ],
                    },
                    {
                        "workspace_member_id": 8,
                        "player_id": None,
                        "display_name": None,
                        "identity": None,
                        "games": 1,
                        "wins": 0,
                        "losses": 1,
                        "draws": 0,
                        "win_rate": 0.0,
                        "streak": -1,
                        "last_played_at": played_at.isoformat(),
                        # A seat recorded without a role lands in no bucket.
                        "by_role": {},
                        "form": [
                            {
                                "outcome": "loss",
                                "match_id": 1,
                                "played_at": played_at.isoformat(),
                                "recorded_at": recorded_at.isoformat(),
                            }
                        ],
                    },
                ],
                # Two seats, one round of one mix.
                "mixes": 1,
                "matches": 1,
            },
        )

    async def test_mix_stats_counts_the_mixes_and_matches_behind_the_seats(self) -> None:
        played_at = datetime(2026, 3, 1, 21, 30)
        self.mix_rounds.seats = AsyncMock(
            return_value=[
                _row(
                    workspace_member_id=member,
                    role=None,
                    encounter_id=encounter,
                    custom_game_id=mix,
                    created_at=played_at,
                    recorded_at=played_at,
                    own_score=1.0,
                    other_score=0.0,
                )
                for member, encounter, mix in ((7, 1, 11), (8, 1, 11), (7, 2, 11), (7, 3, 12), (9, 3, 12))
            ]
        )
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7, 8, 9)

        scoreboard = await self.service.mix_stats(self.session, workspace_id=1, discipline=None, since=None)

        # Five seats over three rounds of two mixes.
        self.assertEqual((scoreboard["mixes"], scoreboard["matches"]), (2, 3))
        # Member 7's three wins lead; every row names its global player.
        self.assertEqual([70, 80, 90], [row["player_id"] for row in scoreboard["members"]])

    async def test_mix_stats_of_an_empty_window_is_zero_everywhere(self) -> None:
        self.mix_rounds.seats = AsyncMock(return_value=[])

        scoreboard = await self.service.mix_stats(self.session, workspace_id=1, discipline=None, since=None)

        self.assertEqual(scoreboard, {"members": [], "mixes": 0, "matches": 0})

    async def test_mix_stats_without_a_game_has_no_role_split(self) -> None:
        played_at = datetime(2026, 3, 1, 21, 30)
        self.mix_rounds.seats = AsyncMock(
            return_value=[
                _row(
                    workspace_member_id=7,
                    role="damage",
                    encounter_id=1,
                    custom_game_id=11,
                    created_at=played_at,
                    recorded_at=played_at,
                    own_score=2.0,
                    other_score=1.0,
                ),
            ]
        )
        self.load_roster.side_effect = None
        self.load_roster.return_value = _members(7)

        scoreboard = await self.service.mix_stats(self.session, workspace_id=1, discipline=None, since=None)

        self.mix_rounds.seats.assert_awaited_once_with(self.session, workspace_id=1, discipline=None, since=None)
        # Role codes of different games are different roles: across games there is no per-role split.
        [member] = scoreboard["members"]
        self.assertIsNone(member["by_role"])
        self.assertEqual((member["games"], member["wins"]), (1, 1))

    async def test_set_next_map_stores_a_catalogue_map(self) -> None:
        self.games.get.return_value = _game()

        await self.service.set_next_map(self.session, workspace_id=1, custom_game_id=11, map_id=42, actor_user_id=9)

        self.assertEqual(self.lobby_rows[0].next_map_id, 42)

    async def test_set_next_map_unknown_map_404(self) -> None:
        self.games.get.return_value = _game()
        self.maps.exists.return_value = False

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_next_map(
                self.session, workspace_id=1, custom_game_id=11, map_id=999, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_set_lobby_code_is_writable_while_the_match_is_live_and_blank_clears_it(self) -> None:
        """A lobby re-created mid-match needs its new code out at once; a cleared field stores no code."""
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, live_encounter_id=900)

        await self.service.set_lobby_code(
            self.session, workspace_id=1, custom_game_id=11, lobby_code="ABC123", actor_user_id=9
        )
        self.assertEqual("ABC123", self.lobby_rows[0].lobby_code)

        await self.service.set_lobby_code(
            self.session, workspace_id=1, custom_game_id=11, lobby_code="", actor_user_id=9
        )
        self.assertIsNone(self.lobby_rows[0].lobby_code)

    async def test_set_variant_index_pages_the_mix_for_every_viewer(self) -> None:
        result = {"variants": [{"teams": []}, {"teams": []}, {"teams": []}]}
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]))

        await self.service.set_variant_index(
            self.session, workspace_id=1, custom_game_id=11, variant_index=2, actor_user_id=9
        )

        self.assertEqual(self.lobby_rows[0].selected_variant_index, 2)

    async def test_set_variant_index_past_the_stored_options_404(self) -> None:
        result = {"variants": [{"teams": []}]}
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]))

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_variant_index(
                self.session, workspace_id=1, custom_game_id=11, variant_index=1, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_discord_lineup_without_a_workspace_channel_409(self) -> None:
        """The workspace names no channel: nothing to post to."""
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [{"teams": []}]})

        with self.assertRaises(HTTPException) as ctx:
            await self.service.discord_lineup(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=0,
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Discord channel not configured")

    async def test_discord_lineup_posts_to_the_workspace_channel(self) -> None:
        """The only channel there is: a mix cannot redirect the workspace's
        Discord, so the workspace-wide setting is both where it is configured
        and where it is read."""
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [{"teams": []}]})
        self.team_names.mapping_for_game.return_value = {}
        self.mix_rounds.activity_for_lobbies = AsyncMock(return_value={})
        self._channel("555")

        channel_id, _commands = await self.service.discord_lineup(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            actor_user_id=9,
        )

        self.assertEqual(channel_id, 555)

    async def test_discord_lineup_unknown_variant_404(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [{"teams": []}]})
        self._channel("555")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.discord_lineup(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=1,
                actor_user_id=9,
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Balance option not found")

    async def test_discord_lineup_claims_the_lobbys_next_match_without_a_card(self) -> None:
        """The match number continues the lobby's history. The row carries no
        card -- the bot renders it from ``discord_view`` -- and the lobby's older
        cards are not touched here: the bot takes their voice buttons off."""
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document([{"teams": []}]))
        self.mix_rounds.activity_for_lobbies = AsyncMock(return_value={0: (3, datetime(2026, 1, 1, 20, 0))})
        self._channel("777")
        older = self.messages.add(subject="mix:11", slot="lineup:0:3", kind="mix.lineup", status="posted")

        channel_id, [command] = await self.service.discord_lineup(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            actor_user_id=9,
        )

        self.assertEqual(channel_id, 777)
        row = self.messages.rows[-1]
        self.assertEqual((command.action, command.message_ref), ("send", row.id))
        self.assertEqual((row.subject, row.slot, row.kind), ("mix:11", "lineup:0:4", "mix.lineup"))
        self.assertEqual((row.channel, row.target, row.payload_json), ("discord_channel", "777", None))
        self.assertEqual(older.status, "posted")

    async def test_discord_view_describes_a_current_lineup(self) -> None:
        """Exactly what the bot's lineup builder takes: the lobby's shown option
        and its players, the lobby's own team names, the map read with its
        gamemode eagerly -- an async session cannot walk that lazily -- the
        HOST's points (the ones recording will move) and the Discord ids of
        whoever that option seats and linked an account."""
        document = lobby_document(
            [
                {"teams": []},
                {
                    "teams": [
                        {"roster": {"Tank": [{"uuid": "1", "name": "Ana", "assigned_rating": 3000}]}},
                        {"roster": {"Tank": [{"uuid": "2", "name": "Bob", "assigned_rating": 2900}]}},
                    ]
                },
            ]
        )
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(
            0, next_map_id=42, lobby_code="ABC123", selected_variant_index=1, balance_result_json=document
        )
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)
        self.team_names.mapping_for_game.return_value = {0: "Blue"}
        self.mix_rounds.activity_for_lobbies = AsyncMock(return_value={0: (3, datetime(2026, 1, 1, 20, 0))})
        self.maps.get_map_with_mode.return_value = _row(
            id=42, name="Busan", parent=_row(name="Control"), image_path="https://s3.example/busan.jpg"
        )
        # Only the first seat's account linked a Discord.
        self._discord_links({1: "111"})

        view = await self.service.discord_view(self.session, 11, [(0, 4)], board_url_base="https://owt.example")

        self.assertEqual(
            view["lineups"],
            [
                {
                    "lobby_index": 0,
                    "match_number": 4,
                    "current": True,
                    "variant": document["variants"][1],
                    "players": document["players"],
                    "team_names": {"0": "Blue"},
                    "next_map": ["Busan", "Control"],
                    "map_image": "https://s3.example/busan.jpg",
                    "map_choice": True,
                    "lobby_code": "ABC123",
                    "points_per_win": 25,
                    "lobby_label": None,
                    "mention_user_ids": ["111"],
                    "voice_target": "11-0",
                }
            ],
        )

    async def test_discord_view_names_no_map_for_a_single_map_game(self) -> None:
        """One competitive map leaves nothing to choose: the card carries no map, even one set before."""
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, next_map_id=42, balance_result_json=lobby_document([{"teams": []}]))
        self.mix_rounds.activity_for_lobbies = AsyncMock(return_value={0: (0, datetime(2026, 1, 1, 20, 0))})
        self.maps.count.return_value = 1
        self.maps.get_map_with_mode.return_value = _row(id=42, name="Busan", parent=None, image_path="x")

        view = await self.service.discord_view(self.session, 11, [(0, 1)], board_url_base="https://owt.example")

        [lineup] = view["lineups"]
        self.assertEqual(
            (True, False, None, None),
            (lineup["current"], lineup["map_choice"], lineup["next_map"], lineup["map_image"]),
        )

    async def test_discord_view_leaves_a_recorded_match_a_gone_option_and_a_finished_mix_alone(self) -> None:
        """The match on a card was recorded: the next shuffle belongs to the next
        post, so the played card is not rewritten under its result. A lobby or a
        shown option that is gone has nothing to show, and a finished mix keeps
        its cards as they ended -- the bot leaves every such card alone."""
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document([{"teams": []}]))
        self.mix_rounds.activity_for_lobbies = AsyncMock(return_value={0: (1, datetime(2026, 1, 1, 20, 0))})

        async def current(*lineups: tuple[int, int]) -> list[bool]:
            view = await self.service.discord_view(self.session, 11, lineups, board_url_base="https://owt.example")
            return [entry["current"] for entry in view["lineups"]]

        # Match 1 of lobby A is recorded, match 2 is next; lobby B does not exist.
        self.assertEqual([False, True, False], await current((0, 1), (0, 2), (1, 1)))
        view = await self.service.discord_view(self.session, 11, [(0, 1)], board_url_base="https://owt.example")
        self.assertEqual(
            view["lineups"],
            [
                {
                    "lobby_index": 0,
                    "match_number": 1,
                    "current": False,
                    "variant": None,
                    "players": None,
                    "team_names": None,
                    "next_map": None,
                    "map_image": None,
                    "map_choice": True,
                    "lobby_code": None,
                    "points_per_win": None,
                    "lobby_label": None,
                    "mention_user_ids": [],
                    "voice_target": "11-0",
                }
            ],
        )

        self.lobby_rows[0] = _lobby(0, selected_variant_index=4, balance_result_json=lobby_document([{"teams": []}]))
        self.assertEqual([False], await current((0, 2)))

        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document([{"teams": []}]))
        self.games.get.return_value = _game(status=MixStatus.COMPLETED)
        self.assertEqual([False], await current((0, 2)))

    async def test_set_voice_channels_writes_the_mixs_general_voice_and_both_team_voices(self) -> None:
        """One write for the whole mix: the general voice everyone returns to,
        and each listed lobby's two team voices."""
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[1] = _lobby(1)

        game = await self.service.set_voice_channels(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            general_voice_channel_id=555,
            lobbies=[(0, 1, 2), (1, 3, None)],
            actor_user_id=9,
        )

        self.assertEqual(game.general_voice_channel_id, 555)
        self.assertEqual(
            [(row.team1_voice_channel_id, row.team2_voice_channel_id) for row in self.lobby_rows.values()],
            [(1, 2), (3, None)],
        )

    async def test_set_voice_channels_requires_the_host_or_a_co_host_403(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_voice_channels(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                general_voice_channel_id=555,
                lobbies=[],
                actor_user_id=21,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_voice_options_splits_the_categorys_voices_into_general_and_team(self) -> None:
        """Only the configured category's voices are offered, and the
        workspace's general ones are the ones a mix returns people to."""
        self.games.get.return_value = _game()
        self._voice_config({"mix_voice_category_id": "10", "mix_general_voice_channel_ids": ["1"]}, "5")
        discord = _discord(
            _channel("10", "Mixes", "category"),
            _channel("1", "General", "voice", category_id="10"),
            _channel("2", "Team A1", "voice", category_id="10", missing_permissions=["move_members"]),
            _channel("3", "Elsewhere", "voice", category_id="20"),
        )

        options = await self.service.voice_options(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, actor_user_id=9
        )

        self.assertEqual(options["category_id"], "10")
        self.assertEqual(options["general"], [{"id": "1", "name": "General", "missing_permissions": None}])
        self.assertEqual(options["team"], [{"id": "2", "name": "Team A1", "missing_permissions": ["move_members"]}])
        self.assertIsNone(options["error"])

    async def test_voice_options_without_a_category_asks_discord_nothing(self) -> None:
        self.games.get.return_value = _game()
        self._voice_config({}, "5")
        discord = _discord()

        options = await self.service.voice_options(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, actor_user_id=9
        )

        self.assertEqual((options["general"], options["team"]), ([], []))
        self.assertIsNone(options["category_id"])
        self.assertIsNone(options["error"])
        discord.guild_channels.assert_not_awaited()

    async def test_voice_options_reports_a_discord_that_is_down(self) -> None:
        self.games.get.return_value = _game()
        self._voice_config({"mix_voice_category_id": "10"}, "5")
        discord = SimpleNamespace(guild_channels=AsyncMock(side_effect=DiscordUnavailable("down")))

        options = await self.service.voice_options(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, actor_user_id=9
        )

        self.assertEqual(options["error"], "down")
        self.assertEqual((options["general"], options["team"]), ([], []))

    async def test_voice_options_reports_a_category_that_is_gone(self) -> None:
        """The admin picked a category and somebody deleted it: the mix page
        says so instead of offering an empty list as if nothing were wrong."""
        self.games.get.return_value = _game()
        self._voice_config({"mix_voice_category_id": "10"}, "5")

        options = await self.service.voice_options(
            self.session,
            discord=_discord(_channel("20", "Other", "category")),
            workspace_id=1,
            custom_game_id=11,
            actor_user_id=9,
        )

        self.assertEqual(options["error"], "category_not_found")

    async def test_voice_move_sends_each_team_of_a_lobby_to_its_own_voice(self) -> None:
        """One ask to discord-service for the whole lobby; whoever could not be
        asked for is in the same report as whoever was."""
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(
            0,
            balance_result_json=_seated([(7, "Ana"), (8, "Bob")], [(9, "Cid")]),
            team1_voice_channel_id=2,
            team2_voice_channel_id=3,
        )
        self._voice_reads({"mix_voice_category_id": "10"}, "5", {7: "70", 9: "90"})
        discord = SimpleNamespace(
            voice_move=AsyncMock(
                return_value=[
                    {"discord_user_id": "70", "channel_id": "2", "status": "moved", "name": "ana#1"},
                    {"discord_user_id": "90", "channel_id": "3", "status": "not_in_voice", "name": "cid#1"},
                ]
            )
        )

        body = await self.service.voice_move(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
        )

        discord.voice_move.assert_awaited_once_with(
            "5",
            category_id="10",
            moves=[{"discord_user_id": "70", "channel_id": "2"}, {"discord_user_id": "90", "channel_id": "3"}],
            drain=None,
        )
        self.assertEqual(body["moved"], 1)
        self.assertEqual(
            [(row["workspace_member_id"], row["name"], row["status"], row["channel_id"]) for row in body["results"]],
            [(8, "Bob", "no_discord_link", "2"), (7, "Ana", "moved", "2"), (9, "Cid", "not_in_voice", "3")],
        )

    async def test_voice_move_without_a_lobby_moves_the_whole_mix(self) -> None:
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=_seated([(7, "Ana")]), team1_voice_channel_id=2, team2_voice_channel_id=3
        )
        self.lobby_rows[1] = _lobby(
            1, balance_result_json=_seated([(8, "Bob")]), team1_voice_channel_id=4, team2_voice_channel_id=5
        )
        self._voice_reads({"mix_voice_category_id": "10"}, "5", {7: "70", 8: "80"})
        discord = SimpleNamespace(voice_move=AsyncMock(return_value=[]))

        await self.service.voice_move(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=None, actor_user_id=9
        )

        self.assertEqual(
            discord.voice_move.await_args.kwargs["moves"],
            [{"discord_user_id": "70", "channel_id": "2"}, {"discord_user_id": "80", "channel_id": "4"}],
        )

    async def test_voice_move_without_a_configured_category_409(self) -> None:
        """The workspace admin has not picked a mix category: there is no
        category to check the mix's voices against, so nobody is moved."""
        self.games.get.return_value = _game()
        self._voice_config({}, "5")
        discord = SimpleNamespace(voice_move=AsyncMock())

        with self.assertRaises(HTTPException) as ctx:
            await self.service.voice_move(
                self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
            )

        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (409, "voice_not_configured"))
        discord.voice_move.assert_not_awaited()

    async def test_voice_move_with_nobody_to_move_asks_discord_nothing(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=_seated([(7, "Ana")]))
        self._voice_reads({"mix_voice_category_id": "10"}, "5", {7: "70"})
        discord = SimpleNamespace(voice_move=AsyncMock())

        body = await self.service.voice_move(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
        )

        discord.voice_move.assert_not_awaited()
        self.assertEqual(
            body,
            {
                "moved": 0,
                "results": [{"workspace_member_id": 7, "name": "Ana", "status": "not_configured", "channel_id": None}],
            },
        )

    async def test_voice_move_with_discord_down_503(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=_seated([(7, "Ana")]), team1_voice_channel_id=2)
        self._voice_reads({"mix_voice_category_id": "10"}, "5", {7: "70"})
        discord = SimpleNamespace(voice_move=AsyncMock(side_effect=DiscordUnavailable("down")))

        with self.assertRaises(HTTPException) as ctx:
            await self.service.voice_move(
                self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
            )

        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (503, "discord_unavailable"))

    async def test_voice_return_drains_the_team_voices_into_the_general_one(self) -> None:
        """Everyone in the team voices, player or not, goes back -- which is why
        it is a drain of the rooms rather than a list of seats."""
        self.games.get.return_value = _game(general_voice_channel_id=1)
        self.lobby_rows[0] = _lobby(0, team1_voice_channel_id=2, team2_voice_channel_id=3)
        self._voice_config({"mix_voice_category_id": "10", "mix_general_voice_channel_ids": ["1"]}, "5")
        discord = SimpleNamespace(
            voice_move=AsyncMock(
                return_value=[{"discord_user_id": "70", "channel_id": "1", "status": "moved", "name": "ana#1"}]
            )
        )

        body = await self.service.voice_return(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
        )

        discord.voice_move.assert_awaited_once_with(
            "5", category_id="10", moves=[], drain={"channel_ids": ["2", "3"], "to_channel_id": "1"}
        )
        self.assertEqual(
            body,
            {
                "moved": 1,
                "results": [{"workspace_member_id": None, "name": "ana#1", "status": "moved", "channel_id": "1"}],
            },
        )

    async def test_voice_return_without_a_general_voice_409(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, team1_voice_channel_id=2)
        self._voice_config({"mix_voice_category_id": "10", "mix_general_voice_channel_ids": ["1"]}, "5")
        discord = SimpleNamespace(voice_move=AsyncMock())

        with self.assertRaises(HTTPException) as ctx:
            await self.service.voice_return(
                self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
            )

        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (409, "general_voice_not_configured"))
        discord.voice_move.assert_not_awaited()

    async def test_voice_return_into_a_voice_the_workspace_does_not_call_general_409(self) -> None:
        """The mix's general voice was dropped from the workspace's list: a
        return would herd everybody into a room nobody agreed on."""
        self.games.get.return_value = _game(general_voice_channel_id=4)
        self.lobby_rows[0] = _lobby(0, team1_voice_channel_id=2)
        self._voice_config({"mix_voice_category_id": "10", "mix_general_voice_channel_ids": ["1"]}, "5")
        discord = SimpleNamespace(voice_move=AsyncMock())

        with self.assertRaises(HTTPException) as ctx:
            await self.service.voice_return(
                self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
            )

        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (409, "general_voice_outside_category"))
        discord.voice_move.assert_not_awaited()

    async def test_voice_return_of_a_lobby_with_no_team_voices_asks_discord_nothing(self) -> None:
        self.games.get.return_value = _game(general_voice_channel_id=1)
        self._voice_config({"mix_voice_category_id": "10", "mix_general_voice_channel_ids": ["1"]}, "5")
        discord = SimpleNamespace(voice_move=AsyncMock())

        body = await self.service.voice_return(
            self.session, discord=discord, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
        )

        discord.voice_move.assert_not_awaited()
        self.assertEqual(body, {"moved": 0, "results": []})

    async def test_balance_feeds_the_hosts_stored_preferences_to_the_solver(self) -> None:
        """The solver knobs are the HOST's, not the presser's.

        A mix already resolves its ranks against the host's own book, so a
        co-host clicking Balance must get the same matchup the host would.
        """
        self.games.get.return_value = _game()
        self.co_hosts.user_ids_for_game.return_value = [21]
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.host_prefs.get_by_user.return_value = _prefs(config_json={"mix_comfort_tilt": 0.75})

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=21)

        # Exactly once: the same row carries the overrides and the roster shape.
        self.host_prefs.get_by_user.assert_awaited_once_with(self.session, 9)
        _player_data, config_overrides, _progress, _role_mask = self.run_balance.await_args.args
        self.assertEqual(config_overrides, {"mix_comfort_tilt": 0.75})

    async def test_balance_without_stored_preferences_leaves_the_engine_defaults(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        _player_data, config_overrides, _progress, _role_mask = self.run_balance.await_args.args
        self.assertIsNone(config_overrides)

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

        game = await self.service.set_team_names(
            self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=21
        )

        self.assertEqual(game.id, 11)
        self.team_names.set.assert_awaited_once_with(self.session, 11, 0, "Wolves")
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
        await self.service.set_team_names(
            self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=21
        )
        self.team_names.set.assert_awaited_once_with(self.session, 11, 0, "Wolves")

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

    async def test_a_superuser_writes_a_mix_they_neither_host_nor_co_host(self) -> None:
        self.games.get.return_value = _game()

        await self.service.set_team_names(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            team_names={"0": "Wolves"},
            actor_user_id=99,
            actor_is_superuser=True,
        )

        self.team_names.set.assert_awaited_once_with(self.session, 11, 0, "Wolves")

    async def test_a_superuser_still_cannot_write_a_closed_mix_409(self) -> None:
        self.games.get.return_value = _game(status="completed")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.close(
                self.session, workspace_id=1, custom_game_id=11, actor_user_id=99, actor_is_superuser=True
            )

        self.assertEqual(ctx.exception.status_code, 409)

    async def test_remove_co_host_revokes_write_access(self) -> None:
        self.games.get.return_value = _game()
        self.co_hosts.user_ids_for_game.return_value = [21]

        await self.service.remove_co_host(
            self.session, workspace_id=1, custom_game_id=11, co_host_user_id=21, actor_user_id=9
        )
        self.co_hosts.remove.assert_awaited_once_with(self.session, 11, 21)

        self.co_hosts.user_ids_for_game.return_value = []
        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_team_names(
                self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=21
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
        game = _game()
        self.lobby_rows[0] = _lobby(0, next_map_id=42)
        self.games.get.return_value = game

        await self.service.set_team_names(
            self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=9
        )

        self.assertEqual(self.lobby_rows[0].next_map_id, 42)

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

    async def test_roster_shape_reads_the_mixs_frozen_format(self) -> None:
        game = _game()
        shape = await self.service.roster_shape(self.session, game)
        self.format_lookup.assert_awaited_once_with(self.session, game)
        self.assertIs(shape, self.format_read.return_value.roster_shape)

    async def test_roster_shape_passes_the_workspace_to_role_resolution(self) -> None:
        game = _game(workspace_id=42)
        await self.service.roster_shape(self.session, game)
        self.format_read.assert_awaited_once_with(
            self.session, self.format_lookup.return_value[0], source="custom_game", workspace_id=42
        )

    async def test_roster_shape_preserves_the_resolved_source(self) -> None:
        self.format_lookup.return_value = (object(), "preset")
        await self.service.roster_shape(self.session, _game())
        self.assertEqual(self.format_read.await_args.kwargs["source"], "preset")

    async def test_roster_shape_of_a_hostless_mix_never_reads_host_preferences(self) -> None:
        await self.service.roster_shape(self.session, _game(host_user_id=None))
        self.host_prefs.get_by_user.assert_not_awaited()

    async def test_balance_uses_the_mixs_open_slot_projection(self) -> None:
        self.slot_shape.return_value = RosterShape(entries=(("flex", 6),))
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        role_mask = self.run_balance.await_args.args[3]
        self.assertEqual(role_mask, {"flex": 6})

    async def test_balance_uses_the_mixs_role_and_open_slot_projection(self) -> None:
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1), ("flex", 4)))
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = {"teams": []}

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        role_mask = self.run_balance.await_args.args[3]
        self.assertEqual(role_mask, {"tank": 1, "flex": 4})

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

    def _two_team_payload(self) -> dict[str, object]:
        """One two-team option as the solver emits it (``teams_to_json``)."""
        return {
            "teams": [
                {
                    "id": 1,
                    "average_mmr": 3050,
                    "roster": {
                        "tank": [self._seat("p1", "Alpha", 3200, "tank")],
                        "damage": [self._seat("p2", "Bravo", 2900, "damage")],
                    },
                },
                {
                    "id": 2,
                    "average_mmr": 2800,
                    "roster": {
                        "tank": [self._seat("p3", "Charlie", 2600, "tank")],
                        "damage": [self._seat("p4", "Delta", 3000, "damage")],
                    },
                },
            ],
            "statistics": {
                "composite_score": 0.87,
                "mix_balancer_quality_total": 41.5,
                "mix_balancer_fairness": 30.0,
                "mix_balancer_uniformity": 4.0,
                "mix_balancer_role_fairness": 5.5,
                "mix_balancer_role_points": 2.0,
                "mmr_std_dev": 10.0,
                "max_total_rating_gap": 50,
                "off_role_count": 0,
            },
            "benched_players": [],
        }

    def _two_team_result(self) -> dict[str, object]:
        """What ``run_mix_balance`` stores for that option."""
        return lobby_document([self._two_team_payload()])

    async def test_swap_seats_swaps_players_and_recomputes_stats(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())

        await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="p1",
            second_uuid="p3",
            actor_user_id=9,
        )

        teams = self.lobby_rows[0].balance_result_json["variants"][0]["teams"]
        self.assertEqual(teams[0]["roster"]["tank"], ["p3"])
        self.assertEqual(teams[1]["roster"]["tank"], ["p1"])
        # Team 1 is now Charlie(2600)+Bravo(2900) = 5500/2 = 2750; team 2 is
        # now Alpha(3200)+Delta(3000) = 6200/2 = 3100.
        self.assertEqual(teams[0]["average_mmr"], 2750.0)
        self.assertEqual(teams[1]["average_mmr"], 3100.0)
        statistics = self.lobby_rows[0].balance_result_json["variants"][0]["statistics"]
        self.assertEqual(statistics["max_total_rating_gap"], 700.0)
        self.assertAlmostEqual(statistics["mmr_std_dev"], 247.487, places=2)
        self.assertEqual(statistics["off_role_count"], 0)
        # The knee-score is population-relative to the solver's Pareto archive
        # for that run -- meaningless for a single hand-edited arrangement, so
        # a manual swap clears it rather than leaving a now-fabricated number.
        self.assertIsNone(statistics["composite_score"])

    async def test_swap_seats_upgrades_a_document_stored_in_the_old_form(self) -> None:
        # A mix balanced before the lobby form stored the solver's payloads
        # verbatim; a swap on it must work and write back the lobby form.
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [self._two_team_payload()]})

        await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="p1",
            second_uuid="p3",
            actor_user_id=9,
        )

        stored = self.lobby_rows[0].balance_result_json
        self.assertEqual(stored["variants"][0]["teams"][0]["roster"]["tank"], ["p3"])
        self.assertEqual(stored["players"]["p1"]["ratings"], {"tank": 3200})
        self.assertEqual(stored["variants"][0]["teams"][1]["total_rating"], 6200.0)

    async def test_swap_seats_clears_every_engine_scored_metric(self) -> None:
        # The mix engine's four terms and their total describe the seating it
        # chose; a hand-moved player invalidates all of them, most of all the
        # role-priority term. Left behind they would read as current.
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())

        await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="p1",
            second_uuid="p3",
            actor_user_id=9,
        )

        statistics = self.lobby_rows[0].balance_result_json["variants"][0]["statistics"]
        for key in (
            "mix_balancer_quality_total",
            "mix_balancer_fairness",
            "mix_balancer_uniformity",
            "mix_balancer_role_fairness",
            "mix_balancer_role_points",
        ):
            self.assertIsNone(statistics[key], key)
        # The teams' own totals stay, recomputed from the seats on screen.
        teams = self.lobby_rows[0].balance_result_json["variants"][0]["teams"]
        self.assertEqual(5500.0, teams[0]["total_rating"])
        self.assertEqual(6200.0, teams[1]["total_rating"])

    async def test_swap_seats_counts_off_role_after_the_move(self) -> None:
        result = self._two_team_result()
        # Bravo actually prefers tank but was seated at damage -- already off-role
        # before the swap, and moving them must not silently "fix" that count.
        result["players"]["p2"]["role_preferences"] = ["tank", "damage"]
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=result)

        await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="p2",
            second_uuid="p4",
            actor_user_id=9,
        )

        statistics = self.lobby_rows[0].balance_result_json["variants"][0]["statistics"]
        self.assertEqual(statistics["off_role_count"], 1)

    async def test_swap_seats_rejects_different_roles(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())
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
        result["variants"][0]["teams"][0]["roster"]["tank"].append("p5")
        result["players"]["p5"] = {"name": "Echo", "ratings": {"tank": 3100}}
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=result)
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
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())
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
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())
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
                self.games.get.return_value = _game(status=status)
                self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())
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
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())
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

    def _captained_result(self) -> dict[str, object]:
        """Two teams of member seats: 7 (3200) and 8 (2900) against 9 (2600) and 10 (3000)."""
        return lobby_document(
            [
                {
                    "teams": [
                        {
                            "roster": {
                                "tank": [self._seat("7", "Alpha", 3200, "tank")],
                                "damage": [self._seat("8", "Bravo", 2900, "damage")],
                            }
                        },
                        {
                            "roster": {
                                "tank": [self._seat("9", "Charlie", 2600, "tank")],
                                "damage": [self._seat("10", "Delta", 3000, "damage")],
                            }
                        },
                    ]
                }
            ]
        )

    def _captains(self) -> list[int | None]:
        return [team["captain_member_id"] for team in self.lobby_rows[0].balance_result_json["variants"][0]["teams"]]

    async def test_balance_captains_each_team_by_its_strongest_seat(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = self._captained_result()

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual([7, 10], self._captains())

    async def test_swapping_a_captain_captains_both_teams_afresh(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=with_captains(self._captained_result()))

        # Alpha (team 1's captain) and Charlie trade tank seats.
        await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="7",
            second_uuid="9",
            actor_user_id=9,
        )

        # Team 1 is now Charlie 2600 + Bravo 2900, team 2 Alpha 3200 + Delta 3000.
        self.assertEqual([8, 7], self._captains())

    async def test_a_swap_between_two_non_captains_keeps_both_captains(self) -> None:
        document = with_captains(self._captained_result())
        document["variants"][0]["teams"][1]["captain_member_id"] = 9  # the host's pick for team 2
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=document)

        await self.service.swap_seats(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            variant_index=0,
            first_uuid="8",
            second_uuid="10",
            actor_user_id=9,
        )

        self.assertEqual([7, 9], self._captains())

    async def test_make_captain_hands_the_crown_to_a_seat_of_the_shown_option(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=with_captains(self._captained_result()))

        await self.service.set_captain(
            self.session, workspace_id=1, custom_game_id=11, workspace_member_id=9, actor_user_id=9
        )

        self.assertEqual([7, 9], self._captains())

    async def test_make_captain_of_somebody_the_option_does_not_seat_404(self) -> None:
        self.games.get.return_value = _game()
        self.lobby_rows[0] = _lobby(0, balance_result_json=with_captains(self._captained_result()))

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_captain(
                self.session, workspace_id=1, custom_game_id=11, workspace_member_id=99, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual([7, 10], self._captains())

    async def test_start_match_on_a_live_lobby_409(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._captained_result(), live_encounter_id=900)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.start_match(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual((409, "match_live"), (ctx.exception.status_code, ctx.exception.detail))
        self.open_match.assert_not_awaited()

    async def test_record_outcome_without_a_live_match_409(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._captained_result())

        with self.assertRaises(HTTPException) as ctx:
            await self.service.record_outcome(
                self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9
            )

        self.assertEqual((409, "no_live_match"), (ctx.exception.status_code, ctx.exception.detail))
        self.write_result.assert_not_awaited()

    async def test_record_outcome_closes_the_live_match_and_leaves_the_mix_open(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._captained_result(), live_encounter_id=900)
        self.team_names.mapping_for_game.return_value = {0: "Wolves"}

        game = await self.service.record_outcome(
            self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9
        )

        # Repeatable: recording a result never closes the mix.
        self.assertEqual(game.status, "balanced")
        draft = self._draft()
        self.assertEqual(
            (
                draft.encounter_id,
                draft.lobby_index,
                draft.names,
                draft.lineup_first_team,
                draft.winner,
                draft.recorder_player_id,
            ),
            (900, 0, ("Wolves", "Team 2"), frozenset({7, 8}), 1, 70),
        )
        self.assertIsNone(self.lobby_rows[0].live_encounter_id)
        self.players.get_id_by_auth_user_id.assert_awaited_once_with(self.session, 9)

    async def test_record_outcome_clears_the_next_map_its_match_was_played_on(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=self._captained_result(), live_encounter_id=900, next_map_id=42
        )

        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=None, actor_user_id=9)

        self.assertIsNone(self.lobby_rows[0].next_map_id)

    async def test_cancel_match_throws_the_live_encounter_away_and_moves_nothing(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=self._captained_result(), live_encounter_id=900, next_map_id=42
        )
        self.host_prefs.get_by_user.return_value = _prefs(points_per_win=25)

        await self.service.cancel_match(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.mix_rounds.delete_round.assert_awaited_once_with(self.session, 900)
        self.assertIsNone(self.lobby_rows[0].live_encounter_id)
        # Nothing was played: the roll stays for the restart, and no book moves.
        self.assertEqual(42, self.lobby_rows[0].next_map_id)
        self.ranks.set_ranks.assert_not_awaited()
        self.write_result.assert_not_awaited()

    async def test_cancel_match_without_a_live_match_409(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._captained_result())

        with self.assertRaises(HTTPException) as ctx:
            await self.service.cancel_match(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual((409, "no_live_match"), (ctx.exception.status_code, ctx.exception.detail))
        self.mix_rounds.delete_round.assert_not_awaited()

    async def test_close_cancels_every_live_match_first(self) -> None:
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, live_encounter_id=900)
        self.lobby_rows[1] = _lobby(1, live_encounter_id=901)

        game = await self.service.close(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual("completed", game.status)
        self.assertEqual([900, 901], [call.args[1] for call in self.mix_rounds.delete_round.await_args_list])
        self.assertEqual([None, None], [row.live_encounter_id for row in self.lobby_rows.values()])

    async def test_a_live_lobby_refuses_every_write_that_reshapes_its_lineup_409(self) -> None:
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[1] = _lobby(1)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        writes = {
            "swap seats": lambda: self.service.swap_seats(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                variant_index=0,
                first_uuid="7",
                second_uuid="9",
                actor_user_id=9,
            ),
            "page the options": lambda: self.service.set_variant_index(
                self.session, workspace_id=1, custom_game_id=11, variant_index=0, actor_user_id=9
            ),
            "roll the next map": lambda: self.service.set_next_map(
                self.session, workspace_id=1, custom_game_id=11, map_id=42, actor_user_id=9
            ),
            "make a captain": lambda: self.service.set_captain(
                self.session, workspace_id=1, custom_game_id=11, workspace_member_id=9, actor_user_id=9
            ),
            "balance the lobby": lambda: self.service.balance(
                self.session, workspace_id=1, custom_game_id=11, actor_user_id=9
            ),
            "shuffle every lobby": lambda: self.service.balance(
                self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9
            ),
        }
        for name, write in writes.items():
            with self.subTest(name):
                document = with_captains(self._captained_result())
                self.lobby_rows[0] = _lobby(0, balance_result_json=document, live_encounter_id=900, next_map_id=5)
                with self.assertRaises(HTTPException) as ctx:
                    await write()
                self.assertEqual((409, "match_live"), (ctx.exception.status_code, ctx.exception.detail))
                lobby = self.lobby_rows[0]
                self.assertIs(document, lobby.balance_result_json)
                self.assertEqual((0, 5), (lobby.selected_variant_index, lobby.next_map_id))
        self.run_balance.assert_not_awaited()

    async def test_a_live_lobby_refuses_a_balance_before_it_reads_the_lineup_409(self) -> None:
        # Everyone is benched: an empty lineup, which is 422 empty_lineup anywhere but under a live match.
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, live_encounter_id=900)
        self.lobby_rows[1] = _lobby(1)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0, participation=MixParticipation.BENCHED)]

        for scope in ("lobby", "all"):
            with self.subTest(scope):
                with self.assertRaises(HTTPException) as ctx:
                    await self.service.balance(
                        self.session, workspace_id=1, custom_game_id=11, scope=scope, actor_user_id=9
                    )
                self.assertEqual((409, "match_live"), (ctx.exception.status_code, ctx.exception.detail))

    async def test_dropping_a_lobby_with_a_live_match_409(self) -> None:
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[1] = _lobby(1, live_encounter_id=901)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_lobby_count(
                self.session, workspace_id=1, custom_game_id=11, lobby_count=1, actor_user_id=9
            )

        self.assertEqual((409, "match_live"), (ctx.exception.status_code, ctx.exception.detail))
        self.assertEqual([0, 1], sorted(self.lobby_rows))

    async def test_a_live_lobby_keeps_team_names_and_player_edits_open(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=with_captains(self._captained_result()), live_encounter_id=900
        )
        row = _roster_row(1, 7, 0)
        self.roster.list_for_game.return_value = [row]
        names: dict[tuple[int, int], str | None] = {}
        self.team_names.set.side_effect = lambda _s, game_id, index, value: names.__setitem__((game_id, index), value)

        await self.service.set_team_names(
            self.session, workspace_id=1, custom_game_id=11, team_names={"0": "Wolves"}, actor_user_id=9
        )
        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"participation": "benched"},
            actor_user_id=9,
        )

        self.assertEqual({(11, 0): "Wolves"}, names)
        self.assertEqual(MixParticipation.BENCHED, row.participation)

    async def test_a_live_lobby_does_not_freeze_its_neighbour(self) -> None:
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=with_captains(self._captained_result()), live_encounter_id=900
        )
        self.lobby_rows[1] = _lobby(1)

        await self.service.set_next_map(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, map_id=42, actor_user_id=9
        )

        self.assertEqual(42, self.lobby_rows[1].next_map_id)

    async def test_balance_leaves_an_away_player_out_even_when_must_play(self) -> None:
        away = _roster_row(1, 7, 0, participation=MixParticipation.MUST_PLAY, away=True)
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [away, _roster_row(2, 8, 1)]
        self.ranks.resolve.return_value = _ranks(7, 8)
        # The solver seats everyone it is handed, so the stored lineup shows who was a candidate.
        self.run_balance.side_effect = lambda data, *_: _seated([(int(uuid), uuid) for uuid in data["players"]])

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual(frozenset({8}), seated_member_ids(self.lobby_rows[0].balance_result_json, 0))
        # The mark is kept: it seats them first once they are back.
        self.assertEqual(MixParticipation.MUST_PLAY, away.participation)

    async def test_rotation_leaves_an_away_player_out(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, away=True),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2),
        ]

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual({8, 9}, {rec.member_id for rec in recommendations})

    async def test_record_outcome_writes_an_away_member_as_busy(self) -> None:
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=self._captained_result(), live_encounter_id=900)
        self.roster.list_for_game.return_value = [_roster_row(1, 12, 0, away=True)]
        busy_by_round: dict[int, frozenset[int]] = {}
        self.write_result.side_effect = lambda _s, draft: busy_by_round.__setitem__(draft.encounter_id, draft.busy)

        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9)

        # Rotation skips the round for them exactly like for somebody playing next door.
        self.assertEqual({900: frozenset({12})}, busy_by_round)

    async def test_the_host_marks_a_player_away_and_back(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [row]

        for away in (True, False):
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"away": away},
                actor_user_id=9,
            )
            self.assertIs(away, row.away)

    async def test_a_player_steps_away_and_back_without_the_role_edit_switch(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=False)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        state = await self.service.self_set_away(
            self.session, custom_game_id=11, auth_user=_auth(), away=True, workspace_id=1
        )
        self.assertTrue(row.away)
        self.assertTrue(state["seat"]["away"])

        await self.service.self_set_away(self.session, custom_game_id=11, auth_user=_auth(), away=False, workspace_id=1)
        self.assertFalse(row.away)

    async def test_stepping_away_off_the_roster_404(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_set_away(
                self.session, custom_game_id=11, auth_user=_auth(), away=True, workspace_id=1
            )

        self.assertEqual((404, "not_on_roster"), (ctx.exception.status_code, ctx.exception.detail))

    async def test_self_state_links_the_voice_of_the_players_own_team(self) -> None:
        row = _roster_row(1, 9, 0)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=9, player_id=70)
        self.lobby_rows[0] = _lobby(
            0, balance_result_json=self._captained_result(), team1_voice_channel_id=111, team2_voice_channel_id=222
        )
        self._voice_config({}, "555")

        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        # Charlie (9) plays on team 2.
        self.assertEqual(
            (0, 9, "https://discord.com/channels/555/222"),
            (state["seat"]["current_lobby"], state["seat"]["workspace_member_id"], state["seat"]["voice_url"]),
        )

    async def test_rotation_returns_empty_list_for_an_empty_pool(self) -> None:
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = []

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)

        self.assertEqual(recommendations, [])

    async def test_rotation_ranks_pool_by_map_history_and_splits_at_seat_count(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2, pool of 3 -> exactly one seat short next map.
        self.games.get.return_value = _game()
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1), ("damage", 1)))
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
        ]
        # Newest-first, as CustomGameRoundRepository.list_for_custom_game returns it.
        self.mix_rounds.list_for_custom_game = AsyncMock(
            return_value=[
                _round(2, created_at=2, first=[9], second=[7]),  # 7 & 9 played, 8 sat
                _round(1, created_at=1, first=[7], second=[8]),  # 7 & 8 played, 9 sat
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
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1), ("damage", 1)))
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=5),  # joined after the only map recorded so far
        ]
        self.mix_rounds.list_for_custom_game = AsyncMock(return_value=[_round(1, created_at=1, first=[7], second=[])])

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

    async def test_rotation_counts_a_match_spent_in_the_other_lobby_as_neither(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2, pool of 3 -> one seat short. Two maps were played
        # in lobby A; 9 spent the first of them on the floor of lobby B.
        self.games.get.return_value = _game()
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1), ("damage", 1)))
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
        ]
        self.mix_rounds.list_for_custom_game = AsyncMock(
            return_value=[
                _round(2, created_at=2, first=[7], second=[8]),  # 7 & 8 played, 9 sat
                _round(1, created_at=1, first=[7], second=[8], busy=[9]),  # 9 was in lobby B
            ]
        )

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)
        by_id = {rec.member_id: rec for rec in recommendations}

        # One map missed, not two: the first never counted against 9 at all.
        self.assertEqual(by_id[9].consecutive_sat, 1)
        self.assertEqual(by_id[9].games_played, 0)
        # 7 and 8 played both maps in a row, so one of them makes room and the
        # single sat-out map is still enough to owe 9 the next seat.
        self.assertEqual(by_id[9].status, RotationStatus.MUST_PLAY)

    async def test_rotation_of_a_one_lobby_mix_has_nothing_to_skip(self) -> None:
        """No busy rows anywhere: the verdict is the one this mix always got."""
        from src.domain.mix_rotation import RotationStatus

        self.games.get.return_value = _game()
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1), ("damage", 1)))
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
        ]
        self.mix_rounds.list_for_custom_game = AsyncMock(
            return_value=[
                _round(2, created_at=2, first=[7], second=[8]),
                _round(1, created_at=1, first=[7], second=[8]),
            ]
        )

        by_id = {
            rec.member_id: rec for rec in await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)
        }

        self.assertEqual(by_id[9].consecutive_sat, 2)
        self.assertEqual(by_id[9].status, RotationStatus.MUST_PLAY)
        # 7 and 8 tie on history; input order seats 7 and benches 8.
        self.assertEqual(by_id[7].status, RotationStatus.NEUTRAL)
        self.assertEqual(by_id[8].status, RotationStatus.SHOULD_REST)

    async def test_per_lobby_writes_touch_only_their_own_lobby(self) -> None:
        """Lobby B rolls its own map and pages its own option; lobby A keeps
        the map and the option the host set for it."""
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, next_map_id=42, balance_result_json=lobby_document([{"teams": []}]))
        self.lobby_rows[1] = _lobby(1, balance_result_json=lobby_document([{"teams": []}, {"teams": []}]))

        await self.service.set_next_map(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, map_id=5, actor_user_id=9
        )
        await self.service.set_variant_index(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, variant_index=1, actor_user_id=9
        )

        self.assertEqual(self.lobby_rows[1].next_map_id, 5)
        self.assertEqual(self.lobby_rows[1].selected_variant_index, 1)
        self.assertEqual(self.lobby_rows[0].next_map_id, 42)
        self.assertEqual(self.lobby_rows[0].selected_variant_index, 0)

    async def test_set_variant_index_refuses_an_option_seating_the_other_lobby_409(self) -> None:
        """Two co-hosts page at once: an option that seats somebody lobby A has
        already put on the floor is not a matchup anybody can play."""
        seated = [{"teams": [{"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}}, {"roster": {}}]}]
        contested = [
            {"teams": [{"roster": {"tank": [self._seat("8", "Bravo", 2900, "tank")]}}, {"roster": {}}]},
            {"teams": [{"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}}, {"roster": {}}]},
        ]
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(seated))
        self.lobby_rows[1] = _lobby(1, balance_result_json=lobby_document(contested))

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_variant_index(
                self.session, workspace_id=1, custom_game_id=11, lobby_index=1, variant_index=1, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "seat_conflict")
        self.assertEqual(self.lobby_rows[1].selected_variant_index, 0)

    async def test_record_outcome_stamps_its_lobby_and_who_was_in_the_other(self) -> None:
        """The match belongs to a lobby, and it remembers who was unavailable --
        playing next door -- so rotation does not read that as sitting out."""
        playing = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                    {"roster": {"tank": [self._seat("8", "Bravo", 2900, "tank")]}},
                ]
            }
        ]
        elsewhere = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    {"roster": {"tank": [self._seat("10", "Delta", 3000, "tank")]}},
                ]
            }
        ]
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, next_map_id=42, balance_result_json=lobby_document(elsewhere))
        self.lobby_rows[1] = _lobby(
            1, next_map_id=7, balance_result_json=lobby_document(playing), live_encounter_id=900
        )

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            lobby_index=1,
            winner=1,
            actor_user_id=9,
        )

        draft = self._draft()
        self.assertEqual((draft.lobby_index, draft.busy), (1, frozenset({9, 10})))
        # Only this lobby's roll is consumed; lobby A still has its own.
        self.assertIsNone(self.lobby_rows[1].next_map_id)
        self.assertEqual(self.lobby_rows[0].next_map_id, 42)

    async def test_record_outcome_of_lobby_b_names_its_own_two_teams(self) -> None:
        """Team names are stored by GLOBAL index, so lobby B's two teams are
        rows 2 and 3 -- not a second reading of lobby A's 0 and 1."""
        playing = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                    {"roster": {"tank": [self._seat("8", "Bravo", 2900, "tank")]}},
                ]
            }
        ]
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[1] = _lobby(1, balance_result_json=lobby_document(playing), live_encounter_id=900)
        self.team_names.mapping_for_game.return_value = {0: "Wolves", 1: "Ravens", 2: "Owls"}

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            lobby_index=1,
            winner=1,
            actor_user_id=9,
        )

        self.assertEqual(self._draft().names, ("Owls", "Team 2"))

    async def test_record_outcome_of_a_one_lobby_mix_records_no_busy_players(self) -> None:
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
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), live_encounter_id=900)

        await self.service.record_outcome(self.session, workspace_id=1, custom_game_id=11, winner=1, actor_user_id=9)

        self.assertEqual((self._draft().lobby_index, self._draft().busy), (0, frozenset()))

    async def test_undo_targets_the_newest_match_of_its_own_lobby(self) -> None:
        """Lobby A's last match is undoable even while lobby B has recorded a
        newer one: the rank book compounds per mix, but the pair a host is
        looking at is their own lobby's."""
        self.games.get.return_value = _game(lobby_count=2)
        self.mix_rounds.get_for_game.return_value = _round(501, created_at=1, first=[7], second=[9], lobby_index=0)
        self.mix_rounds.newest_id_for_lobby.return_value = 501

        await self.service.undo_last_match(
            self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
        )

        self.mix_rounds.newest_id_for_lobby.assert_awaited_once_with(self.session, 11, 0)
        self.mix_rounds.delete_round.assert_awaited_once()

    async def test_undo_refuses_an_older_match_of_the_same_lobby_409(self) -> None:
        self.games.get.return_value = _game(lobby_count=2)
        self.mix_rounds.get_for_game.return_value = _round(501, created_at=1, first=[7], second=[9], lobby_index=1)
        self.mix_rounds.newest_id_for_lobby.return_value = 503

        with self.assertRaises(HTTPException) as ctx:
            await self.service.undo_last_match(
                self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.mix_rounds.newest_id_for_lobby.assert_awaited_once_with(self.session, 11, 1)
        self.mix_rounds.delete_round.assert_not_awaited()

    async def test_discord_lineup_names_the_lobby_and_counts_its_own_games(self) -> None:
        """Two lobbies keep two paces: "game 3" of B is not "game 3" of A."""
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"Tank": [{"uuid": "1", "name": "Ana", "assigned_rating": 3000}]}},
                        {"roster": {"Tank": [{"uuid": "2", "name": "Bob", "assigned_rating": 2900}]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[1] = _lobby(1, balance_result_json=lobby_document(result["variants"]))
        # Stored by global index: lobby B's first team is row 2.
        self.team_names.mapping_for_game.return_value = {0: "Blue", 2: "Red"}
        self.mix_rounds.activity_for_lobbies = AsyncMock(
            return_value={0: (5, datetime(2026, 1, 1, 20, 0)), 1: (2, datetime(2026, 1, 1, 20, 5))}
        )
        self._channel("555")

        await self.service.discord_lineup(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            lobby_index=1,
            variant_index=0,
            actor_user_id=9,
        )

        # Lobby B's own slot: its game 3, not the mix's eighth match.
        self.assertEqual("lineup:1:3", self.messages.rows[-1].slot)
        [lineup] = (await self.service.discord_view(self.session, 11, [(1, 3)], board_url_base="https://owt.example"))[
            "lineups"
        ]
        self.assertEqual(
            (lineup["current"], lineup["lobby_label"], lineup["team_names"], lineup["voice_target"]),
            (True, "B", {"0": "Red"}, "11-1"),
        )

    async def test_rotation_of_one_lobby_ignores_whoever_is_playing_the_other(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2 -> one lobby is four seats; 9 and 10 are on the
        # floor in lobby A and 11 is pinned to A, so lobby B ranks 7 and 8 only.
        seated = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    {"roster": {"tank": [self._seat("10", "Delta", 3000, "tank")]}},
                ]
            }
        ]
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(seated))
        self.lobby_rows[1] = _lobby(1)
        self.slot_shape.return_value = RosterShape(entries=(("tank", 1), ("damage", 1)))
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
            _roster_row(4, 10, 3, created_at=0),
            _roster_row(5, 11, 4, created_at=0, lobby_pin=0),
        ]

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11, lobby_index=1)

        self.assertEqual(sorted(rec.member_id for rec in recommendations), [7, 8])
        self.assertTrue(all(rec.status is not RotationStatus.SHOULD_REST for rec in recommendations))

    async def test_hard_delete_removes_the_game_row(self) -> None:
        game = _game()
        rule = _row(id=5)
        self.games.get.return_value = game
        self.games.delete = AsyncMock()
        self.scoring_rules.get.return_value = rule

        await self.service.hard_delete(self.session, workspace_id=1, custom_game_id=11)

        self.games.delete.assert_awaited_once_with(self.session, game)
        self.scoring_rules.delete.assert_awaited_once_with(self.session, rule)

    async def test_hard_delete_404s_a_game_from_another_workspace(self) -> None:
        self.games.get.return_value = _game(workspace_id=2)
        self.games.delete = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.hard_delete(self.session, workspace_id=1, custom_game_id=11)
        self.assertEqual(ctx.exception.status_code, 404)
        self.games.delete.assert_not_awaited()

    async def test_create_starts_with_the_hosts_formation_default_for_its_game(self) -> None:
        self.host_prefs.get_by_user.return_value = _prefs(
            formation_defaults={"overwatch": {"team_formation": "draft", "draft_pick_seconds": 45}}
        )

        game = await self.service.create(
            self.session, workspace_id=1, discipline="overwatch", host_user_id=9, name="Scrim", actor_user_id=9
        )

        self.assertEqual(("draft", 45), (game.team_formation, game.draft_pick_seconds))

    async def test_create_clone_keeps_its_sources_formation_over_the_host_default(self) -> None:
        self.games.get.return_value = _game(id=5, team_formation="draft", draft_pick_seconds=60)
        self.roster.list_for_game.return_value = []
        self.host_prefs.get_by_user.return_value = _prefs(
            formation_defaults={"overwatch": {"team_formation": "balance", "draft_pick_seconds": 20}}
        )

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Rematch",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertEqual(("draft", 60), (game.team_formation, game.draft_pick_seconds))

    async def test_a_host_sets_the_formation_and_the_pick_clock(self) -> None:
        self.games.get.return_value = _game()

        game = await self.service.set_draft_settings(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            team_formation="draft",
            draft_pick_seconds=90,
            actor_user_id=9,
        )

        self.assertEqual(("draft", 90), (game.team_formation, game.draft_pick_seconds))

    async def test_create_clone_keeps_its_sources_fearless(self) -> None:
        self.games.get.return_value = _game(id=5, hero_fearless=True)
        self.roster.list_for_game.return_value = []

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Rematch",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertTrue(game.hero_fearless)

    async def test_a_host_turns_fearless_on_and_a_preset_edit_leaves_it_on(self) -> None:
        self.games.get.return_value = _game()

        game = await self.service.set_ban_preset(
            self.session, workspace_id=1, custom_game_id=11, hero_ban_preset=None, hero_fearless=True, actor_user_id=9
        )
        self.assertTrue(game.hero_fearless)

        game = await self.service.set_ban_preset(
            self.session, workspace_id=1, custom_game_id=11, hero_ban_preset="hero_classic", actor_user_id=9
        )
        self.assertEqual(("hero_classic", True), (game.hero_ban_preset, game.hero_fearless))


class _AwaitableSession:
    """A sync SQLAlchemy session behind the one awaitable ``hosted_active`` uses.

    The read is a single ``SELECT`` with the whole answer in its WHERE clause,
    so a mocked session would only prove it was called. The suite has no async
    SQLite driver (see ``test_custom_game_undo_cascade.py``), and ``execute`` is
    all this query needs.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement):  # noqa: ANN001, ANN202
        return self._session.execute(statement)


class HostedActiveMixesTests(IsolatedAsyncioTestCase):
    """What ``/mix move``'s autocomplete offers: the open mixes this account may run."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        install_postgres_type_shims()
        tables = [models.CustomGame.__table__, models.CustomGameCoHost.__table__]
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)
        self.sync_session = Session(self.engine)
        self.addCleanup(self.sync_session.close)
        self.session = _AwaitableSession(self.sync_session)
        self.service = CustomGameService()

    def _mix(self, game_id: int, name: str, *, host_user_id: int | None = 9, status: str = "draft", **fields) -> None:
        self.sync_session.execute(
            sa.insert(models.CustomGame.__table__).values(
                id=game_id,
                workspace_id=fields.pop("workspace_id", 1),
                host_user_id=host_user_id,
                name=name,
                status=status,
                lobby_count=fields.pop("lobby_count", 1),
                self_signup="closed",
                self_role_edit=False,
                scoring_rule_id=5,
                **fields,
            )
        )

    async def test_the_caller_is_offered_the_mixes_they_host_or_co_host_newest_first(self) -> None:
        self._mix(11, "Понедельник")
        self._mix(12, "Вторник", host_user_id=99, lobby_count=2)
        self.sync_session.execute(sa.insert(models.CustomGameCoHost.__table__).values(custom_game_id=12, user_id=9))
        self._mix(13, "Чужой", host_user_id=99)

        mixes = await self.service.hosted_active(self.session, workspace_id=1, auth_user=_auth(9))

        self.assertEqual(
            mixes,
            [{"id": 12, "name": "Вторник", "lobby_count": 2}, {"id": 11, "name": "Понедельник", "lobby_count": 1}],
        )

    async def test_a_mix_that_is_over_or_in_another_workspace_is_not_offered(self) -> None:
        self._mix(11, "Открытый", status="balanced")
        self._mix(12, "Сыгранный", status="completed")
        self._mix(13, "Отменённый", status="cancelled")
        self._mix(14, "Соседний", workspace_id=2)

        mixes = await self.service.hosted_active(self.session, workspace_id=1, auth_user=_auth(9))

        self.assertEqual([row["id"] for row in mixes], [11])

    async def test_a_superuser_is_offered_every_open_mix_of_the_workspace(self) -> None:
        self._mix(11, "Чужой", host_user_id=99)

        auth_user = _auth(1)
        auth_user.is_superuser = True
        mixes = await self.service.hosted_active(self.session, workspace_id=1, auth_user=auth_user)

        self.assertEqual([row["id"] for row in mixes], [11])


class MixMapDisciplineTests(IsolatedAsyncioTestCase):
    async def test_a_map_of_another_discipline_is_not_found(self) -> None:
        maps = SimpleNamespace(exists=AsyncMock(return_value=False))
        service = CustomGameService(maps=maps)
        service._writable = AsyncMock(return_value=SimpleNamespace(discipline="lol"))
        with self.assertRaises(custom_game_module.HTTPException) as raised:
            await service.set_next_map(object(), workspace_id=1, custom_game_id=2, map_id=99, actor_user_id=3)
        assert raised.exception.status_code == 404
        maps.exists.assert_awaited_once_with(ANY, id=99, discipline="lol")


class MixCloneDisciplineTests(IsolatedAsyncioTestCase):
    async def test_a_clone_is_gated_on_its_source_s_discipline_not_the_request_default(self) -> None:
        # Scan F03: D89 checks the discipline the new mix actually gets.
        service = CustomGameService(
            games=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=7, workspace_id=1, discipline="lol")))
        )
        service.workspaces = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(disciplines_enabled=["overwatch"]))
        )
        service.members = AsyncMock(return_value=[])
        with self.assertRaises(custom_game_module.HTTPException) as raised:
            await service.create(
                object(),
                workspace_id=1,
                discipline="overwatch",
                host_user_id=3,
                name="x",
                actor_user_id=3,
                clone_from_game_id=7,
            )
        assert raised.exception.status_code == 422
        assert "discipline_not_enabled" in str(raised.exception.detail)


def test_lol_mix_creation_and_clone_play_on_lols_own_grid_never_overwatchs() -> None:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from shared.repository.workspace import WorkspaceRepository
    from shared.services.division_grid import cache as grid_cache
    from shared.services.division_grid.access import get_effective_division_grid
    from shared.services.member_rank import MemberRankService
    from shared.testing import create_test_async_engine
    from shared.testing.cache import configure_test_cache

    async def run():
        configure_test_cache()
        engine = create_test_async_engine()
        db_session = AsyncSession(engine, expire_on_commit=False)
        await ontology.project_disciplines(db_session)
        tag = uuid.uuid4().hex
        workspace = models.Workspace(
            slug=tag, name=tag, disciplines_enabled=["overwatch", "lol"], division_grid_defaults=[]
        )
        host = models.AuthUser(email=f"{tag}@example.test", username=tag)
        db_session.add_all([workspace, host])
        await db_session.flush()
        workspace_id = workspace.id
        service = CustomGameService()
        args = {"workspace_id": workspace.id, "host_user_id": host.id, "actor_user_id": host.id, "name": "LoL"}
        try:
            # LoL has a ladder of its own: a mix needs no organiser grid.
            await service.create(db_session, **args, discipline="lol")
            grid = models.DivisionGrid(workspace_id=workspace.id, slug="lol", name="LoL", discipline="lol")
            version = models.DivisionGridVersion(grid=grid, version=1, label="LoL", status="published", tiers=[])
            db_session.add(version)
            await db_session.flush()
            await WorkspaceRepository().set_default_grid_version(
                db_session, workspace, discipline="lol", version_id=version.id
            )
            await grid_cache.invalidate_workspace(workspace.id)
            version.tiers.append(
                models.DivisionGridTier(
                    slug="organiser",
                    number=9,
                    name="Organiser",
                    sort_order=0,
                    rank_min=0,
                    rank_max=None,
                    icon_url="/tier.png",
                )
            )
            await db_session.flush()
            created = await service.create(db_session, **args, discipline="lol")
            player = models.User(name="LoL player", auth_user_id=host.id)
            db_session.add(player)
            await db_session.flush()
            member = models.WorkspaceMember(workspace_id=workspace.id, player_id=player.id)
            db_session.add(member)
            await db_session.flush()
            db_session.add(models.CustomGamePlayer(custom_game_id=created.id, workspace_member_id=member.id))
            await MemberRankService().set_ranks(
                db_session,
                workspace_id=workspace.id,
                discipline="lol",
                workspace_member_id=member.id,
                ranks={"support": 200},
            )
            await db_session.flush()
            before_state = await service.self_state(db_session, custom_game_id=created.id, auth_user=host)
            assert before_state["seat"]["ranks"]["support"] == 200
            # The badge reads League's own ladder, as Overwatch's reads its ladder.
            assert before_state["seat"]["divisions"]["support"] == {"name": "Iron II", "slug": "iron-2"}
            ow = models.DivisionGrid(workspace_id=workspace.id, slug="ow", name="OW", discipline="overwatch")
            ow_version = models.DivisionGridVersion(
                grid=ow,
                version=1,
                label="OW",
                status="published",
                tiers=[
                    models.DivisionGridTier(
                        slug="ow",
                        number=4,
                        name="OW",
                        sort_order=0,
                        rank_min=0,
                        rank_max=None,
                        icon_url="/ow.png",
                    )
                ],
            )
            db_session.add(ow_version)
            await db_session.flush()
            await get_effective_division_grid(db_session, workspace.id, discipline="overwatch")
            await get_effective_division_grid(db_session, workspace.id, discipline="lol")
            await WorkspaceRepository().set_default_grid_version(
                db_session, workspace, discipline="overwatch", version_id=ow_version.id
            )
            await grid_cache.invalidate_workspace(workspace.id)
            after_state = await service.self_state(db_session, custom_game_id=created.id, auth_user=host)
            assert after_state["seat"] == before_state["seat"]
            cloned = await service.create(db_session, **args, clone_from_game_id=created.id, discipline="overwatch")
            assert (created.discipline, cloned.discipline) == ("lol", "lol")
            assert (
                await get_effective_division_grid(db_session, workspace.id, discipline=cloned.discipline)
            ).resolve_division(200).number == 9
            cloned_state = await service.self_state(db_session, custom_game_id=cloned.id, auth_user=host)
            assert cloned_state["seat"]["ranks"]["support"] == 200
            assert cloned_state["seat"]["divisions"]["support"] == before_state["seat"]["divisions"]["support"]
            await WorkspaceRepository().clear_default_grid_version(
                db_session, workspace_id=workspace.id, version_ids=[version.id]
            )
            await grid_cache.invalidate_workspace(workspace.id)
            # Without a LoL default the game falls back to League's ladder, never Overwatch's grid.
            lol_grid = await get_effective_division_grid(db_session, workspace.id, discipline="lol")
            assert lol_grid.tiers[0].slug == "challenger"
            assert (
                await db_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.CustomGame)
                    .where(models.CustomGame.workspace_id == workspace.id)
                )
                == 3
            )
            print(
                "PostgreSQL LoL mix create/self-state/clone after OW activation: support200 and Iron II badge unchanged; no default falls back to the LoL ladder"
            )
        finally:
            await grid_cache.invalidate_workspace(workspace_id)
            await db_session.rollback()
            assert (
                await db_session.scalar(
                    sa.select(sa.func.count()).select_from(models.Workspace).where(models.Workspace.id == workspace_id)
                )
                == 0
            )
            print("ROLLBACK confirmed: mix smoke workspace rows=0")
            await db_session.close()
            await engine.dispose()

    asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)
