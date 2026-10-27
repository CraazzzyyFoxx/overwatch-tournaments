"""Confirmations that owed more than they did, and reads that took a lock they did not need.

Real Postgres, through the result-flow fixture: every case here is about what a
write leaves in the outbox or the bracket, a row lock another session queues
behind, or a 409 the route answers before it writes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import sqlalchemy as sa

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.encounter import Encounter, EncounterGame, ScoringRule
from shared.models.platform.audit import AuditLog
from shared.models.platform.outbox import EventOutbox
from shared.models.tournament.encounter_link import EncounterLink
from shared.services.chat import SPECTATOR_ROLE, ChatRoom
from shared.services.encounter import participants
from src.rpc import _helpers as rpc_helpers
from src.rpc import ffa as ffa_rpc
from src.services.encounter.chat_access import encounter_chat_service
from src.services.encounter.ffa import ffa_encounter_service
from src.services.encounter.game_correction import game_correction_service
from src.services.encounter.games import GameResultIn, encounter_game_service
from tests._rpc_fakes import CapturingBroker, make_identity
from tests.test_encounter_result_flows import ResultFlowCase, _codes


def _linked():
    """Every encounter linked to a Challonge match, so a confirmation owes a push."""
    return patch(
        "src.services.encounter.settle.resolve_encounter_challonge",
        AsyncMock(side_effect=lambda _s, ids: dict.fromkeys(ids, 1)),
    )


class GameOpenLockOrderTests(ResultFlowCase):
    """Every game insert takes the room lock first (encounter, then game)."""

    async def blocked(self, pid: int) -> bool:
        async with self.Session() as s:
            return bool(await s.scalar(sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}))

    async def test_an_open_without_the_room_lock_waits_for_the_healer_and_takes_its_game(self) -> None:
        """The healer holds the room lock and opens position 1 while a caller that holds nothing opens it too. Without
        the lock first, the caller's insert holds the position's index entry while its foreign-key check waits on the
        healer, and the healer's insert waits on that entry: a deadlock."""
        async with self.Session() as healer, self.Session() as writer:
            encounter = await healer.scalar(sa.select(Encounter).where(Encounter.id == self.ids["e"]).with_for_update())
            writer_pid = await writer.scalar(sa.text("SELECT pg_backend_pid()"))

            async def open_unlocked() -> EncounterGame:
                unlocked = await writer.get_one(Encounter, self.ids["e"])
                return await encounter_game_service.open_game(writer, unlocked, position=1)

            opening = asyncio.create_task(open_unlocked())
            for _ in range(500):
                if await self.blocked(writer_pid):
                    break
                await asyncio.sleep(0.01)
            else:
                self.fail("the unlocked open never waited on the healer")
            opened = await encounter_game_service.open_game(healer, encounter, position=1)
            await healer.commit()
            taken = await asyncio.wait_for(opening, 10)
            await writer.commit()
        self.assertEqual(opened.id, taken.id)


class OutboxCase(ResultFlowCase):
    async def pushes(self) -> list[int]:
        """The result versions of every Challonge push staged for the encounter."""
        async with self.Session() as s:
            rows = await s.scalars(
                sa.select(EventOutbox.payload_json).where(
                    EventOutbox.event_id.startswith(f"challonge_push:{self.ids['e']}:")
                )
            )
            return [row["result_version"] for row in rows]

    async def completions(self) -> int:
        async with self.Session() as s:
            rows = await s.scalars(
                sa.select(EventOutbox.payload_json).where(EventOutbox.event_type == "encounter_completed")
            )
            return sum(row.get("encounter_id") == self.ids["e"] for row in rows)


class GameCorrectionPushTests(OutboxCase):
    async def test_a_correction_that_leaves_the_series_confirmed_pushes_its_new_version(self) -> None:
        """The correction reopens and re-confirms -- two version bumps -- so only a push of the NEW version reaches
        Challonge; one still queued for the old version is dropped as stale."""
        async with self.Session() as s:
            first, second = await self.seats(s)
            game = await self.play(s, 1, first.id, second.id)
            await self.play(s, 2, first.id, second.id)
        self.assertEqual([], await self.pushes())

        with _linked():
            async with self.Session() as s:
                await game_correction_service.correct_game(
                    s,
                    self.ids["e"],
                    game_id=game.id,
                    results=[
                        GameResultIn(encounter_team_id=first.id, score=2),
                        GameResultIn(encounter_team_id=second.id, score=0),
                    ],
                    actor_user_id=self.users[0],
                    reason="the first map's score was misread",
                    audit=AsyncMock(),
                )

        async with self.Session() as s:
            encounter = await self.encounter(s)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, encounter.result_status)
        self.assertEqual([encounter.result_version], await self.pushes())


class LobbyGamesCountTests(OutboxCase):
    slot_count = 3
    best_of = 2
    preset = "points"
    game_formula = "place_pts"
    end_formula = "games >= best_of"

    async def test_lowering_the_count_onto_the_played_games_settles_the_lobby(self) -> None:
        async with self.Session() as s:
            order = [seat.id for seat in await self.seats(s)]

        with (
            patch("src.services.encounter.settle.enqueue_tournament_recalculation", AsyncMock()) as settled,
            _linked(),
        ):
            async with self.Session() as s:
                await ffa_encounter_service.record_lobby_game(
                    s,
                    self.ids["e"],
                    1,
                    [GameResultIn(encounter_team_id=team, placement=place) for place, team in enumerate(order, 1)],
                    actor_user_id=self.users[0],
                    reason=None,
                )
            settled.assert_not_awaited()
            async with self.Session() as s:
                await ffa_encounter_service.set_games_count(s, self.ids["e"], 1, actor_user_id=self.users[0])

        settled.assert_awaited_once_with(ANY, self.ids["t"])
        async with self.Session() as s:
            encounter = await self.encounter(s)
        self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)
        self.assertEqual([encounter.result_version], await self.pushes())
        self.assertEqual(1, await self.completions())


