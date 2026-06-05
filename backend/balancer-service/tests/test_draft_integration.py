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

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from shared.core.enums import DraftPickStatus, DraftPlayerStatus, DraftRole, DraftStatus  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.models.draft import DraftPick  # noqa: E402
from shared.models.realtime import WorkspaceEvent  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.models.user import User  # noqa: E402
from shared.models.workspace import Workspace  # noqa: E402
from src import models  # noqa: E402
from src.services.draft import board as draft_board  # noqa: E402
from src.services.draft import clock as draft_clock  # noqa: E402
from src.services.draft import export as draft_export  # noqa: E402
from src.services.draft import lifecycle, selection  # noqa: E402
from src.services.draft import realtime as draft_realtime  # noqa: E402


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
            tourn = Tournament(workspace_id=ws.id, name=f"T {self._suffix}", status=DraftStatus.SETUP.value)
            # Tournament.status is TournamentStatus; reuse "draft" value via enum string.
            tourn.status = "draft"
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
            self.workspace_id = ws.id
            self.tournament_id = tourn.id
            self.captain_user_ids = [u.id for u in users]
            self.captain_auth_user_ids = [u.id for u in auth_users]
            await s.commit()

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as s:
            from shared.models.draft import DraftSession

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
            await s.execute(
                sa.delete(models.AuthUserPlayer).where(
                    models.AuthUserPlayer.auth_user_id.in_(self.captain_auth_user_ids)
                )
            )
            await s.execute(sa.delete(User).where(User.id.in_(self.captain_user_ids)))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self.captain_auth_user_ids)))
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.commit()
        await self.engine.dispose()

    def _captains(self) -> list[lifecycle.CaptainSeed]:
        return [
            lifecycle.CaptainSeed(name=f"Cap{i}", draft_position=i + 1, user_id=uid)
            for i, uid in enumerate(self.captain_user_ids)
        ]

    def _players(self) -> list[lifecycle.PlayerSeed]:
        roles = [DraftRole.TANK, DraftRole.DPS, DraftRole.SUPPORT]
        return [
            lifecycle.PlayerSeed(primary_role=roles[i % 3], rank_value=3000 + i * 50, battle_tag=f"P{i}#1")
            for i in range(9)
        ]

    async def _new_session(self, s):
        draft = await lifecycle.create_session(
            s,
            tournament_id=self.tournament_id,
            workspace_id=self.workspace_id,
            rounds=2,
            team_size=3,
        )
        await lifecycle.seed(s, draft, captains=self._captains(), players=self._players())
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
            await lifecycle.start(s, draft)
            await s.commit()
            self.assertEqual(draft.status, DraftStatus.LIVE.value)
            self.assertIsNotNone(draft.current_pick_id)
            current = await s.get(DraftPick, draft.current_pick_id)
            self.assertEqual(current.status, DraftPickStatus.ON_CLOCK.value)
            self.assertEqual(current.overall_no, 1)
            self.assertIsNotNone(current.clock_expires_at)

    async def test_select_advances_board(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(lifecycle.DraftTeam, current.draft_team_id)
            available = (
                await s.scalars(
                    sa.select(lifecycle.DraftPlayer).where(
                        lifecycle.DraftPlayer.session_id == draft.id,
                        lifecycle.DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
                    )
                )
            ).all()
            chosen = available[0]
            res = await selection.select(
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

    async def test_select_allows_captain_auth_user_without_team_import(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.create_session(
                s,
                tournament_id=self.tournament_id,
                workspace_id=self.workspace_id,
                rounds=2,
                team_size=3,
            )
            captains = [
                lifecycle.CaptainSeed(
                    name=f"AuthCap{i}",
                    draft_position=i + 1,
                    auth_user_id=auth_user_id,
                )
                for i, auth_user_id in enumerate(self.captain_auth_user_ids)
            ]
            await lifecycle.seed(s, draft, captains=captains, players=self._players())
            await lifecycle.start(s, draft)
            await s.commit()

            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(lifecycle.DraftTeam, current.draft_team_id)
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

            res = await selection.select(
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
            await lifecycle.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            team = await s.get(lifecycle.DraftTeam, current.draft_team_id)
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

            res = await selection.select(
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
            await lifecycle.start(s, draft)
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
                await selection.select(
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
            await lifecycle.start(s, draft)
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

            res = await selection.select(
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
            await lifecycle.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            v = current.version
            won_first = await selection._finalize(
                s,
                current.id,
                status=DraftPickStatus.COMPLETED,
                player_id=None,
                picked_by_user_id=None,
                is_autopick=False,
                is_admin_override=False,
                expected_version=v,
            )
            # Second writer with the same expected_version must lose.
            won_second = await selection._finalize(
                s,
                current.id,
                status=DraftPickStatus.AUTOPICKED,
                player_id=None,
                picked_by_user_id=None,
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
            await lifecycle.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            res = await selection.autopick(s, draft, current, expected_version=current.version)
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
                await lifecycle.create_session(
                    s2,
                    tournament_id=self.tournament_id,
                    workspace_id=self.workspace_id,
                    rounds=2,
                    team_size=3,
                )
                await s2.commit()

    async def test_full_run_autopick_to_completion_then_export(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.start(s, draft)
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
                await selection.autopick(s, draft, current, expected_version=current.version)
                await s.commit()

            self.assertEqual(draft.status, DraftStatus.COMPLETED.value)

            _, removed, imported = await draft_export.export(s, draft)
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
            await lifecycle.start(s, draft)
            await s.commit()
            with self.assertRaises(ApiHTTPException):
                await draft_export.export(s, draft)

    async def test_clock_fires_autopick_when_expired(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.start(s, draft)
            await s.commit()
            current = await s.get(DraftPick, draft.current_pick_id)
            current.clock_expires_at = datetime.now(UTC) - timedelta(seconds=1)  # force overdue
            await s.commit()
            pick_id = current.id
            session_id = draft.id

        fired = await draft_clock.fire_autopick_if_expired(self.Session, None, session_id)
        self.assertTrue(fired)
        async with self.Session() as s:
            pick = await s.get(DraftPick, pick_id)
            self.assertEqual(pick.status, DraftPickStatus.AUTOPICKED.value)
            self.assertTrue(pick.is_autopick)

    async def test_clock_noop_when_not_expired(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.start(s, draft)
            await s.commit()  # clock_expires_at ~45s in the future
            session_id = draft.id
        fired = await draft_clock.fire_autopick_if_expired(self.Session, None, session_id)
        self.assertFalse(fired)

    async def test_board_snapshot_carries_event_cursor(self) -> None:
        # Reconnect/replay correctness: /board reports last_event_id so the
        # client can subscribe with after_event_id and converge.
        async with self.Session() as s:
            draft = await self._new_session(s)
            await draft_realtime.publish_draft_event(
                s,
                None,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
            )
            await s.commit()
            topic = f"tournament:{self.tournament_id}:draft"
            max_id = await s.scalar(sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic == topic))
            board = await draft_board.build_board(s, draft)
            self.assertIsNotNone(board.last_event_id)
            self.assertEqual(board.last_event_id, max_id)
            # all pool players present (rosters renderable), not just available
            self.assertGreater(len(board.players), 0)

    async def test_export_is_idempotent(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await lifecycle.start(s, draft)
            await s.commit()
            guard = 0
            while True:
                await s.refresh(draft)
                if draft.status != DraftStatus.LIVE.value:
                    break
                guard += 1
                self.assertLess(guard, 50)
                current = await s.get(DraftPick, draft.current_pick_id)
                await selection.autopick(s, draft, current, expected_version=current.version)
                await s.commit()

            _, removed1, imported1 = await draft_export.export(s, draft)
            await s.commit()
            self.assertEqual((removed1, imported1), (0, 3))

            # Re-export: prior teams are removed first, then re-created.
            _, removed2, imported2 = await draft_export.export(s, draft)
            await s.commit()
            self.assertEqual(removed2, 3)
            self.assertEqual(imported2, 3)
            teams = (
                await s.scalars(sa.select(models.Team).where(models.Team.tournament_id == self.tournament_id))
            ).all()
            self.assertEqual(len(teams), 3)

    async def _build_balancer_pool(self, s, n: int) -> list[int]:
        """Create n approved, in-pool BalancerRegistration rows (with roles). Returns ids."""
        from shared.models.balancer import BalancerRegistration, BalancerRegistrationRole

        roles = ["tank", "dps", "support"]
        ids: list[int] = []
        for i in range(n):
            tag = f"Pool{self._suffix}-{i}#1"
            reg = BalancerRegistration(
                tournament_id=self.tournament_id,
                workspace_id=self.workspace_id,
                battle_tag=tag,
                battle_tag_normalized=tag.lower(),
                display_name=tag,
                status="approved",
                balancer_status="ready",
                exclude_from_balancer=False,
            )
            s.add(reg)
            await s.flush()
            s.add(
                BalancerRegistrationRole(
                    registration_id=reg.id,
                    role=roles[i % 3],
                    is_primary=True,
                    priority=1,
                    rank_value=3000 + i * 25,
                    is_active=True,
                )
            )
            ids.append(reg.id)
        await s.flush()
        return ids

    async def test_seed_from_pool_uses_existing_balancer_pool(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, rounds=2, team_size=3
            )
            pool_ids = await self._build_balancer_pool(s, 9)
            captain_ids = pool_ids[:3]
            await lifecycle.seed_from_pool(s, draft, captain_registration_ids=captain_ids)
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
            # roles came from the balancer pool (not a TANK placeholder for all)
            self.assertEqual({p.primary_role for p in players}, {"tank", "dps", "support"})
            available = [p for p in players if p.status == DraftPlayerStatus.AVAILABLE.value]
            self.assertEqual(len(available), 6)
            # ranks carried over from the pool
            self.assertTrue(all(p.rank_value and p.rank_value >= 3000 for p in players))

    async def test_seed_from_pool_weakest_first_orders_seats_by_rank(self) -> None:
        from shared.core.enums import DraftCaptainOrder

        async with self.Session() as s:
            draft = await lifecycle.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, rounds=2, team_size=3
            )
            pool_ids = await self._build_balancer_pool(s, 9)
            # ranks = 3000 + i*25, so captains[0..2] have ranks 3000 < 3025 < 3050
            captain_ids = pool_ids[:3]
            await lifecycle.seed_from_pool(
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
            ordered = sorted(teams, key=lambda team: team.draft_position)
            ranks_in_seat_order = [cap_by_team[team.id].rank_value for team in ordered]
            # position 1 picks first = weakest captain
            self.assertEqual(ranks_in_seat_order, [3000, 3025, 3050])

    async def test_can_create_new_draft_after_cancel(self) -> None:
        async with self.Session() as s:
            first = await self._new_session(s)
            await lifecycle.cancel(s, first)
            await s.commit()
            self.assertEqual(first.status, DraftStatus.CANCELLED.value)
        # A cancelled draft must not block creating a fresh one.
        async with self.Session() as s:
            second = await lifecycle.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, rounds=2, team_size=3
            )
            await s.commit()
            self.assertEqual(second.status, DraftStatus.SETUP.value)
            self.assertNotEqual(second.id, first.id)

    async def test_seed_from_pool_rejects_captain_not_in_pool(self) -> None:
        async with self.Session() as s:
            draft = await lifecycle.create_session(
                s, tournament_id=self.tournament_id, workspace_id=self.workspace_id, rounds=2, team_size=3
            )
            await self._build_balancer_pool(s, 4)
            with self.assertRaises(ApiHTTPException):
                await lifecycle.seed_from_pool(s, draft, captain_registration_ids=[999999])

    async def test_realtime_publisher_persists_event(self) -> None:
        async with self.Session() as s:
            draft = await self._new_session(s)
            await draft_realtime.publish_draft_event(
                s,
                None,  # no redis: only the durable WorkspaceEvent is written
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
