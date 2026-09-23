"""End-to-end proof of the pre-game loop, one position of the series at a time:

    map veto (this position's map) -> hero bans (for that map) -> the map is
    played and both captains claim it -> that ACCEPTED result opens the next one

The unit suites (``test_pick_ban_session.py``, ``test_pick_ban_action.py``)
each pin one function's behavior against a canned answer. This one runs the
real service functions -- ``get_pick_ban_state``, ``perform_pick_ban_action``,
``submit_map_report``, ``sync_hero_rounds`` -- against an in-memory store that
actually holds rows, so the loop has to CYCLE rather than merely be plausible
step by step. It is the regression net for the property the room is built on:
round N+1's bans cannot be taken before position N has a CONFIRMED result.

The series' positions are ``EncounterGame`` rows now, not ``Match`` rows and not
map ids: a claim targets a game, the accepted score lives on the game, and the
live series score is derived from the confirmed ones (spec §5.1/§5.2). The room
reads them off ``state["games"]``/``state["series"]``.

The store below is a fake ``AsyncSession``, not a database: it interprets the
handful of query shapes these services issue by walking the SQLAlchemy
expression tree (never by string-matching SQL). Everything it does not know
about -- the seed-resolution lookups (``StageItemInput``/``Stage``/
``Standing``) -- answers empty, which is exactly the "no bracket seeds" path
(``decide_seeds`` -> home acts first).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    EncounterGameState,
    FirstBanRotation,
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoMode,
    PickBanKind,
    PickBanNoRepeatScope,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.matches.match import Match  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterReadiness,
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
    PickBanEntry,
    PickBanSession,
)
from shared.models.tournament.stage import Stage  # noqa: E402
from src.services.encounter.map_report import map_report_service  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from src.services.encounter.pick_ban_session import (  # noqa: E402
    REASON_WAITING_MAP,
    pick_ban_session_service,
)
from tests._pregame_store import _matches, _Result, _Store, staged_topics  # noqa: E402,F401

# ── fixtures ─────────────────────────────────────────────────────────────────

MAP_SLOTS = [[11, 12, 13], [21, 22, 23], [31, 32, 33]]
# Wide enough for three rounds of four bans with nothing re-banned (12 heroes)
# and slack on top, the way a real hero pool is.
HEROES = list(range(101, 117))
HOME_TEAM, AWAY_TEAM = 10, 20


def _map_config(*, rotation: str = FirstBanRotation.RESULT_WINNER_FIRST) -> PickBanConfig:
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.MAP,
        stage_id=None,
        round=None,
        mode=MapVetoMode.SLOTS,
        first_ban_rotation=rotation,
        preset="bracket",
        sequence_json=[],
        turn_timer_seconds=None,
        no_repeat_scope=PickBanNoRepeatScope.NONE,
        unique_attribute_per_side_per_round=None,
        allow_protect=False,
    )
    config.items = []
    config.slots = [
        PickBanConfigSlot(position=position, reserve_item_id=None) for position, _ in enumerate(MAP_SLOTS, start=1)
    ]
    for slot, item_ids in zip(config.slots, MAP_SLOTS, strict=True):
        slot.items = [PickBanConfigSlotItem(item_id=item_id) for item_id in item_ids]
    return config


def _hero_config() -> PickBanConfig:
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.HERO,
        stage_id=None,
        round=None,
        mode=MapVetoMode.POOL,
        first_ban_rotation=FirstBanRotation.FIXED,
        preset="custom",
        # Two bans per side, per map of the series.
        sequence_json=["ban_first", "ban_second", "ban_second", "ban_first"],
        turn_timer_seconds=None,
        # Doc 1's rule: nobody re-bans a hero anywhere in the series.
        no_repeat_scope=PickBanNoRepeatScope.ENCOUNTER,
        unique_attribute_per_side_per_round=None,
        allow_protect=False,
    )
    config.slots = []
    config.items = [PickBanConfigItem(item_id=item_id, sort_order=index) for index, item_id in enumerate(HEROES)]
    return config


def _encounter() -> Encounter:
    encounter = Encounter(
        tournament_id=7,
        stage_id=None,
        stage_item_id=None,
        round=1,
        best_of=3,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_score=0,
        away_score=0,
    )
    return encounter


class PregameLoopTests(IsolatedAsyncioTestCase):
    MAP_ROTATION = FirstBanRotation.RESULT_WINNER_FIRST

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.map_config = _map_config(rotation=self.MAP_ROTATION)
        self.hero_config = _hero_config()
        self.encounter = _encounter()
        self.store.seed(
            self.encounter,
            self.map_config,
            self.hero_config,
            EncounterReadiness(encounter_id=1, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=1, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        # Ids are assigned in seed order; the encounter is first.
        self.encounter_id = self.encounter.id
        for readiness in self.store.all_of(EncounterReadiness):
            readiness.encounter_id = self.encounter_id

    # -- helpers ----------------------------------------------------------
    async def map_state(self) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )

    async def hero_state(self) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.HERO, viewer_side=MapPickSide.HOME.value
        )

    async def act(self, kind: PickBanKind, side: str, item_id: int, action: str = "ban") -> None:
        await pick_ban_action_service.perform_pick_ban_action(
            self.store, self.encounter_id, kind, side, item_id, action
        )

    async def ban_out_the_map_round(self) -> int:
        """Both sides ban this round's first two candidates; the decider takes
        the survivor. Returns the map the round settled on."""
        state = await self.map_state()
        available = [
            entry["item_id"] for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value
        ]
        self.assertEqual(3, len(available), "a map round offers its slot's three candidates")
        await self.act(PickBanKind.MAP, state["turn_side"], available[0])
        state = await self.map_state()
        await self.act(PickBanKind.MAP, state["turn_side"], available[1])
        state = await self.map_state()
        self.assertTrue(state["is_complete"], "the decider closes the round as soon as one candidate is left")
        return available[2]

    async def ban_out_the_hero_round(self) -> list[int]:
        """The round's four bans, two per side. Returns the heroes banned."""
        banned: list[int] = []
        for _ in range(4):
            state = await self.hero_state()
            self.assertFalse(state["is_complete"])
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await self.act(PickBanKind.HERO, state["turn_side"], available[0])
            banned.append(available[0])
        self.assertTrue((await self.hero_state())["is_complete"])
        return banned

    async def game_at(self, position: int) -> dict:
        state = await self.map_state()
        return next(game for game in state["games"] if game["position"] == position)

    async def claim(self, position: int, side: str, home_score: int, away_score: int) -> dict:
        game = await self.game_at(position)
        return await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            game_id=game["id"],
            side=side,
            reporter_user_id=None,
            home_score=home_score,
            away_score=away_score,
        )

    async def report(self, position: int, home_score: int, away_score: int) -> dict:
        """Both captains file the same score for one position -- the agreement
        that accepts it."""
        result: dict = {}
        for side in (MapPickSide.HOME.value, MapPickSide.AWAY.value):
            result = await self.claim(position, side, home_score, away_score)
        return result

    # -- the loop ---------------------------------------------------------
    async def test_a_bo3_runs_map_then_heroes_then_the_result_each_round(self) -> None:
        # ── round 1 ──────────────────────────────────────────────────────
        state = await self.map_state()
        self.assertEqual(["ban_home", "ban_away", "decider"], state["sequence"])
        self.assertEqual(3, len(state["pool"]), "only round 1 exists yet")

        # Heroes are banned FOR a map, so the hero phase is closed until this
        # round's map is picked.
        hero = await self.hero_state()
        self.assertIsNone(hero["session"])
        self.assertEqual(REASON_WAITING_MAP, hero["reason"])

        map_one = await self.ban_out_the_map_round()

        # Round 2's bans are NOT available: nothing is left to act on until the
        # result of position 1 lifts the barrier.
        state = await self.map_state()
        self.assertEqual(
            [], [entry for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value]
        )
        self.assertTrue(state["is_complete"])
        # The pick opened the position, with the map it named on it.
        self.assertEqual(
            [(1, map_one, EncounterGameState.AWAITING_RESULT.value)],
            [(game["position"], game["map_id"], game["state"]) for game in state["games"]],
        )

        round_one_heroes = await self.ban_out_the_hero_round()

        # The position's result is the third phase, and what opens the next map.
        state = await self.map_state()
        self.assertEqual([[]], [game["reports"] for game in state["games"]])
        result = await self.report(1, 2, 1)
        self.assertEqual({"disputed": False, "resolved": True}, {k: result[k] for k in ("disputed", "resolved")})
        self.assertEqual(EncounterGameState.CONFIRMED.value, result["game"]["state"])
        self.assertEqual((2, 1), (result["game"]["accepted_home_score"], result["game"]["accepted_away_score"]))
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

        # ── round 2 ──────────────────────────────────────────────────────
        state = await self.map_state()
        self.assertFalse(state["is_complete"], "position 1's result opened map 2's bans")
        self.assertEqual(2, state["current_round"])
        # `result_winner_first`: home won map 1, so home opens map 2's bans.
        self.assertEqual(MapPickSide.HOME.value, state["turn_side"])
        # A settled pick is never re-stamped: `picked` is the whole settled set,
        # and the result lives on the game.
        self.assertEqual(
            {MapPoolEntryStatus.BANNED.value, MapPoolEntryStatus.PICKED.value},
            {entry["status"] for entry in state["pool"] if entry["round"] == 1},
        )
        self.assertEqual(
            {"home_wins": 1, "away_wins": 0, "played": 1},
            {k: state["series"][k] for k in ("home_wins", "away_wins", "played")},
        )

        await self.ban_out_the_map_round()
        round_two_heroes = await self.ban_out_the_hero_round()
        # No hero is re-banned anywhere in the series (`no_repeat_scope=encounter`).
        self.assertEqual(set(), set(round_one_heroes) & set(round_two_heroes))
        await self.report(2, 1, 2)
        self.assertEqual((1, 1), (self.encounter.home_score, self.encounter.away_score))

        # ── round 3 ──────────────────────────────────────────────────────
        state = await self.map_state()
        self.assertEqual(3, state["current_round"])
        # Away won map 2, so away opens map 3's bans.
        self.assertEqual(MapPickSide.AWAY.value, state["turn_side"])

        await self.ban_out_the_map_round()
        round_three_heroes = await self.ban_out_the_hero_round()
        self.assertEqual(
            12,
            len({*round_one_heroes, *round_two_heroes, *round_three_heroes}),
            "three rounds of two bans per side, none repeated",
        )
        await self.report(3, 2, 0)
        self.assertEqual((2, 1), (self.encounter.home_score, self.encounter.away_score))

        # ── the series is over ───────────────────────────────────────────
        state = await self.map_state()
        self.assertTrue(state["is_complete"])
        self.assertEqual({1, 2, 3}, {entry["round"] for entry in state["pool"]}, "no fourth map round was ever opened")
        self.assertEqual([1, 2, 3], [game["position"] for game in state["games"]])
        self.assertEqual([EncounterGameState.CONFIRMED.value] * 3, [game["state"] for game in state["games"]])
        self.assertTrue(state["series"]["complete"])
        hero = await self.hero_state()
        self.assertTrue(hero["is_complete"])
        self.assertEqual({1, 2, 3}, {entry["round"] for entry in hero["pool"]})
        # Each closed hero round keeps its four bans and drops the candidates
        # nobody touched, so the round in play is never mistaken for an old one.
        for round_number in (1, 2):
            self.assertEqual(4, len([entry for entry in hero["pool"] if entry["round"] == round_number]))

    async def test_a_disputed_result_holds_the_next_map_closed(self) -> None:
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()

        await self.claim(1, MapPickSide.HOME.value, 2, 1)
        disputed = await self.claim(1, MapPickSide.AWAY.value, 0, 2)

        self.assertTrue(disputed["disputed"])
        self.assertEqual(EncounterGameState.DISPUTED.value, disputed["game"]["state"])
        state = await self.map_state()
        self.assertTrue(state["is_complete"], "a disputed position opens nothing")
        self.assertEqual({1}, {entry["round"] for entry in state["pool"]})
        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))
        # Both claims are on the position so the room can say WHY it is waiting.
        self.assertEqual(
            [{MapPickSide.HOME.value, 2, 1}, {MapPickSide.AWAY.value, 0, 2}],
            [{report["side"], report["home_score"], report["away_score"]} for report in state["games"][0]["reports"]],
        )

    async def test_a_decided_series_stops_opening_rounds(self) -> None:
        # 2-0 in a Bo3: map 3 is never played, so it never gets a pick-ban round.
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(1, 2, 0)

        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(2, 2, 1)

        self.assertEqual((2, 0), (self.encounter.home_score, self.encounter.away_score))
        state = await self.map_state()
        self.assertTrue(state["is_complete"])
        self.assertEqual({1, 2}, {entry["round"] for entry in state["pool"]})
        self.assertEqual([1, 2], [game["position"] for game in state["games"]])
        self.assertTrue(state["series"]["complete"])
        hero = await self.hero_state()
        self.assertEqual({1, 2}, {entry["round"] for entry in hero["pool"]})

    async def test_a_confirmed_game_rejects_a_new_claim_with_409_result_locked(self) -> None:
        """Changing an accepted result is the admin correction command, with a
        reason -- not two captains quietly re-agreeing (spec §6.5)."""
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(1, 2, 1)

        with self.assertRaises(HTTPException) as caught:
            await self.claim(1, MapPickSide.HOME.value, 1, 2)

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual(["result_locked"], [item.code for item in caught.exception.detail])
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

    async def test_two_agreeing_claims_count_the_win_once_and_a_re_submitted_identical_claim_changes_nothing(
        self,
    ) -> None:
        """The pair of claims is ONE agreement, not two results -- and the
        second captain's claim landing twice (a double-click, a retry) must not
        credit the map twice either."""
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()

        first = await self.claim(1, MapPickSide.HOME.value, 2, 1)
        self.assertFalse(first["resolved"])
        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))

        await self.claim(1, MapPickSide.AWAY.value, 2, 1)
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

        with self.assertRaises(HTTPException) as caught:
            await self.claim(1, MapPickSide.AWAY.value, 2, 1)

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))
        game = await self.game_at(1)
        self.assertEqual(1, game["result_version"], "one acceptance, one version")

    async def test_hero_round_n_plus_one_waits_for_confirmed_game_n_even_when_the_map_is_picked(self) -> None:
        """Spec V03. A decider can settle map 2 the instant round 2's bans end,
        which is BEFORE map 1 has a result. Heroes are banned for the map that
        is next; handing out map 2's hero bans there would let both captains
        finish the series' hero phase without playing a map."""
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(1, 2, 1)
        await self.ban_out_the_map_round()  # map 2 is picked...

        hero = await self.hero_state()
        self.assertEqual({1, 2}, {entry["round"] for entry in hero["pool"]}, "map 1 is confirmed, so round 2 opens")

        # ...but map 3 is only picked once map 2 is confirmed, and its hero round
        # waits on the same confirmation.
        await self.ban_out_the_hero_round()
        await self.claim(2, MapPickSide.HOME.value, 1, 2)  # one claim is not a result

        hero = await self.hero_state()
        self.assertEqual({1, 2}, {entry["round"] for entry in hero["pool"]}, "an unconfirmed position opens nothing")
        self.assertTrue(hero["is_complete"])

        await self.claim(2, MapPickSide.AWAY.value, 1, 2)
        await self.ban_out_the_map_round()

        hero = await self.hero_state()
        self.assertEqual({1, 2, 3}, {entry["round"] for entry in hero["pool"]})

    async def test_a_map_played_twice_keeps_the_two_plays_apart(self) -> None:
        # A slot config may list the same map in two rounds, and with
        # `no_repeat_scope=none` nothing stops the series from playing it twice.
        # Slot 3's decider is slot 1's decider: `ban_out_the_map_round` bans the
        # first two candidates, so both rounds settle on 13. The POSITION is what
        # tells the two plays apart -- a claim names a game, never a map.
        self.map_config.slots[2].items = [PickBanConfigSlotItem(item_id=item_id) for item_id in (31, 32, 13)]

        first_play = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(1, 2, 1)

        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(2, 1, 2)

        third_play = await self.ban_out_the_map_round()
        self.assertEqual(first_play, third_play, "the fixture plays map 13 twice")
        await self.ban_out_the_hero_round()
        await self.report(3, 2, 0)

        state = await self.map_state()
        thirteens = [game for game in state["games"] if game["map_id"] == first_play]
        self.assertEqual([1, 3], [game["position"] for game in thirteens])
        self.assertEqual(
            [(2, 1), (2, 0)],
            [(game["accepted_home_score"], game["accepted_away_score"]) for game in thirteens],
        )
        # Two claims per position, never shared between the two plays.
        self.assertEqual([2, 2], [len(game["reports"]) for game in thirteens])
        self.assertEqual((2, 1), (self.encounter.home_score, self.encounter.away_score))

    async def test_the_first_report_of_a_map_pushes_a_room_update(self) -> None:
        # The opponent's tile only flips from "not reported" to "sealed" on a
        # realtime signal: nothing else pushes it, and `submit_map_report`'s
        # return value reaches the captain who filed and nobody else. The
        # unresolved path used to commit silently, so the opponent had to reload.
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        game = await self.game_at(1)
        self.store.info.pop("realtime_staged", None)

        result = await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            game_id=game["id"],
            side=MapPickSide.HOME.value,
            reporter_user_id=None,
            home_score=2,
            away_score=1,
        )

        self.assertFalse(result["resolved"], "one claim resolves nothing on its own")
        self.assertEqual(
            [f"encounter:{self.encounter_id}:map-veto", f"encounter:{self.encounter_id}:pick-ban:hero"],
            staged_topics(self.store),
        )

    async def test_scrim_series_rotates_on_the_game_outcome_without_a_match_row(self) -> None:
        """A scrim room runs the identical loop -- and no longer takes a branch
        of its own to do it.

        The scrim carve-out existed because reconciliation used to WRITE a
        ``matches.match`` row, which a scrim has no use for. Nothing writes one
        here any more: the progression reads the position's accepted result off
        its ``EncounterGame``, so a scrim and a tournament are the same code
        path, and ``is_scrim_container`` has nothing left to guard.
        """
        self.map_config.first_ban_rotation = FirstBanRotation.RESULT_LOSER_FIRST

        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(1, 1, 2)

        state = await self.map_state()
        self.assertEqual(2, state["current_round"])
        # Away won position 1, so the LOSER (home) opens map 2's bans.
        self.assertEqual(MapPickSide.HOME.value, state["turn_side"])
        self.assertEqual([], self.store.all_of(Match), "the series loop writes no match row")

    async def test_result_loser_choice_after_a_draw_opens_the_next_round_on_the_snapshot_side_without_a_choice(
        self,
    ) -> None:
        """A draw has no loser to elect, so `result_loser_choice` falls back to
        the session's established opener instead of stalling the room on a modal
        nobody can answer."""
        self.map_config.first_ban_rotation = FirstBanRotation.RESULT_LOSER_CHOICE

        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(1, 1, 1)

        map_session = next(row for row in self.store.all_of(PickBanSession) if row.kind == PickBanKind.MAP)
        self.assertFalse(map_session.awaiting_choice)
        self.assertIsNone(map_session.pending_loser_side)
        state = await self.map_state()
        self.assertEqual(2, state["current_round"])
        self.assertEqual(MapPickSide.HOME.value, state["turn_side"], "the session's snapshot side opens")
        # The draw still consumed a position: 0:0 with one map played.
        self.assertEqual(
            {"home_wins": 0, "away_wins": 0, "played": 1, "complete": False},
            {key: state["series"][key] for key in ("home_wins", "away_wins", "played", "complete")},
        )


