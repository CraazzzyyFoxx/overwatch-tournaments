"""The live pick-ban runtime: the cursor, the two ways a side answers a step,
and the self-healing every read performs.

Driven through the REAL services against ``tests/_pickban_room.Room`` -- the
v1 suite pinned pure helpers (``apply_pick_ban_action``,
``auto_complete_decider_entry``) that ruleset v2 replaced with
``shared.domain.pick_ban_rules``, which has its own unit suites. What is worth
pinning HERE is the service behaviour those helpers used to carry: a system
step resolving as soon as it becomes current, a timer expiring under each
``on_timeout`` policy, the turn/step refusals, and the state payload's blind
privacy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from shared.core.enums import MapVetoSessionStatus, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from tests._pickban_room import AWAY, HOME, Room, available_of, v1_ruleset  # noqa: E402

# One ban per side, then a decider: the shortest sequence with a system step.
BAN_BAN_DECIDER = v1_ruleset(kind="map", mode="pool", sequence=["ban_first", "ban_second", "decider"])
SEQUENTIAL_BANS = v1_ruleset(sequence=["ban_first", "ban_second"])


def blind_ruleset(*, count: int = 2, on_timeout: str = "random_fill", timer: int | None = 30) -> dict:
    """Both sides ban ``count`` heroes at once, privately."""
    return {
        "version": 2,
        "timer_seconds": timer,
        "on_timeout": on_timeout,
        "phases": [
            {
                "id": "main",
                "name": None,
                "when": {},
                "pool_filter": {},
                "generator": None,
                "steps": [
                    {
                        "id": "blind",
                        "action": "ban",
                        "actors": "both",
                        "count": count,
                        "min": None,
                        "blind": True,
                        "target": None,
                        "lifetime": 1,
                        "timer_seconds": None,
                        "on_timeout": None,
                        "dispute": {"enabled": True, "max": 1},
                        "eligible": {},
                        "constraints": [],
                    }
                ],
            }
        ],
    }


async def expire(room: Room, kind: PickBanKind = PickBanKind.HERO) -> None:
    """Open the room if it is not open yet, then wind the step's clock back
    past its deadline."""
    await room.open(kind)
    room.session(kind).current_step_started_at = datetime.now(UTC) - timedelta(hours=1)


class SystemStepTests(IsolatedAsyncioTestCase):
    """A ``system`` step resolves itself the moment it becomes current -- the
    v1 ``decider`` auto-complete, now just another step of the sequence.

    Map kind only: a hero round leaves the unbanned pool playable, so
    ``resolve_round`` drops a decider a legacy hero config still carries."""

    def _room(self, items: list[int]) -> Room:
        return Room(map_ruleset=BAN_BAN_DECIDER, map_items=items)

    async def act(self, room: Room, side: str, item_id: int) -> dict:
        return await room.act(side, item_id, kind=PickBanKind.MAP)

    async def test_the_decider_awards_the_survivor_as_soon_as_the_bans_are_in(self) -> None:
        room = self._room([11, 12, 13])
        await self.act(room, HOME, 11)
        state = await self.act(room, AWAY, 12)

        self.assertTrue(state["is_complete"])
        picked = [entry for entry in state["pool"] if entry["status"] == "picked"]
        self.assertEqual([(13, "decider", 1)], [(e["item_id"], e["picked_by"], e["order"]) for e in picked])
        self.assertEqual(MapVetoSessionStatus.COMPLETED, room.session(PickBanKind.MAP).status)

    async def test_it_does_not_fire_before_its_turn(self) -> None:
        room = self._room([11, 12, 13])
        state = await self.act(room, HOME, 11)

        self.assertFalse(state["is_complete"])
        self.assertEqual([], [entry for entry in state["pool"] if entry["status"] == "picked"])
        self.assertEqual(1, state["current_step_index"])

    async def test_it_picks_among_every_survivor_rather_than_stalling_on_an_oversized_pool(self) -> None:
        """A pool oversized for its sequence (a config mistake, not a captain's)
        reaches the decider with several survivors. Resolving one at random
        beats freezing the room on a step nobody can take -- and across enough
        draws every survivor gets a turn."""
        chosen: set[int] = set()
        for _ in range(40):
            room = self._room([11, 12, 13, 14, 15])
            await self.act(room, HOME, 11)
            state = await self.act(room, AWAY, 12)
            picked = [entry for entry in state["pool"] if entry["status"] == "picked"]
            self.assertEqual(1, len(picked), "a decider settles exactly one item")
            chosen.add(picked[0]["item_id"])
        self.assertEqual({13, 14, 15}, chosen)


class TurnAndStepRefusalTests(IsolatedAsyncioTestCase):
    async def test_the_wrong_side_is_refused(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])

        with self.assertRaises(HTTPException) as caught:
            await room.act(AWAY, 1)

        self.assertEqual(400, caught.exception.status_code)
        self.assertIn("home team's turn", caught.exception.detail)

    async def test_the_wrong_action_is_refused(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])

        with self.assertRaises(HTTPException) as caught:
            await room.act(HOME, 1, action="pick")

        self.assertEqual("Expected action 'ban', got 'pick'", caught.exception.detail)

    async def test_an_exhausted_sequence_is_refused(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])
        await room.act(HOME, 1)
        await room.act(AWAY, 2)

        with self.assertRaises(HTTPException) as caught:
            await room.act(HOME, 3)

        self.assertEqual("Pick-ban sequence is already complete", caught.exception.detail)

    async def test_an_already_banned_item_is_refused_by_code(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])
        await room.act(HOME, 1)

        with self.assertRaises(HTTPException) as caught:
            await room.act(AWAY, 1)

        self.assertEqual("item_not_available", caught.exception.detail)

    async def test_a_blind_step_refuses_act_and_an_open_step_refuses_submit(self) -> None:
        blind = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4])
        with self.assertRaises(HTTPException) as caught:
            await blind.act(HOME, 1)
        self.assertIn("submit the whole draft", caught.exception.detail)

        open_room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])
        with self.assertRaises(HTTPException) as caught:
            await open_room.submit(HOME, [1])
        self.assertIn("one item at a time", caught.exception.detail)


class BlindStepTests(IsolatedAsyncioTestCase):
    async def test_the_opponent_sees_progress_but_never_the_draft(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4, 5, 6])
        await room.submit(HOME, [1, 2], lock=True)

        opponent = await room.state(viewer=AWAY)

        self.assertEqual(
            {"home": {"locked": True, "filled": 2}, "away": {"locked": False, "filled": 0}}, opponent["step_progress"]
        )
        self.assertEqual([], opponent["submissions"], "an unrevealed blind draft is never serialized")
        self.assertEqual(["home"], [side for side in ("home", "away") if side not in opponent["acting_sides"]])
        self.assertEqual([], [entry for entry in opponent["pool"] if entry["status"] != "available"])

    async def test_both_locks_reveal_and_project_the_board(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4, 5, 6])
        await room.submit(HOME, [1, 2], lock=True)
        state = await room.submit(AWAY, [3, 4], lock=True)

        self.assertTrue(state["is_complete"])
        self.assertEqual(
            {(1, "home"), (2, "home"), (3, "away"), (4, "away")},
            {(entry["item_id"], entry["picked_by"]) for entry in state["pool"] if entry["status"] == "banned"},
        )
        self.assertEqual({"revealed"}, {row["state"] for row in state["submissions"]})

    async def test_a_duplicate_ban_is_merged_into_one_banned_entry(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4, 5, 6])
        await room.submit(HOME, [1, 2], lock=True)
        state = await room.submit(AWAY, [2, 3], lock=True)

        banned = [entry for entry in state["pool"] if entry["status"] == "banned"]
        self.assertEqual({1, 2, 3}, {entry["item_id"] for entry in banned})
        self.assertEqual("home", next(e["picked_by"] for e in banned if e["item_id"] == 2), "first side wins")
        # Both submissions still list it: the merge is on the BOARD, not the log.
        self.assertEqual(
            {("home", (1, 2)), ("away", (2, 3))},
            {(row["side"], tuple(item["item_id"] for item in row["items"])) for row in state["submissions"]},
        )

    async def test_an_unlocked_draft_is_visible_to_its_own_side_only(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4])
        await room.submit(HOME, [1], lock=False)

        own = await room.state(viewer=HOME)
        self.assertEqual(
            [("home", "draft", [1])],
            [(r["side"], r["state"], [i["item_id"] for i in r["items"]]) for r in own["submissions"]],
        )
        self.assertEqual(["not_enough_items"], own["draft_issues"], "a short draft names why it cannot lock")

        self.assertEqual([], (await room.state(viewer=AWAY))["submissions"])

    async def test_locking_a_short_draft_is_refused_with_the_engine_code(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4])

        with self.assertRaises(HTTPException) as caught:
            await room.submit(HOME, [1], lock=True)

        self.assertEqual("not_enough_items", caught.exception.detail)


class TimeoutTests(IsolatedAsyncioTestCase):
    async def test_random_fill_completes_the_draft_and_reveals(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4, 5, 6])
        await room.submit(HOME, [1], lock=False)
        await expire(room)

        state = await room.state()

        self.assertTrue(state["is_complete"])
        self.assertEqual(
            [2, 2],
            [len(row["items"]) for row in sorted(state["submissions"], key=lambda row: row["side"])],
            "both sides end with a full draft",
        )
        banned = {entry["item_id"] for entry in state["pool"] if entry["status"] == "banned"}
        # 2 to 4 distinct entries: the board merges a hero both sides filled
        # (D8), and a blind fill does not see the other side's draft, so the
        # away side may even land on exactly the home pair.
        self.assertIn(len(banned), (2, 3, 4))
        self.assertIn(1, banned, "the draft the captain HAD is kept, not replaced")

    async def test_lock_draft_seals_what_was_there_and_ignores_min(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(on_timeout="lock_draft"), hero_items=[1, 2, 3, 4, 5, 6])
        await room.submit(HOME, [1], lock=False)
        await expire(room)

        state = await room.state()

        self.assertTrue(state["is_complete"])
        self.assertEqual({1}, {entry["item_id"] for entry in state["pool"] if entry["status"] == "banned"})

    async def test_wait_leaves_the_step_open_for_an_organizer(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(on_timeout="wait"), hero_items=[1, 2, 3, 4])
        await room.submit(HOME, [1], lock=False)
        await expire(room)

        state = await room.state()

        self.assertFalse(state["is_complete"])
        self.assertEqual(["away", "home"], sorted(state["acting_sides"]))

    async def test_a_timer_less_step_never_expires(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(timer=None), hero_items=[1, 2, 3, 4])
        await expire(room)

        state = await room.state()

        self.assertFalse(state["is_complete"])
        self.assertIsNone(state["step_deadline"])

    async def test_an_open_step_is_auto_banned_for_the_side_that_never_answered(self) -> None:
        room = Room(
            hero_ruleset=v1_ruleset(sequence=["ban_first", "ban_second"], turn_timer_seconds=30),
            hero_items=[1, 2, 3],
        )
        await expire(room)

        state = await room.state()

        # The first step resolved at random; the SECOND is now on the clock with
        # a fresh deadline, not carrying the expired one.
        self.assertEqual(1, state["current_step_index"])
        self.assertEqual(1, len([entry for entry in state["pool"] if entry["status"] == "banned"]))
        self.assertIsNotNone(state["step_deadline"])
        # The very next read must NOT burn the new step on the old clock.
        again = await room.state()
        self.assertEqual(1, again["current_step_index"])
        self.assertEqual(1, len([entry for entry in again["pool"] if entry["status"] == "banned"]))

    async def test_only_the_step_that_was_on_the_clock_expires(self) -> None:
        """The deadline belongs to ONE step. Cascading it would burn a whole
        sequence on a single stale read."""
        room = Room(
            hero_ruleset=v1_ruleset(sequence=["ban_first", "ban_second", "ban_first"], turn_timer_seconds=30),
            hero_items=[1, 2, 3, 4, 5],
        )
        await expire(room)

        state = await room.state()

        self.assertEqual(1, len([entry for entry in state["pool"] if entry["status"] == "banned"]))


class StatePayloadTests(IsolatedAsyncioTestCase):
    async def test_the_payload_carries_what_the_room_renders(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])

        state = await room.state(viewer=HOME)

        self.assertEqual(["home"], state["acting_sides"])
        self.assertTrue(state["viewer_can_act"])
        self.assertEqual(["ban"], state["allowed_actions"])
        self.assertEqual("ban", state["expected_action"])
        self.assertEqual({"item_ids": [1, 2, 3], "by_target": None}, state["eligible"])
        self.assertIsNone(state["targets"], "no resolved step names a player")
        self.assertEqual({"available": False, "step_index": None, "attempts_used": 0, "max": 0}, state["dispute"])
        self.assertNotIn("turn_timer_seconds", state["session"])
        self.assertEqual([None, None, None], [entry["carried_from_round"] for entry in state["pool"]])

    async def test_a_spectator_may_not_act_and_gets_no_eligibility(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])

        state = await room.state(viewer=None)

        self.assertFalse(state["viewer_can_act"])
        self.assertIsNone(state["eligible"])
        self.assertEqual([], state["draft_issues"])

    async def test_the_side_that_is_not_on_the_clock_cannot_act(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])

        state = await room.state(viewer=AWAY)

        self.assertFalse(state["viewer_can_act"])
        self.assertEqual([], state["allowed_actions"])
        self.assertIsNone(state["eligible"])

    async def test_an_unconfigured_room_still_answers_the_full_shape(self) -> None:
        room = Room()  # no config at all

        state = await room.state()

        self.assertIsNone(state["session"])
        self.assertEqual("not_configured", state["reason"])
        for key in ("sequence", "pool", "submissions", "acting_sides", "draft_issues", "allowed_actions"):
            self.assertEqual([], state[key], key)
        for key in ("step_progress", "step_deadline", "eligible", "targets", "current_step"):
            self.assertIsNone(state[key], key)
        self.assertEqual(
            {"requested_by": None, "step_index": None, "item_ids": [], "action": None, "side": None}, state["undo"]
        )


class AdminReopenTests(IsolatedAsyncioTestCase):
    async def test_it_reopens_the_last_settled_step_with_the_drafts_prefilled(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4, 5, 6])
        await room.submit(HOME, [1, 2], lock=True)
        await room.submit(AWAY, [3, 4], lock=True)

        state = await room.admin_reopen()

        self.assertFalse(state["is_complete"])
        self.assertEqual(0, state["current_step_index"])
        self.assertEqual([], [entry for entry in state["pool"] if entry["status"] != "available"])
        home = await room.state(viewer=HOME)
        self.assertEqual(
            [("home", "draft", [1, 2])],
            [(r["side"], r["state"], [i["item_id"] for i in r["items"]]) for r in home["submissions"]],
        )

    async def test_it_is_refused_when_nothing_has_settled(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4])

        with self.assertRaises(HTTPException) as caught:
            await room.admin_reopen()

        self.assertEqual("There is no settled step to reopen", caught.exception.detail)

    async def test_it_ignores_the_attempt_limit_a_dispute_respects(self) -> None:
        room = Room(hero_ruleset=blind_ruleset(), hero_items=[1, 2, 3, 4, 5, 6])
        for _ in range(3):
            await room.submit(HOME, [1, 2], lock=True)
            await room.submit(AWAY, [3, 4], lock=True)
            await room.admin_reopen()

        # Three reopens past a `dispute.max` of 1: only the live attempt 4 is
        # answerable, and the three it replaced are voided history.
        self.assertEqual(4, max(row.attempt for row in room.submissions()))
        live = [row for row in room.submissions() if row.attempt == 4]
        self.assertEqual({"draft"}, {row.state for row in live})
        self.assertEqual({"voided"}, {row.state for row in room.submissions() if row.attempt < 4})
        with self.assertRaises(HTTPException) as caught:
            await room.dispute(HOME)
        self.assertEqual("This step cannot be reopened", caught.exception.detail)


class AvailabilityHelperTests(IsolatedAsyncioTestCase):
    async def test_available_of_tracks_the_round_in_play(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])
        state = await room.state()
        self.assertEqual([1, 2, 3], available_of(state))

        state = await room.act(HOME, 2)
        self.assertEqual([1, 3], available_of(state))


class CancelledSessionTests(IsolatedAsyncioTestCase):
    async def test_a_cancelled_session_refuses_every_mutation(self) -> None:
        room = Room(hero_ruleset=SEQUENTIAL_BANS, hero_items=[1, 2, 3])
        await room.state()
        room.session().status = MapVetoSessionStatus.CANCELLED

        for call in (
            lambda: room.act(HOME, 1),
            lambda: room.submit(HOME, [1]),
            lambda: room.dispute(HOME),
            lambda: pick_ban_action_service.admin_reopen_step(room.store, room.encounter_id, PickBanKind.HERO),
        ):
            with self.assertRaises(HTTPException) as caught:
                await call()
            self.assertEqual("Pick-ban session is cancelled", caught.exception.detail)
