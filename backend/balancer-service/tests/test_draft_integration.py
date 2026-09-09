"""Integration tests for the draft service layer against a real Postgres.

Requires a reachable database via POSTGRES_* env vars (use a disposable DB such
as anak_dev — NEVER production). Skips cleanly if the DB is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from shared.core.enums import (  # noqa: E402
    DraftPickStatus,
    DraftPlayerStatus,
    DraftStatus,
    HeroClass,
    TournamentStatus,
)
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.models.balancer.draft import DraftPick  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.platform.realtime import WorkspaceEvent  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistration,
    BalancerRegistrationRole,
)
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from src import models  # noqa: E402
from src.domain.draft.entities import PoolSeat  # noqa: E402
from src.services.draft import board as draft_board  # noqa: E402
from src.services.draft import clock as draft_clock  # noqa: E402
from src.services.draft import export as draft_export  # noqa: E402
from src.services.draft import lifecycle, loaders, selection  # noqa: E402
from src.services.draft import realtime as draft_realtime  # noqa: E402
from src.services.draft.rosters import draft_rosters  # noqa: E402

# The 3-slot roster these tests draft for. It replaces the old
# `rounds=2, team_size=3` pair: `role_targets_for_team_size(3)` resolved to
# 1 tank / 2 dps / 0 support, which is exactly this shape, and `draft_rounds`
# derives the same 2 rounds the calls used to pass explicitly.
_SHAPE = parse_roster_slots({"tank": 1, "dps": 2})


def _async_url() -> str:
    u = os.environ.get("POSTGRES_USER", "postgres")
    p = os.environ.get("POSTGRES_PASSWORD", "postgres")
    h = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "postgres")
    return f"postgresql+psycopg://{u}:{p}@{h}:{port}/{db}"


_UNIQUE = 0


def _uniq() -> int:
    global _UNIQUE
    _UNIQUE += 1
    return _UNIQUE


class DraftIntegrationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(_async_url(), connect_args={"connect_timeout": 30})
        try:
            async with self.engine.connect() as c:
                db = (await c.execute(sa.text("select current_database()"))).scalar()
                if db == "anak_v5":  # hard guard: never run against prod
                    self.skipTest("refusing to run integration tests against production anak_v5")
        except Exception as exc:  # noqa: BLE001
            await self.engine.dispose()
            self.skipTest(f"database unreachable: {exc}")

        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self._suffix = f"draft-it-{os.getpid()}-{_uniq()}"
        async with self.Session() as s:
            ws = Workspace(slug=f"ws-{self._suffix}", name=f"WS {self._suffix}")
            s.add(ws)
            await s.flush()
            # ``slug`` is NOT NULL and globally unique (migration tslug0001): the
            # public tournament route carries no workspace segment, so the
            # per-test suffix has to go into the slug too, not just the name.
            tourn = Tournament(
                workspace_id=ws.id,
                name=f"T {self._suffix}",
                slug=f"t-{self._suffix}",
                status=DraftStatus.SETUP.value,
            )
            # Tournament.status is TournamentStatus; reuse "draft" value via enum string.
            tourn.status = "draft"
            # The draft resolves its shape from the tournament/workspace override,
            # not from the shape stored on the session, so the override has to
            # match `_SHAPE` or every start preflight sees the default 5-stack.
            tourn.roster_slots_json = {"tank": 1, "dps": 2}
            s.add(tourn)
            await s.flush()
            users = []
            for i in range(3):
                u = User(name=f"cap-{self._suffix}-{i}")
                s.add(u)
                users.append(u)
            auth_users = []
            for i in range(3):
                au = models.AuthUser(
                    username=f"auth-cap-{self._suffix}-{i}",
                    email=f"auth-cap-{self._suffix}-{i}@example.test",
                )
                s.add(au)
                auth_users.append(au)
            await s.flush()
            # A draft seat is now a reference to a balancer registration, and a
            # registration's identity is its workspace_member. Captain identity
            # (both the domain player id and the auth user id the on-clock guard
            # accepts) therefore has to exist BEFORE any registration is written.
            for user, auth_user in zip(users, auth_users, strict=True):
                user.auth_user_id = auth_user.id
            members = [WorkspaceMember(workspace_id=ws.id, player_id=u.id) for u in users]
            for member in members:
                s.add(member)
            await s.flush()
            self.workspace_id = ws.id
            self.tournament_id = tourn.id
            self.captain_user_ids = [u.id for u in users]
            self.captain_auth_user_ids = [u.id for u in auth_users]
            self.captain_member_ids = [m.id for m in members]
            await s.commit()

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as s:
            from shared.models.balancer.draft import DraftSession

            ids = (
                await s.scalars(sa.select(DraftSession.id).where(DraftSession.tournament_id == self.tournament_id))
            ).all()
            for sid in ids:
                await s.execute(sa.delete(DraftSession).where(DraftSession.id == sid))
            # Rows created by export() + realtime publisher.
            await s.execute(sa.delete(WorkspaceEvent).where(WorkspaceEvent.tournament_id == self.tournament_id))
            await s.execute(sa.delete(models.Player).where(models.Player.tournament_id == self.tournament_id))
            await s.execute(sa.delete(models.Team).where(models.Team.tournament_id == self.tournament_id))
            await s.execute(sa.delete(Tournament).where(Tournament.id == self.tournament_id))
            # players.user.auth_user_id is a plain column on User (no separate
            # link-table row to clean up); deleting the User rows below is enough.
            await s.execute(sa.delete(User).where(User.id.in_(self.captain_user_ids)))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self.captain_auth_user_ids)))
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.commit()
        await self.engine.dispose()

    async def _registration(
        self,
        s,
        *,
        tag: str,
        ranks: dict[str, int | None],
        primary: str | None = None,
        workspace_member_id: int | None = None,
    ) -> int:
        """One approved, in-pool ``balancer.registration`` with its role rows.

        ``ranks`` is ``{slot_code: rank}`` in priority order; a ``None`` rank
        leaves the role DECLARED but unranked, which is what makes it unplayable
        and the registration unseatable.
        """
        reg = BalancerRegistration(
            tournament_id=self.tournament_id,
            battle_tag=tag,
            battle_tag_normalized=tag.lower(),
            display_name=tag,
            status="approved",
            balancer_status="ready",
            workspace_member_id=workspace_member_id,
        )
        s.add(reg)
        await s.flush()
        lead = primary or next(iter(ranks))
        for priority, (role, rank) in enumerate(ranks.items()):
            s.add(
                BalancerRegistrationRole(
                    registration_id=reg.id,
                    role=role,
                    is_primary=role == lead,
                    priority=priority,
                    rank_value=rank,
                    is_active=True,
                )
            )
        await s.flush()
        return reg.id

    async def _captain_seats(self, s) -> list[PoolSeat]:
        """Three TANK captains, each bound to a workspace member (= an identity)."""
        seats = []
        for i, member_id in enumerate(self.captain_member_ids):
            registration_id = await self._registration(
                s,
                tag=f"Cap{self._suffix}-{i}#1",
                ranks={"tank": 3400 + i * 10},
                workspace_member_id=member_id,
            )
            seats.append(PoolSeat(registration_id=registration_id, draft_position=i + 1, team_name=f"Cap{i}"))
        return seats

    async def _player_seats(self, s) -> list[PoolSeat]:
        # Captains are TANK in this fixture. A 3-slot roster therefore needs two
        # DPS picks per team; keep enough DPS players for the start preflight.
        roles = ["dps"] * 6 + ["tank", "support", "support"]
        seats = []
        for i, role in enumerate(roles):
            registration_id = await self._registration(s, tag=f"P{self._suffix}-{i}#1", ranks={role: 3000 + i * 50})
            seats.append(PoolSeat(registration_id=registration_id))
        return seats

    async def _seats(self, s) -> list[PoolSeat]:
        return [*await self._captain_seats(s), *await self._player_seats(s)]

    async def _new_session(self, s):
        draft = await lifecycle.lifecycle_service.create_session(
            s,
            tournament_id=self.tournament_id,
            workspace_id=self.workspace_id,
            shape=_SHAPE,
        )
        await lifecycle.lifecycle_service.seed(s, draft, seats=await self._seats(s))
        await s.commit()
        return draft

    async def test_seed_creates_snake_picks_and_ready(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            self.assertEqual(draft.status, DraftStatus.READY.value)
            picks = (await s.scalars(sa.select(DraftPick).where(DraftPick.session_id == draft.id))).all()
            # 3 teams x 2 rounds = 6 picks
            self.assertEqual(len(picks), 6)
            self.assertEqual(sorted(p.overall_no for p in picks), [1, 2, 3, 4, 5, 6])
            # round 2 is reversed (snake): pick 4 -> team of seat 2 (draft_position 3)
            by_no = {p.overall_no: p for p in picks}
            teams = (
                await s.scalars(sa.select(lifecycle.DraftTeam).where(lifecycle.DraftTeam.session_id == draft.id))
            ).all()
            pos_by_team = {t.id: t.draft_position for t in teams}
            self.assertEqual(pos_by_team[by_no[1].draft_team_id], 1)
            self.assertEqual(pos_by_team[by_no[4].draft_team_id], 3)

    async def test_start_arms_first_pick(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            self.assertEqual(draft.status, DraftStatus.LIVE.value)
            self.assertIsNotNone(draft.current_pick_id)
            current = await s.get(DraftPick, draft.current_pick_id)
            self.assertEqual(current.status, DraftPickStatus.ON_CLOCK.value)
            self.assertEqual(current.overall_no, 1)
            self.assertIsNotNone(current.clock_expires_at)

    async def test_start_gated_on_tournament_draft_phase(self) -> None:
        async def _set_status(s, status: TournamentStatus) -> None:
            await s.execute(
                sa.update(Tournament).values(status=status.value).where(Tournament.id == self.tournament_id)
            )
            await s.commit()

        async with self.Session() as s:
            draft = await self._new_session(s)
            await _set_status(s, TournamentStatus.REGISTRATION)

            with self.assertRaises(ApiHTTPException) as ctx:
                await lifecycle.lifecycle_service.start(s, draft)
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(ctx.exception.detail[0]["code"], "tournament_not_in_draft_phase")
            self.assertEqual(draft.status, DraftStatus.READY.value)

            await _set_status(s, TournamentStatus.DRAFT)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            self.assertEqual(draft.status, DraftStatus.LIVE.value)

    async def test_start_phase_gate_is_bypassed_for_superusers(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await s.execute(
                sa.update(Tournament)
                .values(status=TournamentStatus.REGISTRATION.value)
                .where(Tournament.id == self.tournament_id)
            )
            await s.commit()

            await lifecycle.lifecycle_service.start(s, draft, force=True)
            await s.commit()
            self.assertEqual(draft.status, DraftStatus.LIVE.value)

    async def test_select_advances_board(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(
                lifecycle.DraftTeam,
                current.draft_team_id,
                options=loaders.team_options(),
                populate_existing=True,
            )
            available = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer).where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                )
            ).all()
            chosen = available[0]
            res = await selection.selection_service.select(
                s,
                draft,
                current,
                player_id=chosen.id,
                expected_version=current.version,
                target_role=None,
                actor_user_id=team.captain_user_id,
                actor_auth_user_id=None,
                actor_player_ids=[team.captain_user_id],
                is_admin=False,
            )
            await s.commit()
            self.assertEqual(res.pick.status, DraftPickStatus.COMPLETED.value)
            self.assertIsNotNone(res.next_pick)
            self.assertEqual(res.next_pick.overall_no, 2)
            await s.refresh(chosen)
            self.assertEqual(chosen.status, DraftPlayerStatus.PICKED.value)
            self.assertEqual(chosen.drafted_by_team_id, current.draft_team_id)

    async def test_select_off_role_records_role_and_its_rank(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.lifecycle_service.create_session(
                s,
                tournament_id=self.tournament_id,
                workspace_id=self.workspace_id,
                shape=_SHAPE,
            )
            # A registration that leads TANK@3000 and can also play DPS@2500.
            flex_registration_id = await self._registration(
                s,
                tag=f"Flex{self._suffix}#1",
                ranks={"tank": 3000, "dps": 2500},
                primary="tank",
            )
            await lifecycle.lifecycle_service.seed(
                s,
                draft,
                seats=[*await self._seats(s), PoolSeat(registration_id=flex_registration_id)],
            )
            await s.commit()
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(
                lifecycle.DraftTeam,
                current.draft_team_id,
                options=loaders.team_options(),
                populate_existing=True,
            )
            chosen = await s.scalar(
                sa.select(lifecycle.DraftPlayer).where(
                    lifecycle.DraftPlayer.session_id == draft.id,
                    lifecycle.DraftPlayer.registration_id == flex_registration_id,
                )
            )
            res = await selection.selection_service.select(
                s,
                draft,
                current,
                player_id=chosen.id,
                expected_version=current.version,
                target_role=HeroClass.damage,
                actor_user_id=team.captain_user_id,
                actor_auth_user_id=None,
                actor_player_ids=[team.captain_user_id],
                is_admin=False,
            )
            await s.commit()
            # The pick records the drafted off-role and its rank (not primary TANK@3000).
            self.assertEqual(res.pick.target_role, HeroClass.damage.slot_code)
            self.assertEqual(res.pick.target_rank_value, 2500)

    async def test_select_allows_captain_auth_user_without_team_import(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.lifecycle_service.create_session(
                s,
                tournament_id=self.tournament_id,
                workspace_id=self.workspace_id,
                shape=_SHAPE,
            )
            # Captain identity comes from the registration's member: the auth
            # user id resolves through ``workspace_member.player.auth_user_id``,
            # so no imported team row is involved anywhere on this path.
            await lifecycle.lifecycle_service.seed(s, draft, seats=await self._seats(s))
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()

            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(
                lifecycle.DraftTeam,
                current.draft_team_id,
                options=loaders.team_options(),
                populate_existing=True,
            )
            chosen = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer)
                    .where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                    .order_by(lifecycle.DraftPlayer.id.asc())
                )
            ).first()

            res = await selection.selection_service.select(
                s,
                draft,
                current,
                player_id=chosen.id,
                expected_version=current.version,
                target_role=None,
                actor_user_id=None,
                actor_auth_user_id=team.captain_auth_user_id,
                actor_player_ids=[],
                is_admin=False,
            )
            await s.commit()

            self.assertEqual(res.pick.status, DraftPickStatus.COMPLETED.value)
            self.assertIsNone(res.pick.picked_by_user_id)

    async def test_select_allows_linked_public_player_id(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(
                lifecycle.DraftTeam,
                current.draft_team_id,
                options=loaders.team_options(),
                populate_existing=True,
            )
            chosen = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer)
                    .where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                    .order_by(lifecycle.DraftPlayer.id.asc())
                )
            ).first()

            res = await selection.selection_service.select(
                s,
                draft,
                current,
                player_id=chosen.id,
                expected_version=current.version,
                target_role=None,
                actor_user_id=None,
                actor_auth_user_id=self.captain_auth_user_ids[0],
                actor_player_ids=[team.captain_user_id],
                is_admin=False,
            )
            await s.commit()

            self.assertEqual(res.pick.status, DraftPickStatus.COMPLETED.value)

    async def test_select_rejects_wrong_captain(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            chosen = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer)
                    .where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                    .order_by(lifecycle.DraftPlayer.id.asc())
                )
            ).first()

            with self.assertRaises(ApiHTTPException) as ctx:
                await selection.selection_service.select(
                    s,
                    draft,
                    current,
                    player_id=chosen.id,
                    expected_version=current.version,
                    target_role=None,
                    actor_user_id=None,
                    actor_auth_user_id=self.captain_auth_user_ids[-1],
                    actor_player_ids=[self.captain_user_ids[-1]],
                    is_admin=False,
                )

            self.assertEqual(ctx.exception.status_code, 403)

    async def test_select_allows_admin_bypass(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            chosen = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer)
                    .where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                    .order_by(lifecycle.DraftPlayer.id.asc())
                )
            ).first()

            res = await selection.selection_service.select(
                s,
                draft,
                current,
                player_id=chosen.id,
                expected_version=current.version,
                target_role=None,
                actor_user_id=None,
                actor_auth_user_id=None,
                actor_player_ids=[],
                is_admin=True,
            )
            await s.commit()

            self.assertEqual(res.pick.status, DraftPickStatus.COMPLETED.value)

    async def test_finalize_race_only_one_winner(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            v = current.version
            won_first = await selection.selection_service._finalize(
                s,
                current.id,
                status=DraftPickStatus.COMPLETED,
                player_id=None,
                picked_by_member_id=None,
                is_autopick=False,
                is_admin_override=False,
                expected_version=v,
            )
            # Second writer with the same expected_version must lose.
            won_second = await selection.selection_service._finalize(
                s,
                current.id,
                status=DraftPickStatus.AUTOPICKED,
                player_id=None,
                picked_by_member_id=None,
                is_autopick=True,
                is_admin_override=False,
                expected_version=v,
            )
            await s.commit()
            self.assertTrue(won_first)
            self.assertFalse(won_second)

    async def test_autopick_picks_available_and_advances(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            res = await selection.selection_service.autopick(s, draft, current, expected_version=current.version)
            await s.commit()
            self.assertIn(res.pick.status, {DraftPickStatus.AUTOPICKED.value})
            self.assertIsNotNone(res.pick.picked_player_id)
            self.assertTrue(res.pick.is_autopick)
            self.assertIsNotNone(res.next_pick)

    async def test_one_active_draft_per_tournament(self) -> None:
        async with self.Session() as s:
            await self._new_session(s)
        async with self.Session() as s2:
            with self.assertRaises(ApiHTTPException):
                await lifecycle.lifecycle_service.create_session(
                    s2,
                    tournament_id=self.tournament_id,
                    workspace_id=self.workspace_id,
                    shape=_SHAPE,
                )
                await s2.commit()

    async def test_delete_session_erases_teams_players_and_picks(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            draft_id = draft.id

            await lifecycle.lifecycle_service.delete_session(s, draft)
            await s.commit()

            from shared.models.balancer.draft import DraftPlayer, DraftSession, DraftTeam

            for model in (DraftSession, DraftTeam, DraftPlayer, DraftPick):
                column = DraftSession.id if model is DraftSession else model.session_id
                remaining = (await s.scalars(sa.select(model.id).where(column == draft_id))).all()
                self.assertEqual(list(remaining), [], f"{model.__name__} rows survived the delete")

        # The active-session index is free again, so a fresh draft can be set up.
        async with self.Session() as s2:
            replacement = await lifecycle.lifecycle_service.create_session(
                s2,
                tournament_id=self.tournament_id,
                workspace_id=self.workspace_id,
                shape=_SHAPE,
            )
            await s2.commit()
            self.assertNotEqual(replacement.id, draft_id)

    async def test_delete_session_erases_a_cancelled_draft(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.cancel(s, draft)
            await s.commit()
            draft_id = draft.id

            await lifecycle.lifecycle_service.delete_session(s, draft)
            await s.commit()

            from shared.models.balancer.draft import DraftSession

            self.assertIsNone(await s.get(DraftSession, draft_id))

    async def test_full_run_autopick_to_completion_then_export(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()

            # Autopick every pick until the draft completes.
            guard = 0
            while True:
                await s.refresh(draft)
                if draft.status != DraftStatus.LIVE.value:
                    break
                guard += 1
                self.assertLess(guard, 50, "draft did not converge")
                current = await s.get(DraftPick, draft.current_pick_id)
                await selection.selection_service.autopick(s, draft, current, expected_version=current.version)
                await s.commit()

            self.assertEqual(draft.status, DraftStatus.COMPLETED.value)

            _, removed, imported = await draft_export.export_service.export(s, draft)
            await s.commit()
            self.assertEqual(removed, 0)
            self.assertEqual(imported, 3)
            self.assertEqual(draft.export_status, "success")
            self.assertIsNotNone(draft.exported_at)

            teams = (
                await s.scalars(sa.select(models.Team).where(models.Team.tournament_id == self.tournament_id))
            ).all()
            self.assertEqual(len(teams), 3)
            dteams = (
                await s.scalars(sa.select(lifecycle.DraftTeam).where(lifecycle.DraftTeam.session_id == draft.id))
            ).all()
            self.assertTrue(all(t.exported_team_id is not None for t in dteams))

    async def test_export_rejects_incomplete_draft(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            with self.assertRaises(ApiHTTPException):
                await draft_export.export_service.export(s, draft)

    async def test_clock_fires_autopick_when_expired(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            current.clock_expires_at = datetime.now(UTC) - timedelta(seconds=1)  # force overdue
            await s.commit()
            pick_id = current.id
            session_id = draft.id

        fired = await draft_clock.draft_clock_service.fire_autopick_if_expired(self.Session, session_id)
        self.assertTrue(fired)
        async with self.Session() as s:
            pick = await s.get(DraftPick, pick_id)
            self.assertEqual(pick.status, DraftPickStatus.AUTOPICKED.value)
            self.assertTrue(pick.is_autopick)

    async def test_clock_noop_when_not_expired(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()  # clock_expires_at ~45s in the future
            session_id = draft.id
        fired = await draft_clock.draft_clock_service.fire_autopick_if_expired(self.Session, session_id)
        self.assertFalse(fired)

    async def test_board_snapshot_carries_event_cursor(self) -> None:
        # Reconnect/replay correctness: /board reports last_event_id so the
        # client can subscribe with after_event_id and converge.
        async with self.Session() as s:
            draft = await self._new_session(s)
            await draft_realtime.publish_draft_event(
                s,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
            )
            await s.commit()
            topic = f"tournament:{self.tournament_id}:draft"
            max_id = await s.scalar(sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic == topic))
            board = await draft_board.board_service.build_board(s, draft)
            self.assertIsNotNone(board.last_event_id)
            self.assertEqual(board.last_event_id, max_id)
            # all pool players present (rosters renderable), not just available
            self.assertGreater(len(board.players), 0)

    async def test_export_is_idempotent(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()
            guard = 0
            while True:
                await s.refresh(draft)
                if draft.status != DraftStatus.LIVE.value:
                    break
                guard += 1
                self.assertLess(guard, 50)
                current = await s.get(DraftPick, draft.current_pick_id)
                await selection.selection_service.autopick(s, draft, current, expected_version=current.version)
                await s.commit()

            _, removed1, imported1 = await draft_export.export_service.export(s, draft)
            await s.commit()
            self.assertEqual((removed1, imported1), (0, 3))

            # Re-export: prior teams are removed first, then re-created.
            _, removed2, imported2 = await draft_export.export_service.export(s, draft)
            await s.commit()
            self.assertEqual(removed2, 3)
            self.assertEqual(imported2, 3)
            teams = (
                await s.scalars(sa.select(models.Team).where(models.Team.tournament_id == self.tournament_id))
            ).all()
            self.assertEqual(len(teams), 3)

    async def _build_balancer_pool(self, s, n: int) -> list[int]:
        """Create n approved, in-pool BalancerRegistration rows (with roles). Returns ids."""
        roles = ["tank", "dps", "support"]
        return [
            await self._registration(s, tag=f"Pool{self._suffix}-{i}#1", ranks={roles[i % 3]: 3000 + i * 25})
            for i in range(n)
        ]

    async def test_seed_from_pool_uses_existing_balancer_pool(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.lifecycle_service.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, shape=_SHAPE
            )
            pool_ids = await self._build_balancer_pool(s, 9)
            captain_ids = pool_ids[:3]
            await lifecycle.lifecycle_service.seed_from_pool(s, draft, captain_registration_ids=captain_ids)
            await s.commit()

            self.assertEqual(draft.status, DraftStatus.READY.value)
            teams = (
                await s.scalars(sa.select(lifecycle.DraftTeam).where(lifecycle.DraftTeam.session_id == draft.id))
            ).all()
            self.assertEqual(len(teams), 3)  # one team per captain
            players = (
                await s.scalars(sa.select(lifecycle.DraftPlayer).where(lifecycle.DraftPlayer.session_id == draft.id))
            ).all()
            self.assertEqual(len(players), 9)  # 3 captains + 6 pool, all derived from balancer
            captains = [p for p in players if p.is_captain]
            self.assertEqual(len(captains), 3)
            # Roles and ranks are NOT copied onto the seat any more; they are
            # resolved from the registration on every read, which is what makes a
            # rank typed in the balancer after seeding show up without a re-seed.
            rosters = await draft_rosters.load(s, draft, list(players))
            self.assertEqual(len(rosters), 9)
            leads = {rosters[p.id].primary.role.slot_code for p in players}
            self.assertEqual(leads, {"tank", "dps", "support"})
            available = [p for p in players if p.status == DraftPlayerStatus.AVAILABLE.value]
            self.assertEqual(len(available), 6)
            # ranks read back from the pool
            self.assertTrue(all(rosters[p.id].best_rank >= 3000 for p in players))

    async def test_seed_from_pool_weakest_first_orders_seats_by_rank(self) -> None:
        from shared.core.enums import DraftCaptainOrder

        async with self.Session() as s:
            draft = await lifecycle.lifecycle_service.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, shape=_SHAPE
            )
            pool_ids = await self._build_balancer_pool(s, 9)
            # ranks = 3000 + i*25, so captains[0..2] have ranks 3000 < 3025 < 3050
            captain_ids = pool_ids[:3]
            await lifecycle.lifecycle_service.seed_from_pool(
                s, draft, captain_registration_ids=captain_ids, captain_order=DraftCaptainOrder.WEAKEST_FIRST
            )
            await s.commit()

            teams = (
                await s.scalars(sa.select(lifecycle.DraftTeam).where(lifecycle.DraftTeam.session_id == draft.id))
            ).all()
            captains = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer).where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.is_captain.is_(True),
                    )
                )
            ).all()
            cap_by_team = {c.drafted_by_team_id: c for c in captains}
            rosters = await draft_rosters.load(s, draft, list(captains))
            ordered = sorted(teams, key=lambda team: team.draft_position)
            ranks_in_seat_order = [rosters[cap_by_team[team.id].id].best_rank for team in ordered]
            # position 1 picks first = weakest captain
            self.assertEqual(ranks_in_seat_order, [3000, 3025, 3050])

    async def test_seed_refuses_a_registration_the_balancer_ranks_on_no_role(self) -> None:
        # The old seeder labelled such a player ``damage`` with a NULL rank and
        # let them into the pool, where autopick scored them 0 and took them
        # last. There is no honest default, so seeding must refuse and name who
        # needs a rank -- before writing any team, player or pick row.
        async with self.Session() as s:
            draft = await lifecycle.lifecycle_service.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, shape=_SHAPE
            )
            draft_id = draft.id
            seats = await self._seats(s)
            unranked_id = await self._registration(
                s, tag=f"NoRank{self._suffix}#1", ranks={"dps": None, "support": None}
            )
            await s.commit()

            with self.assertRaises(ApiHTTPException) as ctx:
                await lifecycle.lifecycle_service.seed(s, draft, seats=[*seats, PoolSeat(registration_id=unranked_id)])

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(ctx.exception.detail[0]["code"], "draft_pool_unranked")
            self.assertIn(f"NoRank{self._suffix}#1", ctx.exception.detail[0]["msg"])
            await s.rollback()
            # ``rollback`` expires every instance, so the status is re-read from
            # the database rather than off the in-memory row -- which is the
            # stronger assertion anyway: the refused seed left SETUP committed.
            status = await s.scalar(
                sa.select(lifecycle.DraftSession.status).where(lifecycle.DraftSession.id == draft_id)
            )
            self.assertEqual(status, DraftStatus.SETUP.value)
            for model in (lifecycle.DraftTeam, lifecycle.DraftPlayer, DraftPick):
                rows = (await s.scalars(sa.select(model.id).where(model.session_id == draft_id))).all()
                self.assertEqual(list(rows), [], f"{model.__name__} rows were written on the refused seed")

    async def test_can_create_new_draft_after_cancel(self) -> None:
        async with self.Session() as s:
            first = await self._new_session(s)
            await lifecycle.lifecycle_service.cancel(s, first)
            await s.commit()
            self.assertEqual(first.status, DraftStatus.CANCELLED.value)
        # A cancelled draft must not block creating a fresh one.
        async with self.Session() as s:
            second = await lifecycle.lifecycle_service.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, shape=_SHAPE
            )
            await s.commit()
            self.assertEqual(second.status, DraftStatus.SETUP.value)
            self.assertNotEqual(second.id, first.id)

    async def test_seed_from_pool_rejects_captain_not_in_pool(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.lifecycle_service.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, shape=_SHAPE
            )
            await self._build_balancer_pool(s, 4)
            with self.assertRaises(ApiHTTPException):
                await lifecycle.lifecycle_service.seed_from_pool(s, draft, captain_registration_ids=[999999])

    async def test_realtime_publisher_persists_event(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await draft_realtime.publish_draft_event(
                s,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
            )
            await s.commit()
            topic = f"tournament:{self.tournament_id}:draft"
            row = await s.scalar(
                sa.select(WorkspaceEvent).where(
                    WorkspaceEvent.topic == topic,
                    WorkspaceEvent.event_type == "draft.session_updated",
                )
            )
            self.assertIsNotNone(row)
            self.assertEqual(row.tournament_id, self.tournament_id)
            self.assertEqual(row.payload["session_id"], draft.id)

    async def test_rollback_reverts_pick_and_players(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.lifecycle_service.start(s, draft)
            await s.commit()

            # Execute first pick
            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(
                lifecycle.DraftTeam,
                current.draft_team_id,
                options=loaders.team_options(),
                populate_existing=True,
            )
            available = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer).where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                )
            ).all()
            chosen = available[0]

            await selection.selection_service.select(
                s,
                draft,
                current,
                player_id=chosen.id,
                expected_version=current.version,
                target_role=None,
                actor_user_id=team.captain_user_id,
                actor_player_ids=[team.captain_user_id],
                is_admin=True,
            )
            await s.commit()

            # Now draft status is LIVE, pick 1 is completed, pick 2 is on_clock
            await s.refresh(draft)
            self.assertEqual(draft.status, DraftStatus.LIVE.value)
            await s.refresh(chosen)
            self.assertEqual(chosen.status, DraftPlayerStatus.PICKED.value)

            # Rollback
            await lifecycle.lifecycle_service.rollback(s, draft)
            await s.commit()

            # Draft status should be PAUSED, current pick back to pick 1 (on_clock), player status available
            await s.refresh(draft)
            self.assertEqual(draft.status, DraftStatus.PAUSED.value)
            self.assertEqual(draft.current_pick_id, current.id)

            await s.refresh(current)
            self.assertEqual(current.status, DraftPickStatus.ON_CLOCK.value)
            self.assertIsNone(current.picked_player_id)

            await s.refresh(chosen)
            self.assertEqual(chosen.status, DraftPlayerStatus.AVAILABLE.value)
            self.assertIsNone(chosen.drafted_by_team_id)
