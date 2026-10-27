"""The scheduled pick-ban passes, driven the way ``serve.py`` and the config-save
trigger drive them.

Real Postgres, through ``LoopCase``: the stalled sweep's prefilter is SQL, and what
it may skip is exactly what ``room_owes_write`` answers False for -- both halves
have to run against the same rows to pin that. Each pass scans the whole shared
database, so a spy hands every room that is not this test's a "nothing owed"
without touching it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from shared.core import enums
from shared.models.encounter import Encounter
from shared.models.encounter.pick_ban import PickBanSession
from shared.models.identity.auth_user import AuthUser
from shared.models.tournament.scrim import ScrimRoom
from shared.models.tournament.stage import Stage
from shared.services.encounter.participants import place_team
from src.services.encounter import room_reconcile
from src.services.encounter.games import encounter_game_service
from src.services.encounter.pick_ban_action import pick_ban_action_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from tests.test_pregame_room_loop import LoopCase, ban_ruleset


class SweepCase(LoopCase):
    async def add_room(self, *, seats: int = 2) -> tuple[int, list[int]]:
        """Another room of the same tournament with ``seats`` of its two slots seated: ``(encounter, seats)``."""
        async with self.Session() as s:
            first = await s.get_one(Encounter, self.encounter_id)
            room = Encounter(
                workspace_id=self.workspace_id,
                discipline=self.discipline,
                tournament_id=self.tournament_id,
                scoring_rule_id=first.scoring_rule_id,
                name="F",
                slot_count=2,
                best_of=3,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(room)
            await s.flush()
            seated = [
                (await place_team(s, room, slot=slot, team_id=None, name=f"S{slot}", seed=slot, members=())).id
                for slot in range(1, seats + 1)
            ]
            await s.commit()
            return room.id, seated

    async def open_position(self, encounter_id: int) -> None:
        async with self.Session() as s:
            encounter = await s.get_one(Encounter, encounter_id)
            await encounter_game_service.open_game(s, encounter, position=1)
            await s.commit()

    async def ready(self, encounter_id: int, seats: list[int]) -> None:
        async with self.Session() as s:
            encounter = await s.get_one(Encounter, encounter_id)
            for seat in seats:
                await pick_ban_session_service.mark_ready(s, encounter, seat, None)

    async def games(self, encounter_id: int) -> int:
        async with self.Session() as s:
            return len(await encounter_game_service.list_games(s, encounter_id))

    async def owes(self, encounter_id: int) -> bool:
        async with self.Session() as s:
            return await pick_ban_action_service.room_owes_write(s, await s.get_one(Encounter, encounter_id))

    def spy(self, rooms: set[int], *, fail: int | None = None):
        """A stand-in for ``reconcile_encounter`` that heals only ``rooms`` and records, per visit, whether the
        pass's session still had a transaction open on the way in. ``fail`` raises for that room instead."""
        visits: list[tuple[int, bool]] = []
        real = room_reconcile.reconcile_encounter

        async def visit(session, encounter_id: int, *, skip_locked: bool = False) -> bool:
            if encounter_id not in rooms:
                return False
            visits.append((encounter_id, session.in_transaction()))
            if encounter_id == fail:
                raise RuntimeError("a room the organizer broke")
            return await real(session, encounter_id, skip_locked=skip_locked)

        return visits, visit

    async def sweep(self, *rooms: int) -> list[tuple[int, bool]]:
        visits, visit = self.spy(set(rooms))
        with (
            patch.object(room_reconcile.db, "async_session_maker", self.Session),
            patch.object(room_reconcile, "reconcile_encounter", visit),
        ):
            await room_reconcile.reconcile_stalled_rooms()
        return visits


