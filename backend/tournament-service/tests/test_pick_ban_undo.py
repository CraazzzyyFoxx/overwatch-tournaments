"""Undoing the last pick-ban step: the two-sided consent, what it reverts, and
the two map guards that refuse it outright.

``PickBanEntry`` is a projection now, so an undo is not "put these rows back":
it VOIDS the step's live submissions (and every later one) and re-projects.
These tests drive the real service against ``tests/_pickban_room.Room`` so the
projection is what they read back.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from shared.core.enums import MapPickSide, MapVetoSessionStatus, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.services.encounter import pick_ban_undo  # noqa: E402
from tests._pickban_room import AWAY, HOME, Room, v1_ruleset  # noqa: E402

TWO_BANS = v1_ruleset(sequence=["ban_first", "ban_second"])
BAN_THEN_DECIDER = v1_ruleset(kind="map", mode="pool", sequence=["ban_first", "decider"])


def _room() -> Room:
    return Room(hero_ruleset=TWO_BANS, hero_items=[101, 102, 103])


class UndoStateTests(IsolatedAsyncioTestCase):
    async def test_reports_nothing_undoable_on_a_fresh_room(self) -> None:
        state = await _room().state()

        self.assertEqual(
            {"requested_by": None, "step_index": None, "item_ids": [], "action": None, "side": None},
            state["undo"],
        )

    async def test_names_the_last_step_and_who_asked(self) -> None:
        room = _room()
        state = await room.act(HOME, 101)

        self.assertEqual(
            {"requested_by": None, "step_index": 0, "item_ids": [101], "action": "ban", "side": "home"},
            state["undo"],
        )

        await room.undo(HOME)
        self.assertEqual("home", (await room.state())["undo"]["requested_by"])

    async def test_a_request_against_a_superseded_step_reads_as_no_request(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)
        state = await room.act(AWAY, 102)

        self.assertEqual(1, state["undo"]["step_index"])
        self.assertIsNone(state["undo"]["requested_by"], "the consent was given against step 0")

    async def test_it_lists_the_system_step_it_would_revert_alongside_the_action(self) -> None:
        room = Room(map_ruleset=BAN_THEN_DECIDER, map_items=[11, 12, 13])
        state = await room.act(HOME, 11, kind=PickBanKind.MAP)

        # The decider is not an action anybody took -- the engine resolved it
        # off the back of the ban, so it is reverted together with it.
        self.assertEqual(0, state["undo"]["step_index"])
        self.assertEqual("ban", state["undo"]["action"])
        self.assertEqual({11}, {state["undo"]["item_ids"][0]})
        self.assertEqual(2, len(state["undo"]["item_ids"]), "the ban plus the map the decider awarded")

    async def test_a_multi_side_step_names_no_single_side(self) -> None:
        room = Room(
            hero_ruleset={
                "version": 2,
                "timer_seconds": None,
                "on_timeout": "wait",
                "phases": [
                    {
                        "id": "main",
                        "name": None,
                        "when": {},
                        "pool_filter": {},
                        "generator": None,
                        "steps": [
                            {
                                "id": "both",
                                "action": "ban",
                                "actors": "both",
                                "count": 1,
                                "min": None,
                                "blind": False,
                                "target": None,
                                "lifetime": 1,
                                "timer_seconds": None,
                                "on_timeout": None,
                                "dispute": {"enabled": False, "max": 0},
                                "eligible": {},
                                "constraints": [],
                            }
                        ],
                    }
                ],
            },
            hero_items=[101, 102, 103],
        )
        await room.act(HOME, 101)
        state = await room.act(AWAY, 102)

        self.assertEqual(0, state["undo"]["step_index"])
        self.assertIsNone(state["undo"]["side"])
        self.assertEqual([101, 102], state["undo"]["item_ids"])


class PerformUndoTests(IsolatedAsyncioTestCase):
    async def test_the_first_call_only_records_the_request(self) -> None:
        room = _room()
        await room.act(HOME, 101)

        undo = await room.undo(HOME)

        self.assertEqual("home", undo["requested_by"])
        self.assertEqual([101], undo["item_ids"])
        state = await room.state()
        self.assertEqual("banned", next(e["status"] for e in state["pool"] if e["item_id"] == 101))

    async def test_the_same_side_asking_twice_changes_nothing(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)

        await room.undo(HOME)

        self.assertEqual("banned", next(e["status"] for e in (await room.state())["pool"] if e["item_id"] == 101))

    async def test_the_opponent_agreeing_applies_the_undo(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)

        undo = await room.undo(AWAY)

        self.assertEqual({"requested_by": None, "step_index": None, "item_ids": [], "action": None, "side": None}, undo)
        state = await room.state()
        self.assertEqual([], [e for e in state["pool"] if e["status"] != "available"])
        self.assertEqual(0, state["current_step_index"], "the step it reopened is on the clock again")
        self.assertEqual(MapVetoSessionStatus.ACTIVE, room.session().status)

    async def test_the_reopened_step_can_be_answered_again(self) -> None:
        """The voided attempt must not collide with the answer replacing it --
        ``(session, step, side, attempt)`` is unique."""
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)
        await room.undo(AWAY)

        state = await room.act(HOME, 102)

        self.assertEqual("banned", next(e["status"] for e in state["pool"] if e["item_id"] == 102))
        self.assertEqual("available", next(e["status"] for e in state["pool"] if e["item_id"] == 101))
        self.assertEqual(1, state["current_step_index"])
        # The replacement goes onto attempt 2: reusing the voided attempt's
        # number collides with the row it voided on
        # `uq_pick_ban_submission_step_side_attempt`.
        step_zero = [row for row in room.submissions() if row.step_index == 0]
        self.assertEqual({(1, "voided"), (2, "revealed")}, {(row.attempt, row.state) for row in step_zero})

    async def test_withdrawing_clears_the_request_without_reverting(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)

        undo = await room.undo(HOME, consent=False)

        self.assertIsNone(undo["requested_by"])
        self.assertEqual([101], undo["item_ids"], "the step is still undoable, just unrequested")
        self.assertEqual("banned", next(e["status"] for e in (await room.state())["pool"] if e["item_id"] == 101))

    async def test_declining_from_the_other_side_clears_it_too(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)

        undo = await room.undo(AWAY, consent=False)

        self.assertIsNone(undo["requested_by"])
        self.assertEqual("banned", next(e["status"] for e in (await room.state())["pool"] if e["item_id"] == 101))

    async def test_a_stale_request_is_replaced_rather_than_applied(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)
        await room.act(AWAY, 102)  # a new step supersedes the consent

        undo = await room.undo(AWAY)

        self.assertEqual("away", undo["requested_by"], "away opened a FRESH request against step 1")
        self.assertEqual("banned", next(e["status"] for e in (await room.state())["pool"] if e["item_id"] == 102))

    async def test_nothing_to_undo_is_a_400(self) -> None:
        room = _room()

        with self.assertRaises(HTTPException) as caught:
            await room.undo(HOME)

        self.assertEqual(400, caught.exception.status_code)
        self.assertEqual("There is no action left to undo", caught.exception.detail)


class MapUndoGuardTests(IsolatedAsyncioTestCase):
    """Two things a map undo must never quietly destroy: hero bans made for the
    map it takes back, and a result claim standing on the position it opened."""

    async def _played_map_one(self) -> Room:
        room = Room(hero_ruleset=TWO_BANS, hero_items=[1, 2, 3], with_map_veto=True)
        await room.ban_out_the_map_round()
        return room

    async def test_it_waits_on_this_rounds_hero_bans(self) -> None:
        room = await self._played_map_one()
        await room.act(HOME, 1)  # a hero ban for map 1

        with self.assertRaises(HTTPException) as caught:
            await room.undo(HOME, kind=PickBanKind.MAP)

        self.assertEqual(400, caught.exception.status_code)
        self.assertIn("hero bans first", caught.exception.detail)

    async def test_it_goes_through_once_no_hero_ban_stands(self) -> None:
        room = await self._played_map_one()

        await room.undo(HOME, kind=PickBanKind.MAP)
        undo = await room.undo(AWAY, kind=PickBanKind.MAP)

        # Away's ban AND the decider that resolved off it are gone; home's
        # opening ban stands, and is now what an undo would reach next.
        self.assertEqual({"step_index": 0, "item_ids": [11]}, {k: undo[k] for k in ("step_index", "item_ids")})
        state = await room.state(PickBanKind.MAP)
        self.assertEqual([], [e for e in state["pool"] if e["status"] == "picked"])
        self.assertEqual([11], [e["item_id"] for e in state["pool"] if e["status"] == "banned"])

    async def test_it_is_refused_once_the_game_has_a_claim(self) -> None:
        room = await self._played_map_one()
        state = await room.state(PickBanKind.MAP)
        game_id = next(game["id"] for game in state["games"] if game["position"] == 1)
        from src.services.encounter.map_report import map_report_service

        await map_report_service.submit_map_report(
            room.store,
            room.encounter,
            game_id=game_id,
            side=MapPickSide.HOME.value,
            reporter_user_id=None,
            home_score=2,
            away_score=1,
        )

        with self.assertRaises(HTTPException) as caught:
            await room.undo(HOME, kind=PickBanKind.MAP)

        self.assertEqual(400, caught.exception.status_code)
        self.assertIn("result claim", caught.exception.detail)


class ClearUndoRequestTests(IsolatedAsyncioTestCase):
    async def test_a_new_action_drops_an_open_request(self) -> None:
        room = _room()
        await room.act(HOME, 101)
        await room.undo(HOME)

        await room.act(AWAY, 102)

        session = room.session()
        self.assertIsNone(session.undo_requested_by)
        self.assertIsNone(session.undo_target_index)

    def test_clear_undo_request_is_idempotent(self) -> None:
        session = type("S", (), {"undo_requested_by": "home", "undo_target_index": 3})()
        pick_ban_undo.clear_undo_request(session)
        pick_ban_undo.clear_undo_request(session)
        self.assertEqual((None, None), (session.undo_requested_by, session.undo_target_index))