class LobbyReopenTests(ResultFlowCase):
    """A finished one-game lobby whose first place feeds a final."""

    slot_count = 3
    best_of = 1
    preset = "points"
    game_formula = "place_pts"
    end_formula = "games >= best_of"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            # Places pay differently, so the lobby has one sole first place to advance.
            (await s.get_one(ScoringRule, self.ids["rule"])).placement_points = [10.0, 6.0, 3.0]
            final = Encounter(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="Final",
                slot_count=2,
                best_of=1,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(final)
            await s.flush()
            s.add(
                EncounterLink(
                    tournament_id=self.ids["t"],
                    source_encounter_id=self.ids["e"],
                    source_position=1,
                    target_encounter_id=final.id,
                    target_slot=1,
                )
            )
            await s.commit()
            self.ids["final"] = final.id

    async def seated_in_final(self) -> list[int | None]:
        async with self.Session() as s:
            return [seat.team_id for seat in await participants.active_teams(s, self.ids["final"])]

    async def finish(self) -> None:
        """Play the lobby's one game; its first place (team0) advances into the final."""
        async with self.Session() as s:
            order = [seat.id for seat in await self.seats(s)]
        async with self.Session() as s:
            await ffa_encounter_service.record_lobby_game(
                s,
                self.ids["e"],
                1,
                [GameResultIn(encounter_team_id=team, placement=place) for place, team in enumerate(order, 1)],
                actor_user_id=self.users[0],
                reason=None,
            )
        self.assertEqual([self.ids["team0"]], await self.seated_in_final())

    async def assert_unwound(self) -> None:
        async with self.Session() as s:
            self.assertNotEqual(enums.EncounterResultStatus.CONFIRMED, (await self.encounter(s)).result_status)
        self.assertEqual([], await self.seated_in_final())

    async def test_raising_the_count_of_a_finished_lobby_unwinds_what_it_advanced(self) -> None:
        await self.finish()
        async with self.Session() as s:
            await ffa_encounter_service.set_games_count(s, self.ids["e"], 2, actor_user_id=self.users[0])
        await self.assert_unwound()

    async def test_voiding_the_game_that_finished_a_lobby_unwinds_what_it_advanced(self) -> None:
        await self.finish()
        async with self.Session() as s:
            await ffa_encounter_service.cancel_game(
                s, self.ids["e"], 1, actor_user_id=self.users[0], reason="the lobby replays its game"
            )
        await self.assert_unwound()


class DuelIsNotALobbyTests(ResultFlowCase):
    """The seeded encounter is a ``wins`` duel."""

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(
                sa.delete(AuditLog).where(AuditLog.entity_type == "encounter", AuditLog.entity_id == self.ids["e"])
            )
            await s.commit()
        await super().asyncTearDown()

    async def test_the_lobby_read_refuses_a_duel(self) -> None:
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await ffa_encounter_service.load_lobby(s, self.ids["e"])
        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual(["ffa_not_a_lobby"], _codes(caught.exception))

    async def test_the_games_count_route_leaves_a_duels_best_of_alone(self) -> None:
        broker = CapturingBroker()
        ffa_rpc.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        data = {
            "identity": make_identity(user_id=self.users[0], is_superuser=True),
            "id": self.ids["e"],
            "payload": {"games": 5},
        }
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            envelope = await broker.handlers["rpc.tournament.ffa_games_count_set"](data, None)

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("conflict", envelope["error"]["code"], envelope)
        self.assertIn("ffa_not_a_lobby", str(envelope["error"]))
        async with self.Session() as s:
            self.assertEqual(self.best_of, (await self.encounter(s)).best_of)


class ChatReadLockTests(ResultFlowCase):
    async def test_a_spectator_reads_the_chat_while_a_writer_holds_the_room(self) -> None:
        """The history read takes no row lock: a spectator's poll must not queue behind a captain's write."""
        async with self.Session() as writer:
            await writer.execute(sa.select(Encounter.id).where(Encounter.id == self.ids["e"]).with_for_update())
            async with self.Session() as reader:
                # Fails fast, instead of hanging, if the read queues behind the writer's lock.
                await reader.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
                envelope = await encounter_chat_service.envelope(reader, None, ChatRoom.encounter(self.ids["e"]))
            await writer.rollback()
        self.assertEqual(SPECTATOR_ROLE, envelope.viewer.role)

    async def test_a_post_still_queues_behind_the_room_writer(self) -> None:
        """A write keeps the room lock: one account's posts queue, which the count-then-insert rate limit relies on.
        The lock is the resolver's first statement, so the timeout fires before anything else about the caller."""
        async with self.Session() as writer:
            await writer.execute(sa.select(Encounter.id).where(Encounter.id == self.ids["e"]).with_for_update())
            async with self.Session() as poster:
                await poster.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
                with self.assertRaises(sa.exc.DBAPIError):
                    await encounter_chat_service.post(poster, None, ChatRoom.encounter(self.ids["e"]), "hi")
            await writer.rollback()