class LoserChoiceStallTests(IsolatedAsyncioTestCase):
    """``first_ban_rotation=result_loser_choice`` on the HERO config: the round
    after each map cannot open until a human names its opener.

    Standalone rather than a ``PregameLoopTests`` subclass on purpose — the
    suite above cycles a series unattended, which this rotation by definition
    cannot do.

    The regression: nothing but the losing captain's own modal ever surfaced
    the wait, and no override could resolve it. An unreachable captain left the
    room showing a finished round with nothing to click, and the only admin
    control on screen was a session-wiping reset — which re-creates round 1 and
    walks into the same wall one map later.
    """

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.map_config = _map_config()
        self.hero_config = _hero_config()
        self.hero_config.first_ban_rotation = FirstBanRotation.RESULT_LOSER_CHOICE
        self.encounter = _encounter()
        self.store.seed(
            self.encounter,
            self.map_config,
            self.hero_config,
            EncounterReadiness(encounter_id=1, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=1, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        self.encounter_id = self.encounter.id
        for readiness in self.store.all_of(EncounterReadiness):
            readiness.encounter_id = self.encounter_id

    async def state(self, kind: PickBanKind) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, kind, viewer_side=MapPickSide.HOME.value
        )

    async def play_map_one(self) -> None:
        """Map 1 vetoed, its four hero bans taken, its result agreed (home wins),
        and map 2 vetoed — the loop's state one step before hero round 2."""
        for _ in range(2):
            state = await self.state(PickBanKind.MAP)
            available = [
                entry["item_id"] for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], available[0], "ban"
            )
        for _ in range(4):
            state = await self.state(PickBanKind.HERO)
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.HERO, state["turn_side"], available[0], "ban"
            )
        game_id = next(game["id"] for game in (await self.state(PickBanKind.MAP))["games"] if game["position"] == 1)
        for side in (MapPickSide.HOME.value, MapPickSide.AWAY.value):
            await map_report_service.submit_map_report(
                self.store,
                self.encounter,
                game_id=game_id,
                side=side,
                reporter_user_id=None,
                home_score=2,
                away_score=1,
            )
        for _ in range(2):
            state = await self.state(PickBanKind.MAP)
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], available[0], "ban"
            )
        # The hero session catches up with the map phase on a READ
        # (`sync_hero_rounds`), which is where the choice gate is reached.
        await self.state(PickBanKind.HERO)

    def hero_session(self) -> PickBanSession:
        return next(pick_ban for pick_ban in self.store.all_of(PickBanSession) if pick_ban.kind == PickBanKind.HERO)

    def hero_rounds(self) -> set[int]:
        hero_id = self.hero_session().id
        return {entry.round for entry in self.store.all_of(PickBanEntry) if entry.session_id == hero_id}

    async def test_the_wait_is_on_the_state_for_every_viewer_not_just_the_loser(self) -> None:
        await self.play_map_one()

        hero = await self.state(PickBanKind.HERO)
        self.assertTrue(hero["is_complete"])
        self.assertEqual({1}, {entry["round"] for entry in hero["pool"]}, "round 2 waits on the choice")
        # Away lost map 1, so away chooses — and the room can say so to anybody,
        # including the admin looking at a session that is `completed`.
        self.assertTrue(hero["session"]["awaiting_choice"])
        self.assertEqual(MapPickSide.AWAY.value, hero["session"]["pending_loser_side"])

    async def test_the_winning_captain_may_not_elect(self) -> None:
        await self.play_map_one()

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.elect_round_opener(
                self.store, self.hero_session(), first_side="home", acting_side=MapPickSide.HOME.value
            )
        self.assertEqual(403, caught.exception.status_code)
        self.assertEqual({1}, self.hero_rounds())

    async def test_an_admin_elects_for_an_unreachable_captain_and_the_round_opens(self) -> None:
        await self.play_map_one()

        await pick_ban_session_service.elect_round_opener(
            self.store, self.hero_session(), first_side=MapPickSide.AWAY.value, acting_side=None
        )

        hero = await self.state(PickBanKind.HERO)
        self.assertEqual(2, hero["current_round"])
        self.assertFalse(hero["is_complete"])
        self.assertEqual(MapPickSide.AWAY.value, hero["turn_side"], "the elected side opens the round")
        self.assertFalse(hero["session"]["awaiting_choice"])
        self.assertIsNone(hero["session"]["pending_loser_side"])

    async def test_electing_twice_is_refused_rather_than_appending_a_second_round(self) -> None:
        await self.play_map_one()
        await pick_ban_session_service.elect_round_opener(
            self.store, self.hero_session(), first_side=MapPickSide.AWAY.value, acting_side=None
        )

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.elect_round_opener(
                self.store, self.hero_session(), first_side=MapPickSide.HOME.value, acting_side=None
            )
        self.assertEqual(400, caught.exception.status_code)
        self.assertEqual({1, 2}, self.hero_rounds())


