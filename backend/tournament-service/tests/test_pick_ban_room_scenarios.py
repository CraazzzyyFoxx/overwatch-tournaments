"""The three rulebooks the 2026-10-03 tournament actually runs, end to end.

Not unit tests: each class plays a whole room through the real services against
``tests/_pickban_room.Room``, because the risk this wave carries is not "does a
function return X" but "does a MIGRATED v1 config still behave exactly as
before, and does the new blind/per-player rulebook hold up over three maps".

1. :class:`MigratedV1HeroConfigTests` — the sequential hero bans every existing
   tournament is on (``ban_first``/``ban_second`` + a turn timer).
2. :class:`SlotVetoSeriesTests` — the Bo3 loop: map veto, hero round, report.
3. :class:`AntiOneTrickTests` — the ``hero_anti_one_trick`` preset (design §12):
   a blind 2+2 on map 1, per-opponent-player 5+5 from map 2, two-map lifetimes,
   and the dispute that reopens a step both sides replay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from shared.core.enums import MapPoolEntryStatus, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain import pick_ban_rules as pbr  # noqa: E402
from tests._pickban_room import AWAY, HOME, Room, available_of, banned_of, v1_ruleset  # noqa: E402

ANTI_ONE_TRICK = pbr.PRESETS_BY_ID["hero_anti_one_trick"].ruleset.to_json()


def expire(room: Room, kind: PickBanKind = PickBanKind.HERO) -> None:
    room.session(kind).current_step_started_at = datetime.now(UTC) - timedelta(hours=1)


class MigratedV1HeroConfigTests(IsolatedAsyncioTestCase):
    """``sequence_json=[ban_first, ban_second]`` + ``turn_timer_seconds`` after
    the migration: one actor per step, open (public on the click), the timer
    standing in for a captain who never answered, and the two-sided undo."""

    def _room(self) -> Room:
        return Room(
            hero_ruleset=v1_ruleset(sequence=["ban_first", "ban_second"], turn_timer_seconds=30),
            hero_items=[1, 2, 3, 11, 12],
        )

    async def test_it_alternates_sides_and_applies_each_ban_immediately(self) -> None:
        room = self._room()

        state = await room.state()
        self.assertEqual(["home"], state["acting_sides"])
        self.assertEqual(
            [("ban", ["home"], False, 1), ("ban", ["away"], False, 1)],
            [(s["action"], s["sides"], s["blind"], s["count"]) for s in state["sequence"]],
        )
        self.assertIsNotNone(state["step_deadline"], "the v1 turn timer became the step's timer")

        state = await room.act(HOME, 1)
        # An open step is public the instant it lands -- no reveal to wait for.
        self.assertEqual(["away"], state["acting_sides"])
        self.assertEqual([(1, "home")], [(e["item_id"], e["picked_by"]) for e in banned_of(state)])
        self.assertEqual([2, 3, 11, 12], available_of(state))

        state = await room.act(AWAY, 2)
        self.assertTrue(state["is_complete"])
        self.assertEqual({(1, "home"), (2, "away")}, {(e["item_id"], e["picked_by"]) for e in banned_of(state)})

    async def test_a_timed_out_turn_is_banned_at_random_for_the_absent_captain(self) -> None:
        picked: set[int] = set()
        for _ in range(30):
            room = self._room()
            await room.open()
            expire(room)

            state = await room.state()

            banned = banned_of(state)
            self.assertEqual(1, len(banned), "exactly the abandoned step resolved")
            self.assertEqual("home", banned[0]["picked_by"])
            self.assertEqual(1, state["current_step_index"], "away is now on the clock, with a fresh deadline")
            picked.add(banned[0]["item_id"])
        self.assertEqual({1, 2, 3, 11, 12}, picked, "every candidate is reachable by the draw")

    async def test_both_captains_can_take_the_last_ban_back(self) -> None:
        room = self._room()
        await room.act(HOME, 1)

        asked = await room.undo(HOME)
        self.assertEqual("home", asked["requested_by"])
        self.assertEqual("banned", next(e["status"] for e in (await room.state())["pool"] if e["item_id"] == 1))

        await room.undo(AWAY)

        state = await room.state()
        self.assertEqual([], banned_of(state))
        self.assertEqual(0, state["current_step_index"])
        self.assertEqual(["home"], state["acting_sides"])
        # And the restored step is answerable again, with a different hero.
        state = await room.act(HOME, 3)
        self.assertEqual([3], [e["item_id"] for e in banned_of(state)])


class SlotVetoSeriesTests(IsolatedAsyncioTestCase):
    """The Bo3 loop on a migrated slot-veto map config plus sequential hero
    bans: map veto -> hero round -> the map is played and reported -> next
    map. The barrier is the property the whole room is built on."""

    async def asyncSetUp(self) -> None:
        self.room = Room(
            hero_ruleset=v1_ruleset(sequence=["ban_first", "ban_second"]),
            hero_items=[1, 2, 3, 4, 5, 11, 12, 13, 14, 15],
            with_map_veto=True,
        )

    async def ban_out_hero_round(self) -> list[int]:
        banned: list[int] = []
        for _ in range(2):
            state = await self.room.state()
            item_id = available_of(state)[0]
            await self.room.act(state["acting_sides"][0], item_id)
            banned.append(item_id)
        return banned

    async def test_a_bo3_cycles_all_three_phases(self) -> None:
        room = self.room

        hero = await room.state()
        self.assertIsNone(hero["session"])
        self.assertEqual("waiting_map", hero["reason"], "heroes are banned FOR a map")

        map_one = await room.ban_out_the_map_round()
        state = await room.state(PickBanKind.MAP)
        self.assertEqual(
            [(1, map_one, "awaiting_result")], [(g["position"], g["map_id"], g["state"]) for g in state["games"]]
        )

        round_one = await self.ban_out_hero_round()
        self.assertTrue((await room.state())["is_complete"])

        # Round 2 stays shut until position 1 has a CONFIRMED result.
        self.assertEqual({1}, {entry["round"] for entry in (await room.state())["pool"]})
        await room.report(1, 2, 1)

        state = await room.state(PickBanKind.MAP)
        self.assertEqual(2, state["current_round"])
        self.assertEqual(["home"], state["acting_sides"], "result_winner_first: home won map 1")

        await room.ban_out_the_map_round()
        hero = await room.state()
        self.assertEqual(2, hero["current_round"])
        round_two = await self.ban_out_hero_round()
        await room.report(2, 1, 2)

        await room.ban_out_the_map_round()
        round_three = await self.ban_out_hero_round()
        await room.report(3, 2, 0)

        state = await room.state(PickBanKind.MAP)
        self.assertTrue(state["series"]["complete"])
        self.assertEqual([1, 2, 3], [game["position"] for game in state["games"]])
        self.assertEqual((2, 1), (room.encounter.home_score, room.encounter.away_score))
        hero = await room.state()
        self.assertEqual({1, 2, 3}, {entry["round"] for entry in hero["pool"]})
        # Each closed round keeps its two bans and drops the untouched rest.
        for round_number in (1, 2):
            self.assertEqual(2, len([e for e in hero["pool"] if e["round"] == round_number]))
        # A migrated v1 config bans with `lifetime: 1`, so nothing carries: each
        # round re-offers the whole pool, which is exactly `no_repeat_scope=none`.
        self.assertEqual([round_one, round_two, round_three], [round_one] * 3)
        self.assertEqual([], [e for e in hero["pool"] if e["carried_from_round"] is not None])


class AntiOneTrickTests(IsolatedAsyncioTestCase):
    """The tournament preset (design §12)."""

    async def asyncSetUp(self) -> None:
        self.room = Room(
            hero_ruleset=ANTI_ONE_TRICK,
            with_map_veto=True,
            with_rosters=True,
        )
        await self.room.ban_out_the_map_round()

    # -- helpers -----------------------------------------------------------
    def targets(self, side: str) -> list[int]:
        """The opponent roster ids ``side`` bans for, in role order."""
        opponent = AWAY if side == HOME else HOME
        return [player.id for player in self.room.players[opponent]]

    def draft(self, side: str, heroes: list[int]) -> list[dict]:
        return [
            {"item_id": hero_id, "target_player_id": player_id}
            for hero_id, player_id in zip(heroes, self.targets(side), strict=True)
        ]

    async def play_map_one_bans(self) -> dict:
        await self.room.submit(HOME, [1, 2], lock=True)
        return await self.room.submit(AWAY, [2, 3], lock=True)

    async def open_map_two_bans(self) -> None:
        await self.play_map_one_bans()
        await self.room.report(1, 2, 1)
        await self.room.ban_out_the_map_round()
        state = await self.room.state()
        assert state["current_round"] == 2, state["current_round"]

    # -- map 1: blind 2+2 ---------------------------------------------------
    async def test_map_one_is_a_blind_two_plus_two_that_merges_duplicates(self) -> None:
        room = self.room

        state = await room.state()
        step = state["current_step"]
        self.assertEqual(
            ("ban", ["home", "away"], True, 2, 1),
            (step["action"], step["sides"], step["blind"], step["count"], step["lifetime"]),
        )
        self.assertIsNone(step["target"])

        await room.submit(HOME, [1, 2], lock=True)

        # Privacy: the opponent learns that home locked two items, nothing more.
        opponent = await room.state(viewer=AWAY)
        self.assertEqual(
            {"home": {"locked": True, "filled": 2}, "away": {"locked": False, "filled": 0}}, opponent["step_progress"]
        )
        self.assertEqual([], opponent["submissions"])
        self.assertEqual([], banned_of(opponent))

        state = await room.submit(AWAY, [2, 3], lock=True)

        # Overlap on hero 2: banned once, credited to the first side in order.
        self.assertEqual(3, len(banned_of(state)))
        self.assertEqual(
            {(1, "home"), (2, "home"), (3, "away")},
            {(e["item_id"], e["picked_by"]) for e in banned_of(state)},
        )
        self.assertTrue(state["is_complete"])

    async def test_a_timed_out_blind_step_is_filled_at_random_and_revealed(self) -> None:
        room = self.room
        await room.submit(HOME, [1], lock=False)
        await room.open()
        expire(room)

        state = await room.state()

        self.assertTrue(state["is_complete"])
        self.assertEqual([2, 2], [len(row["items"]) for row in sorted(state["submissions"], key=lambda r: r["side"])])
        self.assertIn(1, [e["item_id"] for e in banned_of(state)])

    # -- map 2+: per-opponent-player 5+5 ------------------------------------
    async def test_map_two_bans_one_hero_per_opponent_player_matching_their_role(self) -> None:
        room = self.room
        await self.open_map_two_bans()

        state = await room.state()
        step = state["current_step"]
        self.assertEqual(
            ("opponent_player", 5, 2, True), (step["target"], step["count"], step["lifetime"], step["blind"])
        )
        # The board the room draws: both rosters, tanks first, then damage,
        # then support.
        self.assertEqual(
            ["tank", "damage", "damage", "support", "support"],
            [player["role"] for player in state["targets"]["away"]],
        )
        self.assertEqual({"home", "away"}, set(state["targets"]))
        self.assertEqual(
            sorted(self.targets(HOME)),
            sorted(int(player_id) for player_id in state["eligible"]["by_target"]),
            "home chooses for AWAY's players",
        )

        tank_target, damage_target = self.targets(HOME)[0], self.targets(HOME)[1]

        with self.assertRaises(HTTPException) as caught:
            await room.submit(
                HOME,
                [
                    {"item_id": 1, "target_player_id": tank_target},
                    {"item_id": 2, "target_player_id": tank_target},
                ],
                lock=False,
            )
        self.assertIn("one_per_target", caught.exception.detail)

        with self.assertRaises(HTTPException) as caught:
            await room.submit(HOME, [{"item_id": 21, "target_player_id": tank_target}], lock=False)
        self.assertEqual("item_not_eligible", caught.exception.detail, "a support hero is not a tank's ban")

        # A damage hero on a damage player is fine.
        await room.submit(HOME, [{"item_id": 11, "target_player_id": damage_target}], lock=False)
        self.assertEqual(["not_enough_items"], (await room.state(viewer=HOME))["draft_issues"])

        await room.submit(HOME, self.draft(HOME, [1, 11, 12, 21, 22]), lock=True)
        state = await room.submit(AWAY, self.draft(AWAY, [2, 13, 14, 23, 24]), lock=True)

        self.assertTrue(state["is_complete"])
        self.assertEqual(10, len(banned_of(state, round=2)))
        self.assertEqual(
            {
                (1, "home"),
                (11, "home"),
                (12, "home"),
                (21, "home"),
                (22, "home"),
                (2, "away"),
                (13, "away"),
                (14, "away"),
                (23, "away"),
                (24, "away"),
            },
            {(e["item_id"], e["picked_by"]) for e in banned_of(state, round=2)},
        )

    async def test_map_three_carries_the_map_two_bans_and_adds_ten_more(self) -> None:
        room = self.room
        await self.open_map_two_bans()
        await room.submit(HOME, self.draft(HOME, [1, 11, 12, 21, 22]), lock=True)
        await room.submit(AWAY, self.draft(AWAY, [2, 13, 14, 23, 24]), lock=True)
        await room.report(2, 1, 2)
        await room.ban_out_the_map_round()

        state = await room.state()
        self.assertEqual(3, state["current_round"])

        carried = [entry for entry in state["pool"] if entry["carried_from_round"] is not None]
        self.assertEqual(10, len(carried), "map 2's bans have lifetime 2, so map 3 still owes them")
        self.assertEqual({2}, {entry["carried_from_round"] for entry in carried})
        self.assertEqual({MapPoolEntryStatus.BANNED.value}, {entry["status"] for entry in carried})
        self.assertEqual({1, 2, 11, 12, 13, 14, 21, 22, 23, 24}, {entry["item_id"] for entry in carried})
        # Map 1's bans had lifetime 1 and expired two maps ago.
        self.assertNotIn(3, {entry["item_id"] for entry in carried})
        self.assertEqual(15, len(available_of(state)), "25 heroes minus the 10 still banned")
        self.assertEqual([], [entry["item_id"] for entry in carried if entry["item_id"] in available_of(state)])

        await room.submit(HOME, self.draft(HOME, [3, 15, 16, 25, 26]), lock=True)
        state = await room.submit(AWAY, self.draft(AWAY, [4, 17, 18, 27, 28]), lock=True)

        fresh = [entry for entry in banned_of(state, round=3) if entry["carried_from_round"] is None]
        self.assertEqual(10, len(fresh))
        self.assertEqual(20, len(banned_of(state, round=3)), "10 carried + 10 new")

    # -- dispute ------------------------------------------------------------
    async def test_a_dispute_reopens_the_step_with_both_drafts_prefilled(self) -> None:
        room = self.room
        await self.open_map_two_bans()
        home_draft = self.draft(HOME, [1, 11, 12, 21, 22])
        await room.submit(HOME, home_draft, lock=True)
        state = await room.submit(AWAY, self.draft(AWAY, [2, 13, 14, 23, 24]), lock=True)
        self.assertEqual(
            {"available": True, "attempts_used": 0, "max": 1},
            {key: state["dispute"][key] for key in ("available", "attempts_used", "max")},
        )

        state = await room.dispute(AWAY)

        self.assertFalse(state["is_complete"], "the step is live again")
        self.assertEqual([], banned_of(state, round=2), "the revealed bans are void until it settles again")
        home = await room.state(viewer=HOME)
        reopened = [row for row in home["submissions"] if row["step_index"] == home["current_step_index"]]
        self.assertEqual(
            [(("home", "draft", 2), [(item["item_id"], item["target_player_id"]) for item in home_draft])],
            [
                (
                    (row["side"], row["state"], row["attempt"]),
                    [(item["item_id"], item["target_player_id"]) for item in row["items"]],
                )
                for row in reopened
            ],
            "the side's previous draft is handed back to it, and to nobody else",
        )

    async def test_a_second_dispute_is_refused_by_the_steps_max(self) -> None:
        room = self.room
        await self.open_map_two_bans()
        await room.submit(HOME, self.draft(HOME, [1, 11, 12, 21, 22]), lock=True)
        await room.submit(AWAY, self.draft(AWAY, [2, 13, 14, 23, 24]), lock=True)
        await room.dispute(AWAY)
        await room.submit(HOME, self.draft(HOME, [1, 11, 12, 21, 22]), lock=True)
        state = await room.submit(AWAY, self.draft(AWAY, [2, 13, 14, 23, 24]), lock=True)

        self.assertEqual(
            {"available": False, "attempts_used": 1, "max": 1},
            {key: state["dispute"][key] for key in ("available", "attempts_used", "max")},
        )
        with self.assertRaises(HTTPException) as caught:
            await room.dispute(HOME)
        self.assertEqual("This step cannot be reopened", caught.exception.detail)

    async def test_a_reported_map_can_no_longer_be_disputed(self) -> None:
        room = self.room
        state = await self.play_map_one_bans()
        self.assertTrue(state["dispute"]["available"], "map 1's bans are disputable until the map is settled")

        await room.report(1, 2, 1)

        state = await room.state()
        self.assertFalse(state["dispute"]["available"])
        with self.assertRaises(HTTPException) as caught:
            await room.dispute(HOME)
        self.assertEqual("This step cannot be reopened", caught.exception.detail)
