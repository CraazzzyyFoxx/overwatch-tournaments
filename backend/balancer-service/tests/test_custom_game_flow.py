"""One pass through a whole mix, over in-memory stand-ins for the tables.

Every other test in ``test_custom_game.py`` pins one method against mocks. This
one runs the real host journey end to end -- create, fill the lineup, pin a
seat, balance, record the match, close -- against fakes that behave like the
normalized schema (a roster row owns one ``participation``, roles/co-hosts/team
names/role slots live in their own tables). It is the check that the use cases
compose: a state one method writes is the state the next one reads.
"""

from __future__ import annotations

import asyncio
import sys
from itertools import count
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

from shared.core.enums import MixParticipation, MixRoleSelectionMode  # noqa: E402
from shared.core.social import SocialProvider  # noqa: E402
from shared.domain.member_rank import ResolvedRank  # noqa: E402
from shared.domain.roster_shape import RosterShape  # noqa: E402
from shared.schemas.identity import PersonDisplayRead, PlayerIdentityRead  # noqa: E402
from shared.services import ontology  # noqa: E402
from shared.tests.test_team_format import OW_5V5, _module_ontology  # noqa: E402
from src.services.custom_game import CustomGameService  # noqa: E402
from src.services.workspace_roster import RosterMember  # noqa: E402
from tests.mix_ranker_fakes import in_memory_ranker  # noqa: E402

_MEMBERS = (7, 8, 9, 10, 11, 12, 13, 14, 15, 16)