class DeletedConfigStallTests(IsolatedAsyncioTestCase):
    """A progressive session whose config was deleted mid-series names the
    problem instead of declining in silence.

    ``PickBanSession.config_id`` is ``ondelete=SET NULL``, so the session
    survives its config and can never open another round. Returning quietly
    from ``advance_to_next_round`` left the room frozen on a finished round with
    no reason on screen and nothing in the logs.
    """

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.encounter = _encounter()
        self.store.seed(
            self.encounter,
            _map_config(),
            _hero_config(),
            EncounterReadiness(encounter_id=1, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=1, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        self.encounter_id = self.encounter.id
        for readiness in self.store.all_of(EncounterReadiness):
            readiness.encounter_id = self.encounter_id

    async def test_it_says_the_config_is_gone(self) -> None:
        state = await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )
        pick_ban = next(row for row in self.store.all_of(PickBanSession) if row.kind == PickBanKind.MAP)
        available = [
            entry["item_id"] for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value
        ]
        for item_id in available[:2]:
            state = await pick_ban_action_service.get_pick_ban_state(
                self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
            )
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], item_id, "ban"
            )
        pick_ban.config_id = None

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.advance_to_next_round(
                self.store, pick_ban, completed_round=1, outcome="home"
            )
        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("no longer", str(caught.exception.detail))


