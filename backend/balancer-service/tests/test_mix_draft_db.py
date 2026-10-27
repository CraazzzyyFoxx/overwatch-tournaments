"""A mix lobby's captain draft against a real Postgres (spec §9): the session's owner, its seats and ranks, its
lifecycle and the lineup it leaves behind."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_BACKEND_ROOT), str(REPO_BACKEND_ROOT / "balancer-service")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from shared import models  # noqa: E402
from shared.core.enums import DraftPlayerStatus, DraftStatus, MixParticipation, MixStatus  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.roster_shape import FLEX_SLOT_CODE  # noqa: E402
from shared.domain.team_format import FormatDimension, FormatRule, TeamFormat  # noqa: E402
from shared.models.identity.oauth import OAuthConnection  # noqa: E402
from shared.models.platform.realtime import WorkspaceEvent  # noqa: E402
from shared.repository import CatalogRoleRepository  # noqa: E402
from shared.services import team_format  # noqa: E402
from shared.services.member_rank import member_rank_service  # noqa: E402
from shared.services.realtime.emit import _STAGED_KEY  # noqa: E402
from shared.tests.encounter_writer_case import EncounterWriterCase  # noqa: E402
from src.domain.draft.entities import PoolSeat  # noqa: E402
from src.domain.mix_lobbies import seated_member_ids  # noqa: E402
from src.domain.mix_ranker import HiddenRating, Ranker  # noqa: E402
from src.rpc import custom  # noqa: E402
from src.rpc import draft as draft_rpc  # noqa: E402
from src.services.account_links import required_link_providers  # noqa: E402
from src.services.custom_game import CustomGameService, custom_game_service  # noqa: E402
from src.services.draft import lifecycle, selection  # noqa: E402
from src.services.draft import realtime as draft_rt  # noqa: E402
from src.services.draft.board import board_service  # noqa: E402
from src.services.draft.feasibility import feasibility_service  # noqa: E402
from src.services.draft.rosters import draft_rosters  # noqa: E402
from src.services.mix_draft import mix_draft_service  # noqa: E402

#: A 2v2: one tank and one damage seat a team, so a draft is one round of two picks.
_TWO_SEATS = TeamFormat(
    discipline="overwatch",
    name="Two seats",
    starter_min=2,
    starter_max=2,
    dimensions=(FormatDimension("player_role", "enforced"),),
    rules=(FormatRule("player_role", "tank", 1, 1), FormatRule("player_role", "damage", 1, 1)),
)

#: The workspace canon a host-less mix reads (``MIX_ORDER``): m0 and m2 tank, m1 and m3 damage.
_RANKS = (("m0", "tank", 3000), ("m1", "damage", 2800), ("m2", "tank", 2500), ("m3", "damage", 2400))


class _Broker:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class _Quiet:
    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


class MixDraftTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.draft_ids: list[int] = []
        self.auth_user_ids: list[int] = []
        async with self.Session() as s:
            mix = await self.mix_encounter(s)
            self.cg_id = mix.custom_game_id
            await s.execute(sa.delete(models.Encounter).where(models.Encounter.id == mix.id))
            s.add(models.CustomGameLobby(custom_game_id=self.cg_id, lobby_index=0))
            await team_format._save(s, _TWO_SEATS, workspace_id=self.ids["ws"], custom_game_id=self.cg_id)
            for order, (member, role, rank) in enumerate(_RANKS):
                s.add(
                    models.CustomGamePlayer(
                        custom_game_id=self.cg_id, workspace_member_id=self.ids[member], sort_order=order
                    )
                )
                await member_rank_service.set_ranks(
                    s,
                    workspace_id=self.ids["ws"],
                    discipline="overwatch",
                    workspace_member_id=self.ids[member],
                    ranks={role: rank},
                )
            await s.commit()

    async def asyncTearDown(self) -> None:
        # Board events of a draft scope carry no workspace or tournament id, and the outbox keeps the mix's
        # pickup-mix events: the workspace cascade misses both.
        async with self.Session() as s:
            await s.execute(
                sa.delete(WorkspaceEvent).where(
                    WorkspaceEvent.topic.in_([f"draft:{draft_id}:board" for draft_id in self.draft_ids])
                )
            )
            await s.execute(
                sa.text("DELETE FROM event_outbox WHERE payload_json->>'custom_game_id' = :id"), {"id": str(self.cg_id)}
            )
            await s.execute(
                sa.text(
                    "DELETE FROM event_outbox WHERE routing_key = 'notification.created'"
                    " AND (payload_json->>'notification_id')::bigint IN"
                    " (SELECT id FROM notification WHERE source_workspace_id = :ws)"
                ),
                {"ws": self.ids["ws"]},
            )
            await s.execute(sa.text("DELETE FROM notification WHERE source_workspace_id = :ws"), {"ws": self.ids["ws"]})
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self.auth_user_ids)))
            await s.commit()
        await super().asyncTearDown()

    async def _session(self, s) -> models.DraftSession:
        game = await s.get_one(models.CustomGame, self.cg_id)
        draft = await lifecycle.lifecycle_service.create_session(
            s,
            custom_game_id=self.cg_id,
            lobby_index=0,
            workspace_id=self.ids["ws"],
            shape=await team_format.custom_game_slot_shape(s, game),
        )
        self.draft_ids.append(draft.id)
        return draft

    async def _seeded(self) -> int:
        """Lobby A seeded by hand: m1 captains team 1 (the weaker picks first), m0 team 2; m2 and m3 in the pool."""
        async with self.Session() as s:
            draft = await self._session(s)
            await lifecycle.lifecycle_service.seed(
                s,
                draft,
                seats=[
                    PoolSeat(None, draft_position=1, workspace_member_id=self.ids["m1"]),
                    PoolSeat(None, draft_position=2, workspace_member_id=self.ids["m0"]),
                    PoolSeat(None, workspace_member_id=self.ids["m2"]),
                    PoolSeat(None, workspace_member_id=self.ids["m3"]),
                ],
            )
            await s.commit()
            return draft.id

    async def _seat_ranks(self, draft_id: int) -> dict[int, int | None]:
        async with self.Session() as s:
            draft = await s.get_one(models.DraftSession, draft_id)
            seats = (
                (await s.scalars(sa.select(models.DraftPlayer).where(models.DraftPlayer.session_id == draft_id)))
                .unique()
                .all()
            )
            rosters = await draft_rosters.load(s, draft, seats)
        return {seat.workspace_member_id: rosters[seat.id].best_rank for seat in seats}

    async def test_a_lobby_draft_seats_members_and_reads_their_ranks_from_the_mix(self) -> None:
        draft_id = await self._seeded()
        async with self.Session() as s:
            draft = await s.get_one(models.DraftSession, draft_id)
            seats = (
                (await s.scalars(sa.select(models.DraftPlayer).where(models.DraftPlayer.session_id == draft_id)))
                .unique()
                .all()
            )
            rosters = await draft_rosters.load(s, draft, seats)
            read = await board_service.session_read(s, draft)

        self.assertEqual({None}, {seat.registration_id for seat in seats})
        self.assertEqual(
            {self.ids["m0"]: 3000, self.ids["m1"]: 2800, self.ids["m2"]: 2500, self.ids["m3"]: 2400},
            {seat.workspace_member_id: rosters[seat.id].best_rank for seat in seats},
        )
        self.assertEqual(
            ("overwatch", None, self.cg_id, 0),
            (read.discipline, read.tournament_id, read.custom_game_id, read.lobby_index),
        )

    async def _ranker_host(self, member: str = "m0", open_rank: int = 3000) -> tuple[int, int]:
        """The mix's host balances on the ranker, and ``member``'s hidden rating corrects their open ``open_rank``
        tank: the host and that member's effective tank rank."""
        hidden = HiddenRating(Ranker().initial(3500).mu, 3.0)
        async with self.Session() as s:
            host = models.AuthUser(
                email=f"mixdraft-host-{self.cg_id}@example.test",
                username=f"mixdraft-host-{self.cg_id}",
                is_active=True,
                is_verified=True,
            )
            s.add(host)
            await s.flush()
            self.auth_user_ids.append(host.id)
            (await s.get_one(models.CustomGame, self.cg_id)).host_user_id = host.id
            s.add(models.UserBalancerConfig(user_id=host.id, rating_mode="ranker"))
            tank = (await CatalogRoleRepository().rated_rows(s, discipline="overwatch", workspace_id=None))["tank"]
            s.add(
                models.MemberHiddenRating(
                    workspace_id=self.ids["ws"],
                    workspace_member_id=self.ids[member],
                    catalog_role=tank,
                    dimension_id=tank.dimension_id,
                    mu=hidden.mu,
                    sigma=hidden.sigma,
                )
            )
            await s.commit()
            return host.id, round(Ranker().effective(open_rank, hidden))

    async def test_a_ranker_host_drafts_on_the_effective_rating_the_balance_uses(self) -> None:
        """U3: a ranker-mode host's draft shows the open rank corrected by the hidden one, like the mix balance."""
        _host, corrected = await self._ranker_host()

        ranks = await self._seat_ranks(await self._seeded())

        self.assertNotEqual(3000, corrected)
        self.assertEqual(
            {self.ids["m0"]: corrected, self.ids["m1"]: 2800, self.ids["m2"]: 2500, self.ids["m3"]: 2400}, ranks
        )

    async def test_a_ranker_hosts_drafted_lineup_keeps_the_open_rank_a_match_moves(self) -> None:
        """Like a balanced lineup: the seat plays on its effective rank, and a recorded match moves the open one."""
        host, corrected = await self._ranker_host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)
        await self._autopick(draft_id)
        async with self.Session() as s:
            lobby = await s.get_one(models.CustomGameLobby, (self.cg_id, 0))
        m0 = lobby.balance_result_json["players"][str(self.ids["m0"])]

        self.assertEqual((corrected, 3000), (m0["ratings"]["tank"], m0["open_ratings"]["tank"]))

    async def test_an_all_flex_lineup_keeps_the_ranks_its_picks_froze(self) -> None:
        """A host transfer before the last pick re-ranks the pool, never a pick made: an all-flex seat plays on the
        rank its pick froze, as a role seat does (spec §9.4)."""
        async with self.Session() as s:
            await team_format._save(
                s,
                TeamFormat("overwatch", "Open two", 2, 2, dimensions=(FormatDimension("player_role", "off"),)),
                workspace_id=self.ids["ws"],
                custom_game_id=self.cg_id,
            )
            await s.commit()
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        async with self.Session() as s:
            draft = await s.get_one(models.DraftSession, draft_id)
            pick = await s.get_one(models.DraftPick, draft.current_pick_id)
            await selection.selection_service.select(
                s,
                draft,
                pick,
                player_id=await self._seat(s, draft_id, "m2"),
                expected_version=pick.version,
                target_role=None,
                actor_user_id=None,
                is_admin=True,
            )
            await s.commit()
        _new_host, corrected = await self._ranker_host("m2", 2500)  # the mix changes hands mid-draft
        await self._autopick(draft_id)
        async with self.Session() as s:
            lobby = await s.get_one(models.CustomGameLobby, (self.cg_id, 0))
            frozen = dict(
                (
                    await s.execute(
                        sa.select(models.DraftPlayer.workspace_member_id, models.DraftPick.target_rank_value)
                        .join(models.DraftPick, models.DraftPick.picked_player_id == models.DraftPlayer.id)
                        .where(models.DraftPick.session_id == draft_id)
                    )
                ).all()
            )
        players = lobby.balance_result_json["players"]

        self.assertEqual("completed", await self._status(draft_id))
        self.assertNotEqual(2500, corrected)
        self.assertEqual(2500, frozen[self.ids["m2"]])
        self.assertEqual(frozen, {member: players[str(member)]["ratings"][FLEX_SLOT_CODE] for member in frozen})

    async def test_a_lobby_runs_one_active_draft_at_a_time(self) -> None:
        await self._seeded()
        async with self.Session() as s:
            with self.assertRaises(IntegrityError):
                await self._session(s)

    async def test_a_draft_session_has_exactly_one_owner(self) -> None:
        async with self.Session() as s:
            s.add(
                models.DraftSession(
                    tournament_id=self.ids["t"],
                    custom_game_id=self.cg_id,
                    lobby_index=0,
                    workspace_id=self.ids["ws"],
                    discipline="overwatch",
                )
            )
            with self.assertRaises(IntegrityError):
                await s.flush()

    async def test_a_mix_seat_is_a_member_never_a_registration(self) -> None:
        """R-ID: the CHECK accepts either id; the seed refuses a mix seat that names a registration instead."""
        async with self.Session() as s:
            draft = await self._session(s)
            with self.assertRaises(ApiHTTPException) as caught:
                await lifecycle.lifecycle_service.seed(
                    s,
                    draft,
                    seats=[
                        PoolSeat(None, draft_position=1, workspace_member_id=self.ids["m1"]),
                        PoolSeat(424242),
                    ],
                )

        self.assertEqual(
            (422, "seat_identity_invalid"), (caught.exception.status_code, caught.exception.detail[0]["code"])
        )

    async def test_a_tournament_seat_is_a_registration_never_a_bare_member(self) -> None:
        """R-ID: the seed refuses a tournament seat that names only a workspace member."""
        async with self.Session() as s:
            game = await s.get_one(models.CustomGame, self.cg_id)
            draft = await lifecycle.lifecycle_service.create_session(
                s,
                tournament_id=self.ids["t"],
                workspace_id=self.ids["ws"],
                shape=await team_format.custom_game_slot_shape(s, game),
            )
            self.draft_ids.append(draft.id)
            with self.assertRaises(ApiHTTPException) as caught:
                await lifecycle.lifecycle_service.seed(
                    s, draft, seats=[PoolSeat(None, draft_position=1, workspace_member_id=self.ids["m0"])]
                )

        self.assertEqual("overwatch", draft.discipline)
        self.assertEqual(
            (422, "seat_identity_invalid"), (caught.exception.status_code, caught.exception.detail[0]["code"])
        )

    async def test_a_mix_draft_starts_without_any_tournament_phase(self) -> None:
        draft_id = await self._seeded()
        async with self.Session() as s:
            draft = await s.get_one(models.DraftSession, draft_id)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            on_clock = await s.get_one(models.DraftPick, draft.current_pick_id)

        self.assertEqual(DraftStatus.LIVE.value, draft.status)
        self.assertEqual(1, on_clock.overall_no)

    async def test_deleting_the_workspace_takes_a_mix_draft_with_it(self) -> None:
        """The seat's member FK is the anchor rule (NO ACTION, deferred): the workspace cascade removes member, session
        and seats in one statement, and by commit nothing is left pointing anywhere. A SET NULL there would strip a mix
        seat of its only identity and trip ``ck_draft_player_identity`` instead."""
        draft_id = await self._seeded()
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.ids["ws"]))
            await s.commit()
            sessions = await s.scalar(
                sa.select(sa.func.count()).select_from(models.DraftSession).where(models.DraftSession.id == draft_id)
            )
            seats = await s.scalar(
                sa.select(sa.func.count())
                .select_from(models.DraftPlayer)
                .where(models.DraftPlayer.session_id == draft_id)
            )

        self.assertEqual((0, 0), (sessions, seats))

    async def _host(self) -> tuple[int, int]:
        """The mix's host and an account that is nobody here: two real ``auth.user`` rows."""
        async with self.Session() as s:
            host = models.AuthUser(username=f"host-{self.cg_id}", email=f"host-{self.cg_id}@example.test")
            stranger = models.AuthUser(username=f"stranger-{self.cg_id}", email=f"stranger-{self.cg_id}@example.test")
            s.add_all([host, stranger])
            await s.flush()
            self.auth_user_ids.extend((host.id, stranger.id))
            (await s.get_one(models.CustomGame, self.cg_id)).host_user_id = host.id
            await s.commit()
            return host.id, stranger.id

    def _rpc(self) -> _Broker:
        factory = draft_rpc._SF
        draft_rpc._SF = self.Session
        self.addCleanup(setattr, draft_rpc, "_SF", factory)
        broker = _Broker()
        draft_rpc.register(broker, _Quiet())
        return broker

    async def test_the_mix_host_runs_the_draft_and_a_stranger_cannot(self) -> None:
        host, stranger = await self._host()
        draft_id = await self._seeded()
        start = self._rpc().handlers["rpc.balancer.draft.start"]

        refused = await start({"id": draft_id, "identity": {"user_id": stranger, "is_active": True}}, None)
        started = await start({"id": draft_id, "identity": {"user_id": host, "is_active": True}}, None)

        self.assertEqual("forbidden", refused["error"]["code"])
        self.assertTrue(started["ok"], started)
        self.assertEqual("live", started["data"]["status"])

    async def test_a_mix_role_edit_passes_the_hosts_gate_then_stops_at_the_tournament_guard(self) -> None:
        """R-B1: the role edit authorizes on the session's owner first, so a stranger is refused before the guard."""
        host, stranger = await self._host()
        draft_id = await self._seeded()
        async with self.Session() as s:
            seat_id, version = (
                await s.execute(
                    sa.select(models.DraftPlayer.id, models.DraftPlayer.version).where(
                        models.DraftPlayer.session_id == draft_id,
                        models.DraftPlayer.workspace_member_id == self.ids["m3"],
                    )
                )
            ).one()
        edit = self._rpc().handlers["rpc.balancer.draft.player_role_edit"]
        request = {
            "id": seat_id,
            "session_id": draft_id,
            "payload": {
                "expected_version": version,
                "role": {"dimension": "player_role", "role": "tank"},
                "rank_value": 2500,
                "reason": "Emergency tank",
                "preview_only": True,
            },
        }

        refused = await edit({**request, "identity": {"user_id": stranger, "is_active": True}}, None)
        guarded = await edit({**request, "identity": {"user_id": host, "is_active": True}}, None)

        self.assertEqual("forbidden", refused["error"]["code"])
        self.assertEqual(
            ("unprocessable", "role_edit_tournament_only"),
            (guarded["error"]["code"], guarded["error"]["details"]["fields"][0]["code"]),
        )

    async def test_a_co_host_removed_while_their_draft_write_waits_is_refused(self) -> None:
        """Authorized under the mix lock, against the owner as it is once the lock is held (as ``_writable`` does): a
        co-host whose grant is revoked while their pause and their pick for a team wait on the mix row is refused."""
        host, co_host = await self._host()
        async with self.Session() as s:
            s.add(models.CustomGameCoHost(custom_game_id=self.cg_id, user_id=co_host))
            await s.commit()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        async with self.Session() as s:
            pick = await s.get_one(models.DraftPick, (await s.get_one(models.DraftSession, draft_id)).current_pick_id)
            m2_seat = await self._seat(s, draft_id, "m2")
        handlers = self._rpc().handlers
        identity = {"user_id": co_host, "is_active": True}
        async with self.Session() as holder:
            await CustomGameService().remove_co_host(holder, **self._as_host(host, co_host_user_id=co_host))
            waiting = [
                asyncio.create_task(handlers["rpc.balancer.draft.pause"]({"id": draft_id, "identity": identity}, None)),
                asyncio.create_task(
                    handlers["rpc.balancer.draft.pick_select"](
                        {
                            "id": pick.id,
                            "identity": identity,
                            "payload": {"player_id": m2_seat, "expected_version": pick.version},
                        },
                        None,
                    )
                ),
            ]
            await asyncio.sleep(0.5)
            await holder.commit()
        replies = await asyncio.wait_for(asyncio.gather(*waiting), 10)

        self.assertEqual(["forbidden", "forbidden"], [reply.get("error", {}).get("code") for reply in replies], replies)
        self.assertEqual("live", await self._status(draft_id))

    async def test_board_events_land_on_the_sessions_own_topic(self) -> None:
        draft_id = await self._seeded()
        async with self.Session() as s:
            await lifecycle.lifecycle_service.transition(
                s,
                draft_id,
                lifecycle.lifecycle_service.start,
                event_type="draft.pick_started",
                audit_action="started",
                actor_auth_user_id=None,
            )
            await s.commit()
            topics = set(
                (
                    await s.scalars(
                        sa.select(WorkspaceEvent.topic).where(
                            WorkspaceEvent.payload["session_id"].astext == str(draft_id)
                        )
                    )
                ).all()
            )
            newest = await draft_rt.last_event_id(s, draft_id)

        self.assertEqual({f"draft:{draft_id}:board"}, topics)
        self.assertIsNotNone(newest)

    async def _member(self, name: str, role: str, rank: int, *, away: bool = False, sort_order: int = 99) -> int:
        """One more player of this mix: a workspace member with a canon rank and a pool row."""
        async with self.Session() as s:
            user = models.User(name=f"{name}-{self.cg_id}")
            s.add(user)
            await s.flush()
            self.users.append(user.id)
            member = models.WorkspaceMember(workspace_id=self.ids["ws"], player_id=user.id)
            s.add(member)
            await s.flush()
            s.add(
                models.CustomGamePlayer(
                    custom_game_id=self.cg_id, workspace_member_id=member.id, sort_order=sort_order, away=away
                )
            )
            await member_rank_service.set_ranks(
                s,
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                workspace_member_id=member.id,
                ranks={role: rank},
            )
            await s.commit()
            return member.id

    def _as_host(self, host: int, **extra: object) -> dict[str, object]:
        return {"workspace_id": self.ids["ws"], "custom_game_id": self.cg_id, "actor_user_id": host, **extra}

    async def _seed_lobby(self, host: int, lobby_index: int = 0) -> int:
        async with self.Session() as s:
            await mix_draft_service.seed_lobby(s, **self._as_host(host, lobby_index=lobby_index))
            await s.commit()
            pools = await CustomGameService().draft_lobbies(s, self.cg_id)
        self.draft_ids.append(pools[lobby_index][0])
        return pools[lobby_index][0]

    async def _teams(self, draft_id: int) -> list[models.DraftTeam]:
        async with self.Session() as s:
            return list(
                (
                    await s.scalars(
                        sa.select(models.DraftTeam)
                        .where(models.DraftTeam.session_id == draft_id)
                        .order_by(models.DraftTeam.draft_position)
                    )
                ).all()
            )

    async def _seat(self, s, draft_id: int, member: str) -> int:
        return await s.scalar(
            sa.select(models.DraftPlayer.id).where(
                models.DraftPlayer.session_id == draft_id, models.DraftPlayer.workspace_member_id == self.ids[member]
            )
        )

    async def _start(self, draft_id: int, host: int) -> None:
        async with self.Session() as s:
            await lifecycle.lifecycle_service.transition(
                s,
                draft_id,
                lifecycle.lifecycle_service.start,
                event_type="draft.pick_started",
                audit_action="started",
                actor_auth_user_id=host,
            )
            await s.commit()

    async def _autopick(self, draft_id: int) -> None:
        """The clock runs out on the pick on the clock: the engine's own expiry path."""
        async with self.Session() as s:
            draft = await s.get_one(models.DraftSession, draft_id)
            pick = await s.get_one(models.DraftPick, draft.current_pick_id)
            await selection.selection_service.autopick(
                s, draft, pick, expected_version=pick.version, actor_auth_user_id=None, reason="expiry"
            )
            await s.commit()

    async def _status(self, draft_id: int) -> str:
        async with self.Session() as s:
            return (await s.get_one(models.DraftSession, draft_id)).status

    async def _away(self, host: int, member_id: int, away: bool) -> None:
        """The host marks a player away or back; a flag that flips reaches the mix's draft (as the RPC wires it)."""
        async with self.Session() as s:
            await CustomGameService().update_player(
                s,
                **self._as_host(host, workspace_member_id=member_id, patch={"away": away}),
                on_away=mix_draft_service.on_away,
            )
            await s.commit()

    async def _self_away(self, account: models.AuthUser, away: bool) -> None:
        """The player steps away or back themselves (as the RPC wires it)."""
        async with self.Session() as s:
            await custom_game_service.self_set_away(
                s, custom_game_id=self.cg_id, auth_user=account, away=away, on_away=mix_draft_service.on_away
            )
            await s.commit()

    async def _account(self, user_id: int) -> models.AuthUser:
        """A login for this mix's player ``user_id``, linked to every provider a self-service write asks for."""
        async with self.Session() as s:
            account = models.AuthUser(username=f"acct-{user_id}", email=f"acct-{user_id}@example.test")
            s.add(account)
            await s.flush()
            self.auth_user_ids.append(account.id)
            for provider in required_link_providers("overwatch"):
                s.add(
                    OAuthConnection(
                        auth_user_id=account.id,
                        provider=provider,
                        provider_user_id=f"{provider}-{user_id}",
                        username=f"{provider}-{user_id}",
                    )
                )
            (await s.get_one(models.User, user_id)).auth_user_id = account.id
            await s.commit()
            return account

    async def _overview_signals(self) -> int:
        """``pickup_mix_changed`` facts this mix staged for a draft: the overview's (and the bot's) re-read."""
        async with self.Session() as s:
            return await s.scalar(
                sa.text(
                    "SELECT count(*) FROM event_outbox "
                    "WHERE payload_json->>'custom_game_id' = :id AND payload_json->>'change' = 'draft'"
                ),
                {"id": str(self.cg_id)},
            )

    async def test_draft_seeds_the_seated_set_with_the_two_strongest_as_captains(self) -> None:
        host, _ = await self._host()
        await self._member("m4", "tank", 3500, away=True)  # strongest, but away: in no seated set (§7.4)
        draft_id = await self._seed_lobby(host)
        async with self.Session() as s:
            pools = await CustomGameService().draft_lobbies(s, self.cg_id)
            session_id, status, pool = pools[0]
            lobby = await s.get_one(models.CustomGameLobby, (self.cg_id, 0))

        self.assertEqual((draft_id, "ready"), (session_id, status))
        self.assertEqual({self.ids[f"m{i}"] for i in range(4)}, set(pool))
        # The weaker of the two strongest (m1, 2800) picks first; m0 (3000) second.
        self.assertEqual(
            [self.ids["m1"], self.ids["m0"]],
            [team.captain_workspace_member_id for team in await self._teams(draft_id)],
        )
        self.assertIsNone(lobby.balance_result_json)

    async def test_an_idle_draft_still_ends_in_the_lobbys_lineup(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)
        before = await self._overview_signals()
        await self._autopick(draft_id)

        async with self.Session() as s:
            lobby = await s.get_one(models.CustomGameLobby, (self.cg_id, 0))
            game = await s.get_one(models.CustomGame, self.cg_id)
        document = lobby.balance_result_json
        [variant] = document["variants"]
        m0, m1, m2, m3 = (str(self.ids[f"m{i}"]) for i in range(4))

        self.assertEqual("completed", await self._status(draft_id))
        self.assertEqual("draft", document["source"])
        self.assertEqual(MixStatus.BALANCED, game.status)
        self.assertEqual(
            [({"damage": [m1], "tank": [m2]}, int(m1)), ({"tank": [m0], "damage": [m3]}, int(m0))],
            [(team["roster"], team["captain_member_id"]) for team in variant["teams"]],
        )
        self.assertEqual(100, variant["statistics"]["max_total_rating_gap"])
        self.assertEqual(0, variant["statistics"]["off_role_count"])
        # The clock's last pick tells the overview the lobby moved Draft -> Ready.
        self.assertEqual(before + 1, await self._overview_signals())

    async def test_a_finished_mix_draft_is_neither_paused_nor_rolled_back(self) -> None:
        """R-S2: the finished draft is the lobby's lineup, maybe already on the floor; the host re-forms instead. A
        pause would reopen it too (completed -> paused, then rollback and resume)."""
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)
        await self._autopick(draft_id)
        refusals = []
        for move, event_type in (
            (lifecycle.lifecycle_service.pause, "draft.paused"),
            (lifecycle.lifecycle_service.rollback, "draft.rollback"),
        ):
            async with self.Session() as s:
                with self.assertRaises(ApiHTTPException) as caught:
                    await lifecycle.lifecycle_service.transition(
                        s, draft_id, move, event_type=event_type, audit_action="moved", actor_auth_user_id=host
                    )
            refusals.append((caught.exception.status_code, caught.exception.detail[0]["code"]))

        self.assertEqual([(409, "mix_draft_completed")] * 2, refusals)
        self.assertEqual("completed", await self._status(draft_id))

    async def test_a_host_rolls_a_pick_back_and_the_player_is_draftable_again(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)
        async with self.Session() as s:
            await lifecycle.lifecycle_service.transition(
                s,
                draft_id,
                lifecycle.lifecycle_service.rollback,
                event_type="draft.rollback",
                audit_action="rollback",
                actor_auth_user_id=host,
            )
            await s.commit()
            seat = await s.get_one(models.DraftPlayer, await self._seat(s, draft_id, "m2"))

        self.assertEqual("paused", await self._status(draft_id))
        self.assertEqual(DraftPlayerStatus.AVAILABLE.value, seat.status)

    async def test_replacing_a_captain_before_the_start_reseeds_the_weaker_first(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        [_, second] = await self._teams(draft_id)
        async with self.Session() as s:
            m2_seat = await self._seat(s, draft_id, "m2")
            await mix_draft_service.replace_captain(
                s, **self._as_host(host, lobby_index=0, team_id=second.id, player_id=m2_seat)
            )
            await s.commit()

        # m0's team now has m2 (2500): weaker than m1 (2800), so m2 picks first.
        self.assertEqual(
            [self.ids["m2"], self.ids["m1"]],
            [team.captain_workspace_member_id for team in await self._teams(draft_id)],
        )

    async def test_replacing_a_captain_mid_draft_hands_the_team_to_a_teammate(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)  # team 1 (m1) takes m2
        [first, _] = await self._teams(draft_id)
        async with self.Session() as s:
            m2_seat = await self._seat(s, draft_id, "m2")
            m1_seat = await self._seat(s, draft_id, "m1")
            await mix_draft_service.replace_captain(
                s, **self._as_host(host, lobby_index=0, team_id=first.id, player_id=m2_seat)
            )
            await s.commit()
            resolved = await s.scalar(
                sa.select(sa.func.count())
                .select_from(models.DraftPick)
                .where(models.DraftPick.session_id == draft_id, models.DraftPick.picked_player_id.is_not(None))
            )
        async with self.Session() as s:
            board = await board_service.build_board(s, await s.get_one(models.DraftSession, draft_id))
            m2_player = (await s.get_one(models.WorkspaceMember, self.ids["m2"])).player_id
        crowns = {player.id: player.is_captain for player in board.players}
        members = {player.id: player.workspace_member_id for player in board.players}

        self.assertEqual(self.ids["m2"], (await self._teams(draft_id))[0].captain_workspace_member_id)
        self.assertEqual(1, resolved)  # the pick made stands
        # U2: the crown the board shows, and the team's captain identity, follow the team's current captain.
        self.assertEqual((True, False), (crowns[m2_seat], crowns[m1_seat]))
        self.assertEqual(m2_player, board.teams[0].captain_user_id)
        # A mix seat names its workspace member, so the room can tie it to the lineup seat.
        self.assertEqual((self.ids["m2"], self.ids["m1"]), (members[m2_seat], members[m1_seat]))

    async def test_replacing_a_captain_reauthorizes_the_draft_chat(self) -> None:
        """The gateway re-checks a chat topic's live subscribers only on ``chat.visibility_changed``: the replace
        announces it at the room's current setting, so a former captain stops receiving a chat closed to spectators.
        Chat events are never stored, so the transaction's staged realtime events are the record."""
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)  # team 1 (m1) takes m2
        [first, _] = await self._teams(draft_id)
        async with self.Session() as s:
            await mix_draft_service.replace_captain(
                s,
                **self._as_host(host, lobby_index=0, team_id=first.id, player_id=await self._seat(s, draft_id, "m2")),
            )
            staged = [
                (scope.domain_topic(data.domain), data.event_type, dict(data.payload))
                for scope, data, _actor in s.info[_STAGED_KEY].domain
            ]
            await s.commit()

        self.assertIn((f"draft:{draft_id}:chat", "chat.visibility_changed", {"spectators_can_read": True}), staged)

    async def _draft_dms(self) -> list[tuple[int, str, bool]]:
        """``mix.draft_started`` rows of this workspace: ``(recipient, dedupe key, its delivery event is in the
        outbox)``."""
        async with self.Session() as s:
            rows = await s.execute(
                sa.text(
                    "SELECT n.recipient_auth_user_id, n.dedupe_key, EXISTS (SELECT 1 FROM event_outbox o"
                    " WHERE o.routing_key = 'notification.created'"
                    " AND (o.payload_json->>'notification_id')::bigint = n.id)"
                    " FROM notification n WHERE n.kind = 'mix.draft_started' AND n.source_workspace_id = :ws"
                ),
                {"ws": self.ids["ws"]},
            )
        return sorted(tuple(row) for row in rows)

    async def _move(self, draft_id: int, host: int, move, event_type: str) -> None:
        async with self.Session() as s:
            await lifecycle.lifecycle_service.transition(
                s, draft_id, move, event_type=event_type, audit_action="moved", actor_auth_user_id=host
            )
            await s.commit()

    async def test_start_draft_dms_both_captains_and_a_live_replacement_but_not_a_seed_or_a_resume(self) -> None:
        """R3-3: one DM per captain when the clock starts, one for a captain handed the running draft, none at the
        seed (captains are only proposed), per pick or on resume."""
        host, _ = await self._host()
        accounts = {
            member: (await self._account(self.users[index])).id for index, member in enumerate(("m0", "m1", "m2"))
        }
        m0, m1, m2 = (self.ids[member] for member in ("m0", "m1", "m2"))
        draft_id = await self._seed_lobby(host)
        self.assertEqual([], await self._draft_dms())

        await self._start(draft_id, host)
        started = sorted(
            [(accounts["m1"], f"mix_draft:{draft_id}:{m1}", True), (accounts["m0"], f"mix_draft:{draft_id}:{m0}", True)]
        )
        self.assertEqual(started, await self._draft_dms())

        await self._autopick(draft_id)  # team 1 (m1) takes m2
        [first, _] = await self._teams(draft_id)
        async with self.Session() as s:
            m2_seat = await self._seat(s, draft_id, "m2")
            await mix_draft_service.replace_captain(
                s, **self._as_host(host, lobby_index=0, team_id=first.id, player_id=m2_seat)
            )
            await s.commit()
        await self._move(draft_id, host, lifecycle.lifecycle_service.pause, "draft.paused")
        await self._move(draft_id, host, lifecycle.lifecycle_service.resume, "draft.resumed")

        self.assertEqual(
            sorted([*started, (accounts["m2"], f"mix_draft:{draft_id}:{m2}", True)]), await self._draft_dms()
        )

    async def test_a_captain_crowned_while_the_draft_is_paused_gets_the_draft_dm(self) -> None:
        """R3-3's live draft is a started one, paused included: the resume sends nothing, so the crowning is the new
        captain's one DM. The seeded captains have no site account here, so the start itself DMs nobody."""
        host, _ = await self._host()
        m2_account = (await self._account(self.users[2])).id
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)  # team 1 (m1) takes m2
        await self._move(draft_id, host, lifecycle.lifecycle_service.pause, "draft.paused")
        self.assertEqual(DraftStatus.PAUSED.value, await self._status(draft_id))
        [first, _] = await self._teams(draft_id)
        async with self.Session() as s:
            m2_seat = await self._seat(s, draft_id, "m2")
            await mix_draft_service.replace_captain(
                s, **self._as_host(host, lobby_index=0, team_id=first.id, player_id=m2_seat)
            )
            await s.commit()

        self.assertEqual([(m2_account, f"mix_draft:{draft_id}:{self.ids['m2']}", True)], await self._draft_dms())

    async def test_rolling_back_the_pick_that_seated_a_replacement_captain_is_refused(self) -> None:
        """The rollback would free the team's captain into the pool: refused until the host crowns a player who stays
        on the team. A rollback that frees no captain still runs
        (``test_a_host_rolls_a_pick_back_and_the_player_is_draftable_again``)."""
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)  # team 1 (m1) takes m2
        [first, _] = await self._teams(draft_id)
        async with self.Session() as s:
            await mix_draft_service.replace_captain(
                s,
                **self._as_host(host, lobby_index=0, team_id=first.id, player_id=await self._seat(s, draft_id, "m2")),
            )
            await s.commit()
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await lifecycle.lifecycle_service.transition(
                    s,
                    draft_id,
                    lifecycle.lifecycle_service.rollback,
                    event_type="draft.rollback",
                    audit_action="rollback",
                    actor_auth_user_id=host,
                )
        async with self.Session() as s:
            seat = await s.get_one(models.DraftPlayer, await self._seat(s, draft_id, "m2"))

        self.assertEqual(
            (409, "rollback_frees_captain"), (caught.exception.status_code, caught.exception.detail[0]["code"])
        )
        self.assertEqual("live", await self._status(draft_id))
        self.assertEqual((DraftPlayerStatus.PICKED.value, first.id), (seat.status, seat.drafted_by_team_id))

    async def test_a_picked_player_going_away_pauses_the_draft(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)  # m2 is picked
        await self._away(host, self.ids["m2"], True)

        self.assertEqual("paused", await self._status(draft_id))

    async def test_an_unpicked_player_going_away_leaves_the_pool_and_a_short_draft_pauses(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._away(host, self.ids["m3"], True)
        async with self.Session() as s:
            draft = await s.get_one(models.DraftSession, draft_id)
            report = await feasibility_service.analyze_session(s, draft)
            pool = (await CustomGameService().draft_lobbies(s, self.cg_id))[0][2]

        # m3 was the only damage player left for team 2: the draft cannot be finished without a waiting player.
        self.assertFalse(report.is_feasible)
        self.assertEqual("paused", await self._status(draft_id))
        self.assertNotIn(self.ids["m3"], pool)

    async def test_a_ready_draft_repairs_an_away_player_and_every_read_names_the_lobby(self) -> None:
        """R-S1: ready -> m3 steps away (leaves the pool, the draft cannot start) -> m4 comes back themselves and the
        host adds them -> start. Meanwhile the busy, detail and self reads agree on who the draft holds."""
        host, _ = await self._host()
        waiting = await self._member("m4", "damage", 2300, away=True)
        account = await self._account(self.users[-1])
        draft_id = await self._seed_lobby(host)

        await self._away(host, self.ids["m3"], True)
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException):
                await lifecycle.lifecycle_service.start(s, await s.get_one(models.DraftSession, draft_id))
        await self._self_away(account, False)
        async with self.Session() as s:
            await mix_draft_service.add_player(s, **self._as_host(host, lobby_index=0, workspace_member_id=waiting))
            await s.commit()
        await self._start(draft_id, host)

        async with self.Session() as s:
            game = await s.get_one(models.CustomGame, self.cg_id)
            read = await custom._with_roster(s, game)
            seat = (await custom_game_service.self_state(s, custom_game_id=self.cg_id, auth_user=account))["seat"]
        current = {row["workspace_member_id"]: row["current_lobby"] for row in read["players"]}

        self.assertEqual("live", await self._status(draft_id))
        self.assertEqual(
            {self.ids["m0"]: 0, self.ids["m1"]: 0, self.ids["m2"]: 0, self.ids["m3"]: None, waiting: 0}, current
        )
        self.assertEqual((0, False), (seat["current_lobby"], seat["away"]))

    async def test_stepping_away_takes_the_mix_lock_before_the_players_own_row(self) -> None:
        """Owner first, as every host write: a player stepping away waits on the mix row before touching their own,
        so a host write that holds the mix and edits that row never deadlocks with them."""
        host, _ = await self._host()
        account = await self._account(self.users[3])  # m3
        async with self.Session() as holder:
            await CustomGameService()._writable(holder, **self._as_host(host))
            stepping = asyncio.create_task(self._self_away(account, True))
            await asyncio.sleep(0.5)
            waiting = not stepping.done()
            # NOWAIT: raises if the player's write already holds the row.
            row = await holder.scalar(
                sa.select(models.CustomGamePlayer)
                .where(
                    models.CustomGamePlayer.custom_game_id == self.cg_id,
                    models.CustomGamePlayer.workspace_member_id == self.ids["m3"],
                )
                .with_for_update(nowait=True)
            )
            row.participation = MixParticipation.MUST_PLAY
            await holder.commit()
        await asyncio.wait_for(stepping, 10)
        async with self.Session() as s:
            row = await s.scalar(
                sa.select(models.CustomGamePlayer).where(
                    models.CustomGamePlayer.custom_game_id == self.cg_id,
                    models.CustomGamePlayer.workspace_member_id == self.ids["m3"],
                )
            )

        self.assertTrue(waiting)
        self.assertEqual((MixParticipation.MUST_PLAY, True), (row.participation, row.away))

    async def test_an_away_pause_also_refreshes_the_boards_seats(self) -> None:
        """R-S1: ``draft.paused`` is a status change to the board; the seat that left the pool needs the re-read."""
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._away(host, self.ids["m3"], True)
        async with self.Session() as s:
            newest = (
                await s.scalars(
                    sa.select(WorkspaceEvent.event_type)
                    .where(WorkspaceEvent.topic == f"draft:{draft_id}:board")
                    .order_by(WorkspaceEvent.id.desc())
                    .limit(2)
                )
            ).all()

        self.assertEqual(["draft.session_updated", "draft.paused"], list(newest))

    async def test_a_repeated_away_flag_does_not_pause_a_resumed_draft(self) -> None:
        """Only a flag that flips is news: the host resumed past m2's absence, and saying it again changes nothing."""
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        await self._start(draft_id, host)
        await self._autopick(draft_id)  # m2 is picked
        await self._away(host, self.ids["m2"], True)
        async with self.Session() as s:
            await lifecycle.lifecycle_service.transition(
                s,
                draft_id,
                lifecycle.lifecycle_service.resume,
                event_type="draft.resumed",
                audit_action="resumed",
                actor_auth_user_id=host,
            )
            await s.commit()
        await self._away(host, self.ids["m2"], True)

        self.assertEqual("live", await self._status(draft_id))

    async def test_reforming_the_lobby_or_closing_the_mix_cancels_its_draft(self) -> None:
        host, _ = await self._host()
        first = await self._seed_lobby(host)
        second = await self._seed_lobby(host)  # Draft again: re-forming the lobby
        async with self.Session() as s:
            await CustomGameService().close(s, **self._as_host(host))
            await s.commit()

        self.assertEqual(("cancelled", "cancelled"), (await self._status(first), await self._status(second)))

    async def test_a_drafting_lobby_reads_draft_setup_and_its_pool_is_seated(self) -> None:
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        async with self.Session() as s:
            read = await custom._with_roster(s, await s.get_one(models.CustomGame, self.cg_id))

        [lobby] = read["lobbies"]
        self.assertEqual(("draft_setup", draft_id), (lobby["state"], lobby["draft_session_id"]))
        self.assertEqual({0}, {row["current_lobby"] for row in read["players"]})

    async def test_a_live_drafts_lobby_read_carries_the_first_picks_clock_start(self) -> None:
        """U1: a drafting card times the draft from its first pick's clock, as it times bans; setup has no time yet."""
        host, _ = await self._host()
        draft_id = await self._seed_lobby(host)
        async with self.Session() as s:
            [setup] = (await custom._with_roster(s, await s.get_one(models.CustomGame, self.cg_id)))["lobbies"]
        await self._start(draft_id, host)
        async with self.Session() as s:
            started = await s.scalar(
                sa.select(models.DraftPick.clock_started_at).where(
                    models.DraftPick.session_id == draft_id, models.DraftPick.overall_no == 1
                )
            )
            [live] = (await custom._with_roster(s, await s.get_one(models.CustomGame, self.cg_id)))["lobbies"]

        self.assertEqual(("draft_setup", None), (setup["state"], setup["live_started_at"]))
        self.assertEqual(("draft_live", started.isoformat()), (live["state"], live["live_started_at"]))

    @unittest.skipUnless(importlib.util.find_spec("balancer_native"), "balancer_native is not installed")
    async def test_a_tied_overflow_pool_seats_the_same_players_in_a_draft_as_in_a_balance(self) -> None:
        """R-S3: nobody has a rotation history, so the overflow tie falls to the balancer's own input order. m4 heads
        the roster's order -- a draft that read the roster would seat them and leave m3 waiting."""
        host, _ = await self._host()
        await self._member("m4", "damage", 2600, sort_order=-1)
        await self._seed_lobby(host)
        async with self.Session() as s:
            drafted = (await CustomGameService().draft_lobbies(s, self.cg_id))[0][2]
            await CustomGameService().balance(s, **self._as_host(host))
            await s.commit()
            lobby = await s.get_one(models.CustomGameLobby, (self.cg_id, 0))

        self.assertEqual(4, len(drafted))
        self.assertEqual(seated_member_ids(lobby.balance_result_json, 0), drafted)

    async def test_split_pool_seeds_one_draft_per_lobby_from_disjoint_halves(self) -> None:
        host, _ = await self._host()
        for name, role, rank in (
            ("m4", "tank", 2300),
            ("m5", "damage", 2200),
            ("m6", "tank", 2100),
            ("m7", "damage", 2000),
        ):
            await self._member(name, role, rank)
        async with self.Session() as s:
            (await s.get_one(models.CustomGame, self.cg_id)).lobby_count = 2
            s.add(models.CustomGameLobby(custom_game_id=self.cg_id, lobby_index=1))
            await s.commit()
        async with self.Session() as s:
            await mix_draft_service.split_pool(s, **self._as_host(host))
            await s.commit()
            pools = await CustomGameService().draft_lobbies(s, self.cg_id)
        self.draft_ids.extend(entry[0] for entry in pools.values())

        self.assertEqual({0, 1}, set(pools))
        self.assertEqual({"ready"}, {entry[1] for entry in pools.values()})
        self.assertEqual([4, 4], [len(pools[index][2]) for index in (0, 1)])
        self.assertFalse(pools[0][2] & pools[1][2])