class _Games:
    """``mix.custom_game`` as a dict, ids handed out on insert."""

    def __init__(self) -> None:
        self.rows: dict[int, Any] = {}
        self._ids = count(1)

    async def create(self, _session: Any, row: Any) -> Any:
        row.id = next(self._ids)
        self.rows[row.id] = row
        return row

    async def get(self, _session: Any, game_id: int, **_options: Any) -> Any:
        return self.rows.get(game_id)

    async def list_for_workspace(
        self,
        _session: Any,
        workspace_id: int,
        discipline: str | None = None,
        *,
        statuses: Any = None,
        search: str | None = None,
        before_id: int | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        rows = [
            row
            for row in sorted(self.rows.values(), key=lambda row: row.id, reverse=True)
            if row.workspace_id == workspace_id
            and (discipline is None or row.discipline == discipline)
            and (statuses is None or row.status in statuses)
            and (before_id is None or row.id < before_id)
            # Name only: the host-name half of the search is SQL against the roster, which has no fake here.
            and (not search or search.lower() in row.name.lower())
        ]
        return rows[:limit]

    async def delete(self, _session: Any, row: Any) -> None:
        self.rows.pop(row.id, None)


class _Roster:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self._ids = count(1)

    async def create_many(self, _session: Any, rows: list[Any]) -> list[Any]:
        for row in rows:
            row.id = next(self._ids)
            row.created_at = None
            self.rows.append(row)
        return rows

    async def list_for_game(self, _session: Any, game_id: int) -> list[Any]:
        return sorted(
            (row for row in self.rows if row.custom_game_id == game_id),
            key=lambda row: (row.sort_order, row.id),
        )

    async def delete(self, _session: Any, row: Any) -> None:
        self.rows.remove(row)


class _PlayerRoles:
    def __init__(self) -> None:
        self.by_player: dict[int, list[str]] = {}

    async def roles_for_players(self, _session: Any, player_ids: list[int]) -> dict[int, list[str]]:
        wanted = set(player_ids)
        return {pid: roles for pid, roles in self.by_player.items() if pid in wanted}

    async def replace_for_player(self, _session: Any, player_id: int, roles: Any, *, discipline: str) -> None:
        self.by_player[player_id] = list(roles)


class _TeamNames:
    def __init__(self) -> None:
        self.by_game: dict[int, dict[int, str]] = {}

    async def mapping_for_game(self, _session: Any, game_id: int) -> dict[int, str]:
        return dict(self.by_game.get(game_id, {}))

    async def set(self, _session: Any, game_id: int, index: int, name: str | None) -> None:
        names = self.by_game.setdefault(game_id, {})
        if name is None:
            names.pop(index, None)
        else:
            names[index] = name


class _Lobbies:
    """``mix.lobby`` as a dict keyed by (game id, lobby index)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, int], Any] = {}

    async def list_for_game(self, _session: Any, game_id: int) -> list[Any]:
        return [row for (gid, _index), row in sorted(self.rows.items()) if gid == game_id]

    async def get(self, _session: Any, game_id: int, lobby_index: int) -> Any:
        return self.rows.get((game_id, lobby_index))

    async def create(self, _session: Any, row: Any) -> Any:
        self.rows[(row.custom_game_id, row.lobby_index)] = row
        return row

    async def delete(self, _session: Any, row: Any) -> None:
        self.rows.pop((row.custom_game_id, row.lobby_index), None)


class _HostPrefs:
    """The host's solver and rating knobs."""

    def __init__(self) -> None:
        self.rows: dict[int, Any] = {}

    def save(self, user_id: int, **fields: Any) -> None:
        self.rows[user_id] = SimpleNamespace(
            user_id=user_id,
            config_json=fields.get("config_json", {}),
            points_per_win=fields.get("points_per_win"),
            rating_mode=fields.get("rating_mode", "points"),
            hero_ban_presets=fields.get("hero_ban_presets", {}),
            formation_defaults=fields.get("formation_defaults", {}),
        )

    async def get_by_user(self, _session: Any, user_id: int) -> Any:
        return self.rows.get(user_id)


class _CoHosts:
    def __init__(self) -> None:
        self.by_game: dict[int, list[int]] = {}

    async def user_ids_for_game(self, _session: Any, game_id: int) -> list[int]:
        return list(self.by_game.get(game_id, []))

    async def add(self, _session: Any, game_id: int, user_id: int) -> None:
        self.by_game.setdefault(game_id, []).append(user_id)

    async def remove(self, _session: Any, game_id: int, user_id: int) -> None:
        granted = self.by_game.get(game_id)
        if granted and user_id in granted:
            granted.remove(user_id)


class _RoundStore:
    """Matches as Start leaves them and rounds as Record leaves them, shaped like ``CustomGameRoundRepository`` rows."""

    def __init__(self) -> None:
        self.matches: list[Any] = []
        self.drafts: list[Any] = []
        self.rounds: list[Any] = []

    async def open(self, _session: Any, draft: Any) -> Any:
        self.matches.append(draft)
        return SimpleNamespace(id=500 + len(self.matches))

    async def record(self, _session: Any, draft: Any) -> Any:
        match = self.matches[draft.encounter_id - 501]
        self.drafts.append(draft)
        seated = [seat.workspace_member_id for team in match.seats for seat in team]
        self.rounds.append(
            SimpleNamespace(
                encounter_id=draft.encounter_id,
                custom_game_id=match.custom_game_id,
                encounter=SimpleNamespace(created_at=len(self.rounds) + 1),
                members=[SimpleNamespace(workspace_member_id=m, busy=False) for m in seated]
                + [SimpleNamespace(workspace_member_id=m, busy=True) for m in sorted(draft.busy - set(seated))],
            )
        )

    async def list_for_custom_game(self, _session: Any, game_id: int) -> list[Any]:
        return [row for row in reversed(self.rounds) if row.custom_game_id == game_id]


def _solver_result(lineup: list[Any]) -> dict[str, Any]:
    """A two-team, 1-1 split of the first four seated members, like the engine."""
    seats = [
        {
            "uuid": str(row.workspace_member_id),
            "name": f"P{row.workspace_member_id}",
            "assigned_rating": 2500,
            "role_preferences": ["tank"],
            "is_flex": False,
        }
        for row in lineup[:4]
    ]
    return {
        "variants": [
            {
                "teams": [
                    {"roster": {"tank": [seats[0]], "damage": [seats[1]]}},
                    {"roster": {"tank": [seats[2]], "damage": [seats[3]]}},
                ],
                "statistics": {},
                "benched_players": [{"uuid": str(row.workspace_member_id), "name": "spare"} for row in lineup[4:]],
            }
        ]
    }


class MixFlowTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.games = _Games()
        self.roster = _Roster()
        self.player_roles = _PlayerRoles()
        self.team_names = _TeamNames()
        self.host_prefs = _HostPrefs()
        self.co_hosts = _CoHosts()
        self.store = _RoundStore()
        self.lobbies = _Lobbies()

        self.ranks = MagicMock()
        self.ranks.resolve = AsyncMock(
            return_value={
                (member_id, role): ResolvedRank(2500, "workspace")
                for member_id in _MEMBERS
                for role in ("tank", "damage", "support")
            }
        )
        self.ranks.set_ranks = AsyncMock()
        self.ranks.list_layer = AsyncMock(return_value={})

        self.session = MagicMock()
        self.session.flush = AsyncMock()

        for target, value in (
            ("get_effective_division_grid", object()),
            ("custom_game_slot_shape", RosterShape(entries=(("tank", 1), ("damage", 1)))),
            ("copy_for_custom_game", None),
            ("custom_game_format", (OW_5V5, "custom_game")),
        ):
            patcher = patch(f"src.services.custom_game.{target}", new=AsyncMock(return_value=value))
            patcher.start()
            self.addCleanup(patcher.stop)
        ontology_patch = patch(
            "src.services.custom_game.CatalogRoleRepository.ontology",
            new=AsyncMock(return_value=_module_ontology("overwatch")),
        )
        ontology_patch.start()
        self.addCleanup(ontology_patch.stop)

        self.service = CustomGameService(
            games=self.games,
            workspaces=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(disciplines_enabled=["overwatch"]))),
            roster=self.roster,
            co_hosts=self.co_hosts,
            lobbies=self.lobbies,
            player_roles=self.player_roles,
            team_names=self.team_names,
            # The host's solver and points knobs, not the mix's format.
            host_prefs=self.host_prefs,
            mix_rounds=SimpleNamespace(list_for_custom_game=self.store.list_for_custom_game),
            open_match=self.store.open,
            write_result=self.store.record,
            players=SimpleNamespace(get_id_by_auth_user_id=AsyncMock(return_value=90)),
            ranks=self.ranks,
            scoring_rules=SimpleNamespace(create=AsyncMock(side_effect=lambda _s, row: setattr(row, "id", 5) or row)),
            load_roster=AsyncMock(
                side_effect=lambda _s, *, workspace_id, provider, member_ids: {
                    member_id: RosterMember(
                        member_id=member_id,
                        player_id=member_id * 10,
                        identity=PlayerIdentityRead.of(SocialProvider.BATTLENET, f"P{member_id}#1"),
                        display_name=f"P{member_id}",
                        display=PersonDisplayRead(name=f"P{member_id}"),
                        auth_user_id=member_id * 100,
                    )
                    for member_id in member_ids
                }
            ),
            load_hosts=AsyncMock(return_value={9: "Host"}),
            load_member_user_ids=AsyncMock(return_value=set()),
            run_balance=AsyncMock(),
            ranker=in_memory_ranker(),
            drafts=SimpleNamespace(
                active_lobby_pools=AsyncMock(return_value={}), active_for_custom_game=AsyncMock(return_value=[])
            ),
        )
        self.enterContext(
            patch.object(
                ontology._roles,
                "resolve",
                AsyncMock(side_effect=lambda _s, **kw: SimpleNamespace(code=kw["code"], parent_role_id=None)),
            )
        )

    async def test_a_whole_mix_from_create_to_close(self) -> None:
        self.host_prefs.save(9, points_per_win=25)

        game = await self.service.create(
            self.session,
            workspace_id=1,
            discipline="overwatch",
            host_user_id=9,
            name="Thursday scrim",
            actor_user_id=9,
            member_ids=list(_MEMBERS[:5]),
        )
        self.assertEqual(game.status, "draft")
        lineup = await self.roster.list_for_game(self.session, game.id)
        self.assertEqual([row.participation for row in lineup], [MixParticipation.POOL] * 5)

        # The host settles the lineup: one guaranteed seat, one spare benched,
        # and one player narrowed to a single role.
        await self.service.set_participation(
            self.session,
            workspace_id=1,
            custom_game_id=game.id,
            participation={
                7: MixParticipation.MUST_PLAY,
                11: MixParticipation.BENCHED,
            },
            actor_user_id=9,
        )
        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=game.id,
            workspace_member_id=8,
            patch={"roles": [{"dimension": "player_role", "role": "damage"}], "is_flex": False},
            actor_user_id=9,
        )
        narrowed = next(row for row in self.roster.rows if row.workspace_member_id == 8)
        self.assertEqual(narrowed.role_selection_mode, MixRoleSelectionMode.EXPLICIT)
        self.assertEqual(self.player_roles.by_player[narrowed.id], ["damage"])

        # A name for the first column -- the only setting that is the mix's own.
        await self.service.set_team_names(
            self.session,
            workspace_id=1,
            custom_game_id=game.id,
            team_names={"0": "Wolves"},
            actor_user_id=9,
        )

        seated = [
            row
            for row in await self.roster.list_for_game(self.session, game.id)
            if row.participation != MixParticipation.BENCHED
        ]
        self.service.run_balance = AsyncMock(return_value=_solver_result(seated))

        balanced = await self.service.balance(self.session, workspace_id=1, custom_game_id=game.id, actor_user_id=9)
        self.assertEqual(balanced.status, "balanced")
        # The solver only ever sees the seated lineup, and only the shape and the
        # knobs the host actually set reach it.
        payload, overrides, _progress, role_mask = self.service.run_balance.await_args.args
        self.assertEqual(sorted(payload["players"]), ["10", "7", "8", "9"])
        self.assertTrue(payload["players"]["7"]["identity"]["mustPlay"])
        self.assertEqual(list(payload["players"]["8"]["stats"]["classes"]), ["damage"])
        self.assertEqual(role_mask, {"tank": 1, "damage": 1})
        # The shape and the points are columns beside the override blob, so
        # neither leaks into the solver's config: this host set no solver knob.
        self.assertEqual(overrides, {})
        # The overflow the solver could not seat is benched, nothing else moves.
        by_member = {row.workspace_member_id: row for row in self.roster.rows}
        self.assertEqual(by_member[11].participation, MixParticipation.BENCHED)
        self.assertEqual(by_member[7].participation, MixParticipation.MUST_PLAY)

        await self.service.start_match(self.session, workspace_id=1, custom_game_id=game.id, actor_user_id=9)
        [match] = self.store.matches
        self.assertEqual(match.names, ("Wolves", "Team 2"))
        seats = [seat for team in match.seats for seat in team]
        self.assertEqual(sorted(seat.workspace_member_id for seat in seats), [7, 8, 9, 10])
        self.assertTrue(all(seat.display_name for seat in seats))
        # One captain per team.
        self.assertEqual([1, 1], [sum(seat.is_captain for seat in team) for team in match.seats])

        recorded = await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=game.id,
            winner=1,
            actor_user_id=9,
        )
        # Repeatable: the mix stays open, and the match is the only record.
        self.assertEqual(recorded.status, "balanced")
        self.assertEqual(len(self.store.drafts), 1)
        draft = self.store.drafts[0]
        self.assertEqual((draft.encounter_id, draft.names, draft.winner), (501, ("Wolves", "Team 2"), 1))
        # No bans: Start kept the lineup order, so lineup team 1 is the team in slot 1.
        self.assertEqual(draft.lineup_first_team, frozenset(seat.workspace_member_id for seat in match.seats[0]))
        # The pin was redeemed by the seat it guaranteed; the win moved ranks.
        self.assertEqual(by_member[7].participation, MixParticipation.POOL)
        self.assertEqual(len(self.ranks.set_ranks.await_args_list), 9)

        # The recorded map now feeds the rotation hint for the next one.
        rotation = await self.service.rotation(self.session, workspace_id=1, custom_game_id=game.id)
        owed = {rec.member_id for rec in rotation if rec.status.value == "must_play"}
        self.assertIn(11, owed)

        closed = await self.service.close(self.session, workspace_id=1, custom_game_id=game.id, actor_user_id=9)
        self.assertEqual(closed.status, "completed")
        # Closed is terminal: the next write is refused rather than silently applied.
        with self.assertRaises(Exception) as ctx:
            await self.service.balance(self.session, workspace_id=1, custom_game_id=game.id, actor_user_id=9)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 409)