class StalledSweepTests(SweepCase):
    async def test_a_room_nothing_can_be_owed_is_never_loaded(self) -> None:
        """No session, no config, an open game: every branch of ``room_owes_write`` is closed, so SQL drops it."""
        await self.open_position(self.encounter_id)
        self.assertFalse(await self.owes(self.encounter_id))
        self.assertEqual([], await self.sweep(self.encounter_id))

    async def test_a_room_owed_its_next_position_is_swept_and_healed(self) -> None:
        self.assertTrue(await self.owes(self.encounter_id))
        self.assertEqual([self.encounter_id], [room for room, _ in await self.sweep(self.encounter_id)])
        self.assertEqual(1, await self.games(self.encounter_id))

    async def test_a_closed_scrim_room_is_left_alone(self) -> None:
        """By decision, not by ``room_owes_write``: the room still owes its next position, but a closed scrim is
        history the backstop stops visiting."""
        async with self.Session() as s:
            first = await s.get_one(Encounter, self.encounter_id)
            author = AuthUser(email=f"{self.tag}@example.test", username=self.tag)
            stage = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=first.scoring_rule_id,
                name="Scrim",
                stage_type=enums.StageType.ROUND_ROBIN,
            )
            s.add_all([author, stage])
            await s.flush()
            s.add(
                ScrimRoom(
                    token=self.tag,
                    label="Scrim",
                    workspace_id=self.workspace_id,
                    tournament_id=self.tournament_id,
                    stage_id=stage.id,
                    encounter_id=self.encounter_id,
                    created_by_auth_user_id=author.id,
                    closed_at=datetime.now(UTC),
                )
            )
            await s.commit()
            self.addAsyncCleanup(self.drop_author, author.id)
        self.assertTrue(await self.owes(self.encounter_id))
        self.assertEqual([], await self.sweep(self.encounter_id))

    async def drop_author(self, author_id: int) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(AuthUser).where(AuthUser.id == author_id))
            await s.commit()

    async def test_a_config_keeps_an_idle_room_in_the_sweep(self) -> None:
        """A config can owe a room its opening, so the prefilter may not decide it; readiness answers it, unlocked."""
        await self.open_position(self.encounter_id)
        await self.save_config()
        self.assertEqual([self.encounter_id], [room for room, _ in await self.sweep(self.encounter_id)])

    async def test_a_live_session_keeps_the_room_in_the_sweep(self) -> None:
        await self.start(ban_ruleset(timer_seconds=30))
        await self.reconcile()
        self.assertEqual(1, await self.games(self.encounter_id))
        # The clock ran out while nobody wrote anything: only a room with a session can owe that.
        async with self.Session() as s:
            pick_ban = await pick_ban_session_service.get_pick_ban_session(
                s, self.encounter_id, enums.PickBanKind.HERO, for_update=True
            )
            pick_ban.current_step_started_at = datetime.now(UTC) - timedelta(minutes=5)
            await s.commit()
        self.assertEqual([self.encounter_id], [room for room, _ in await self.sweep(self.encounter_id)])
        banned = [entry for entry in (await self.state())["pool"] if entry["status"] == "banned"]
        self.assertEqual(1, len(banned))

    async def test_each_room_is_checked_in_its_own_transaction(self) -> None:
        """A steady room returns with its read transaction open; the sweep ends it before the next room."""
        await self.start()
        await self.reconcile()
        other, _seats = await self.add_room()
        await self.open_position(other)
        self.assertFalse(await self.owes(self.encounter_id))
        self.assertFalse(await self.owes(other))

        visits = await self.sweep(self.encounter_id, other)

        self.assertEqual([self.encounter_id, other], [room for room, _ in visits])
        self.assertFalse(visits[1][1], "the previous room's transaction was still open")


class ConfigSavePassTests(SweepCase):
    async def test_a_failing_room_does_not_stop_the_pass_and_unready_rooms_are_not_visited(self) -> None:
        await self.save_config()
        await self.ready(self.encounter_id, self.seats)
        ready, ready_seats = await self.add_room()
        await self.ready(ready, ready_seats)
        unready, _seats = await self.add_room()

        visits, visit = self.spy({self.encounter_id, ready, unready}, fail=self.encounter_id)
        with (
            patch.object(room_reconcile.db, "async_session_maker", self.Session),
            patch.object(room_reconcile, "reconcile_encounter", visit),
        ):
            await room_reconcile._reconcile_in_new_session(("tournament", self.tournament_id))

        self.assertEqual([self.encounter_id, ready], [room for room, _ in visits])
        async with self.Session() as s:
            self.assertIsNotNone(await pick_ban_session_service.get_pick_ban_session(s, ready, enums.PickBanKind.HERO))


class DueTickTests(SweepCase):
    async def test_a_room_whose_steps_no_longer_build_does_not_stop_the_clock(self) -> None:
        """An old-format sequence naming a slot nobody holds any more raises when built. The tick hands that room to
        ``_sweep`` as due -- where it fails alone -- instead of failing for every room."""
        await self.start(ban_ruleset(timer_seconds=30))
        broken, _seats = await self.add_room(seats=1)
        async with self.Session() as s:
            s.add(
                PickBanSession(
                    encounter_id=broken,
                    kind=enums.PickBanKind.HERO,
                    pool_json={},
                    seed_source=enums.VetoSeedSource.FALLBACK_FIRST_SLOT,
                    resolved_sequence_json=[{"sides": ["away"]}],
                    ruleset_json={},
                    status=enums.MapVetoSessionStatus.ACTIVE,
                )
            )
            pick_ban = await pick_ban_session_service.get_pick_ban_session(
                s, self.encounter_id, enums.PickBanKind.HERO, for_update=True
            )
            pick_ban.current_step_started_at = datetime.now(UTC) - timedelta(minutes=5)
            await s.commit()

        with patch.object(room_reconcile.db, "async_session_maker", self.Session):
            await room_reconcile.reconcile_due_rooms()

        banned = [entry for entry in (await self.state())["pool"] if entry["status"] == "banned"]
        self.assertEqual(1, len(banned))
        self.assertEqual(self.slot1, banned[0]["picked_by_team_id"])