class FreeplayPositionOpensOnlyForAPlayableRoomTests(IsolatedAsyncioTestCase):
    """With no map veto configured the room offers one position at a time -- but
    only once there is a series to play.

    Reading the map room is a GET that every open client repeats, and an
    organizer previews brackets long before they are activated. Opening the
    position unconditionally wrote an ``encounter_game`` row for a matchup that
    may never exist (a preview stage), or for one whose slots are still waiting
    on an upstream result.
    """

    def _store(self, *, encounter: Encounter, stage: Stage | None = None) -> _Store:
        store = _Store()
        rows = [encounter, *([stage] if stage is not None else [])]
        store.seed(*rows)
        store.seed(
            EncounterReadiness(encounter_id=encounter.id, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=encounter.id, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        return store

    async def _map_state(self, store: _Store, encounter: Encounter) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            store, encounter.id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )

    async def test_a_live_freeplay_room_with_both_teams_opens_its_first_position(self) -> None:
        encounter = _encounter()
        store = self._store(encounter=encounter)

        state = await self._map_state(store, encounter)

        self.assertIsNone(state["session"], "no map config: there is no veto to run")
        self.assertEqual([(1, None, "planned")], [(g["position"], g["map_id"], g["state"]) for g in state["games"]])
        self.assertEqual(1, len(store.all_of(EncounterGame)))

    async def test_a_preview_bracket_opens_nothing(self) -> None:
        stage = Stage(tournament_id=7, name="Playoffs", is_published=False)
        encounter = _encounter()
        store = self._store(encounter=encounter, stage=stage)
        encounter.stage_id = stage.id

        state = await self._map_state(store, encounter)

        self.assertEqual([], state["games"])
        self.assertEqual([], store.all_of(EncounterGame))

    async def test_an_encounter_still_missing_a_team_opens_nothing(self) -> None:
        encounter = _encounter()
        encounter.away_team_id = None
        store = self._store(encounter=encounter)

        state = await self._map_state(store, encounter)

        self.assertEqual([], state["games"])
        self.assertEqual([], store.all_of(EncounterGame))
