"""The organizer's emergency controls over a live room: pause, extend, cancel,
technical loss.

Driven through the REAL services against ``tests/_pickban_room.Room``. What is
worth pinning here is what each control does to the ENGINE -- a frozen clock
that genuinely refuses to expire, a resume that gives back the time the step had
left rather than restarting it, a cancelled map session that hands the series to
freeplay -- plus the forfeit score rule, which is pure arithmetic and tested as
such.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.core.enums import EncounterGameState, MapVetoSessionStatus, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from src.services.encounter import room_control  # noqa: E402
from src.services.encounter.games import encounter_game_service  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from tests._pickban_room import AWAY, HOME, Room, v1_ruleset  # noqa: E402

TIMED_BANS = v1_ruleset(sequence=["ban_first", "ban_second"], turn_timer_seconds=30)
UNTIMED_BANS = v1_ruleset(sequence=["ban_first", "ban_second"])

ADMIN = 99  # the auth user id every control here is journaled against


async def _pause(room: Room, *, paused: bool, kind: PickBanKind = PickBanKind.HERO) -> dict:
    return await room_control.set_paused(room.store, room.encounter_id, kind, paused=paused, actor_auth_user_id=ADMIN)


class PauseTests(IsolatedAsyncioTestCase):
    async def _room(self) -> Room:
        room = Room(hero_ruleset=TIMED_BANS, hero_items=[1, 2, 3, 4])
        await room.open()
        return room

    async def test_a_paused_step_does_not_time_out_however_long_the_clock_says(self) -> None:
        room = await self._room()
        await _pause(room, paused=True)
        # Long past the 30s timer: unpaused, the next read would force-lock it.
        room.session().current_step_started_at = datetime.now(UTC) - timedelta(hours=1)

        state = await room.state()

        self.assertIsNone(state["step_deadline"], "a paused room shows no countdown")
        self.assertEqual(0, state["current_step_index"], "the expired step is still the open one")
        self.assertEqual([], room.submissions(), "nothing was force-locked")
        self.assertFalse(state["viewer_can_act"])

    async def test_a_captain_write_is_refused_while_an_admin_override_still_lands(self) -> None:
        room = await self._room()
        await _pause(room, paused=True)

        with self.assertRaises(HTTPException) as refused:
            await room.act(HOME, 1)
        self.assertEqual(409, refused.exception.status_code)
        self.assertIn("paused", str(refused.exception.detail))

        await pick_ban_action_service.perform_pick_ban_action(
            room.store, room.encounter_id, PickBanKind.HERO, HOME, item_id=1, action="ban", viewer_side=None
        )
        self.assertEqual([(0, HOME)], [(row.step_index, row.side) for row in room.submissions()])

    async def test_resuming_hands_the_step_back_the_time_it_had_left(self) -> None:
        room = await self._room()
        now = datetime.now(UTC)
        pick_ban = room.session()
        # 20s of a 30s timer were spent before the room was frozen for a minute.
        pick_ban.current_step_started_at = now - timedelta(seconds=80)
        await _pause(room, paused=True)
        pick_ban.paused_at = now - timedelta(seconds=60)

        state = await _pause(room, paused=False)

        self.assertIsNone(room.session().paused_at)
        left = datetime.fromisoformat(state["step_deadline"]) - datetime.now(UTC)
        self.assertAlmostEqual(10, left.total_seconds(), delta=2)

    async def test_a_step_an_organizer_opens_during_the_pause_resumes_with_its_full_timer(self) -> None:
        room = await self._room()
        await _pause(room, paused=True)
        room.session().paused_at = datetime.now(UTC) - timedelta(seconds=60)

        # The organizer bans for home while frozen: the board moves on to away's
        # step, whose clock starts at the pause's beginning, not at "now".
        state = await pick_ban_action_service.perform_pick_ban_action(
            room.store, room.encounter_id, PickBanKind.HERO, HOME, item_id=1, action="ban", viewer_side=None
        )
        self.assertEqual(1, state["current_step_index"], "a paused board still settles")
        self.assertIsNone(state["step_deadline"])

        state = await _pause(room, paused=False)

        left = datetime.fromisoformat(state["step_deadline"]) - datetime.now(UTC)
        self.assertAlmostEqual(30, left.total_seconds(), delta=2)

    async def test_an_extension_granted_while_paused_survives_the_resume(self) -> None:
        room = await self._room()
        pick_ban = room.session()
        # 20s of a 30s timer spent, then frozen for a minute and extended by 60s.
        now = datetime.now(UTC)
        pick_ban.current_step_started_at = now - timedelta(seconds=80)
        await _pause(room, paused=True)
        pick_ban.paused_at = now - timedelta(seconds=60)
        await room_control.extend_step_timer(
            room.store, room.encounter_id, PickBanKind.HERO, seconds=60, actor_auth_user_id=ADMIN
        )

        state = await _pause(room, paused=False)

        left = datetime.fromisoformat(state["step_deadline"]) - datetime.now(UTC)
        self.assertAlmostEqual(70, left.total_seconds(), delta=2)

    async def test_pausing_twice_changes_nothing(self) -> None:
        room = await self._room()
        await _pause(room, paused=True)
        paused_at = room.session().paused_at

        await _pause(room, paused=True)

        self.assertEqual(paused_at, room.session().paused_at)


class ExtendTests(IsolatedAsyncioTestCase):
    async def test_extending_moves_the_deadline_by_exactly_the_seconds_given(self) -> None:
        room = Room(hero_ruleset=TIMED_BANS, hero_items=[1, 2, 3, 4])
        before = datetime.fromisoformat((await room.open())["step_deadline"])

        state = await room_control.extend_step_timer(
            room.store, room.encounter_id, PickBanKind.HERO, seconds=60, actor_auth_user_id=ADMIN
        )

        after = datetime.fromisoformat(state["step_deadline"])
        self.assertAlmostEqual(60, (after - before).total_seconds(), delta=1)

    async def test_an_untimed_step_has_nothing_to_extend(self) -> None:
        room = Room(hero_ruleset=UNTIMED_BANS, hero_items=[1, 2, 3, 4])
        await room.open()

        with self.assertRaises(HTTPException) as refused:
            await room_control.extend_step_timer(
                room.store, room.encounter_id, PickBanKind.HERO, seconds=60, actor_auth_user_id=ADMIN
            )

        self.assertEqual(409, refused.exception.status_code)


class CancelTests(IsolatedAsyncioTestCase):
    async def test_a_cancelled_map_session_hands_the_rest_of_the_series_to_freeplay(self) -> None:
        room = Room(with_map_veto=True)
        picked = await room.ban_out_the_map_round()
        await room.state(PickBanKind.MAP)

        await room_control.cancel_session(
            room.store, room.encounter_id, PickBanKind.MAP, reason="pool is unplayable", actor_auth_user_id=ADMIN
        )
        # Position 1 is played out, which is what opens the next one.
        await room.report(1, 2, 1)
        state = await room.state(PickBanKind.MAP)

        self.assertEqual(MapVetoSessionStatus.CANCELLED, str(room.session(PickBanKind.MAP).status))
        self.assertEqual(
            [(1, picked, "confirmed"), (2, None, "planned")],
            [(game["position"], game["map_id"], game["state"]) for game in state["games"]],
        )
        # ...and the captains may name that position's map themselves.
        game = next(row for row in room.store.all_of(EncounterGame) if row.position == 2)
        await encounter_game_service.select_map(room.store, room.encounter, game, map_id=31)
        self.assertEqual(31, game.map_id)

    async def test_cancelling_twice_is_refused(self) -> None:
        room = Room(hero_ruleset=UNTIMED_BANS, hero_items=[1, 2, 3, 4])
        await room.open()
        await room_control.cancel_session(
            room.store, room.encounter_id, PickBanKind.HERO, reason="abandoned", actor_auth_user_id=ADMIN
        )

        with self.assertRaises(HTTPException) as refused:
            await room_control.cancel_session(
                room.store, room.encounter_id, PickBanKind.HERO, reason="again", actor_auth_user_id=ADMIN
            )

        self.assertEqual(409, refused.exception.status_code)


class DefaultTechnicalScoreTests(IsolatedAsyncioTestCase):
    def test_an_unplayed_bo3_is_a_clean_sweep(self) -> None:
        self.assertEqual(
            (2, 0), room_control.default_technical_score(best_of=3, loser_side="away", home_wins=0, away_wins=0)
        )

    def test_a_bo3_at_one_all_only_needs_the_decider(self) -> None:
        self.assertEqual(
            (2, 1), room_control.default_technical_score(best_of=3, loser_side="away", home_wins=1, away_wins=1)
        )

    def test_a_forfeiting_side_keeps_the_maps_it_won_but_not_the_series(self) -> None:
        # Bo5 standing 2:0 for the side that then forfeits.
        self.assertEqual(
            (2, 3), room_control.default_technical_score(best_of=5, loser_side="home", home_wins=2, away_wins=0)
        )

    def test_a_winner_already_past_the_line_keeps_its_own_count(self) -> None:
        self.assertEqual(
            (3, 0), room_control.default_technical_score(best_of=3, loser_side="away", home_wins=3, away_wins=0)
        )


class TechnicalLossTests(IsolatedAsyncioTestCase):
    async def test_it_cancels_the_room_keeps_the_played_map_and_confirms_the_result(self) -> None:
        room = Room(with_map_veto=True)
        await room.ban_out_the_map_round()
        await room.state(PickBanKind.MAP)
        await room.report(1, 2, 1)  # home takes position 1
        await room.ban_out_the_map_round()  # round 2 settles, opening position 2
        await room.state(PickBanKind.MAP)
        # The result write is its own tested transaction (finalize, audit,
        # bracket advance); what is pinned here is what this command hands it.
        confirm = AsyncMock(return_value=room.encounter)

        with patch.object(room_control.captain_service, "set_encounter_result", confirm):
            await room_control.technical_loss(
                room.store,
                room.encounter,
                loser_side=AWAY,
                home_score=None,
                away_score=None,
                reason="no-show",
                actor_auth_user_id=ADMIN,
                actor_player_id=None,
            )

        self.assertEqual(MapVetoSessionStatus.CANCELLED, str(room.session(PickBanKind.MAP).status))
        self.assertEqual(
            {(1, EncounterGameState.CONFIRMED), (2, EncounterGameState.CANCELLED)},
            {(game.position, game.state) for game in room.store.all_of(EncounterGame)},
        )
        self.assertEqual(2, confirm.await_args.kwargs["home_score"])
        self.assertEqual(0, confirm.await_args.kwargs["away_score"])

    async def test_an_explicit_score_must_put_the_forfeiting_side_below(self) -> None:
        room = Room(with_map_veto=True)
        await room.state(PickBanKind.MAP)

        with self.assertRaises(HTTPException) as refused:
            await room_control.technical_loss(
                room.store,
                room.encounter,
                loser_side=AWAY,
                home_score=0,
                away_score=2,
                reason="typo",
                actor_auth_user_id=ADMIN,
                actor_player_id=None,
            )

        self.assertEqual(422, refused.exception.status_code)
