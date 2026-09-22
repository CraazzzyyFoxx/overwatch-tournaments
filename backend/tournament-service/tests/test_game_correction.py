"""Admin correction of one position, and the round it re-opens (spec §6.5).

Position N's outcome is what opened map N+1's bans, so correcting N is only a
score edit while the WINNER stays the same. Flip the winner and the round that
followed was opened by the wrong side: it is scrapped and re-opened on the new
outcome -- but only while nobody has acted in it, because a ban already taken
there is history no correction may delete.

Runs the real pre-game loop (`test_pregame_loop`'s fixtures) up to the point
being corrected, so what is asserted is the room's actual state and not a
hand-placed one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    EncounterGameResultSource,
    EncounterGameState,
    MapPickSide,
    MapPoolEntryStatus,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.tournament.pick_ban import EncounterReadiness, PickBanEntry  # noqa: E402
from src.services.encounter.game_correction import game_correction_service  # noqa: E402
from src.services.encounter.map_report import map_report_service  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from tests._pregame_store import _Store  # noqa: E402
from tests.test_pregame_loop import _encounter, _hero_config, _map_config  # noqa: E402

ADMIN_ID = 909


class GameCorrectionTests(IsolatedAsyncioTestCase):
    """A bo3 whose first position is corrected, from four different states."""

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.map_config = _map_config()
        self.hero_config = _hero_config()
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

    # -- driving the room --------------------------------------------------
    async def map_state(self) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )

    async def hero_state(self) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.HERO, viewer_side=MapPickSide.HOME.value
        )

    async def ban_out_the_map_round(self) -> None:
        for _ in range(2):
            state = await self.map_state()
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], available[0], "ban"
            )

    async def ban_out_the_hero_round(self) -> None:
        for _ in range(4):
            state = await self.hero_state()
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.HERO, state["turn_side"], available[0], "ban"
            )

    async def game_id_at(self, position: int) -> int:
        state = await self.map_state()
        return next(game["id"] for game in state["games"] if game["position"] == position)

    async def claim(self, position: int, side: str, home_score: int, away_score: int) -> dict:
        return await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            game_id=await self.game_id_at(position),
            side=side,
            reporter_user_id=None,
            home_score=home_score,
            away_score=away_score,
        )

    async def play_position_one(self, home_score: int = 2, away_score: int = 1) -> None:
        """Map bans, hero bans, then an agreed result for position 1 -- the state
        every correction below starts from."""
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        for side in (MapPickSide.HOME.value, MapPickSide.AWAY.value):
            await self.claim(1, side, home_score, away_score)

    async def correct(self, position: int, home_score: int, away_score: int) -> dict:
        return await game_correction_service.correct(
            self.store,
            self.encounter,
            game_id=await self.game_id_at(position),
            home_score=home_score,
            away_score=away_score,
            actor_user_id=ADMIN_ID,
            reason="VOD review",
        )

    # -- case 2: the winner did not change ---------------------------------
    async def test_a_score_only_correction_leaves_the_next_round_standing(self) -> None:
        await self.play_position_one(2, 1)
        opened = await self.map_state()
        self.assertEqual(2, opened["current_round"])
        self.assertEqual(MapPickSide.HOME.value, opened["turn_side"], "home won map 1 and opens map 2")
        sequence_before = list(opened["sequence"])

        result = await self.correct(1, 3, 1)

        self.assertEqual([], result["rebuilt_rounds"])
        self.assertEqual(EncounterGameResultSource.ADMIN.value, result["game"]["result_source"])
        self.assertEqual((3, 1), (result["game"]["accepted_home_score"], result["game"]["accepted_away_score"]))
        self.assertEqual(2, result["game"]["result_version"], "the correction is the second write of this result")

        state = await self.map_state()
        self.assertEqual(sequence_before, state["sequence"], "round 2's steps are untouched")
        self.assertEqual(MapPickSide.HOME.value, state["turn_side"], "home still won map 1, so home still opens map 2")
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

    # -- case 3: the winner changed, nothing downstream started ------------
    async def test_flipping_the_winner_rebuilds_the_untouched_next_round(self) -> None:
        await self.play_position_one(2, 1)
        before = await self.map_state()
        self.assertEqual(["ban_home", "ban_away", "decider"], before["sequence"][-3:])

        result = await self.correct(1, 1, 2)

        self.assertEqual([2], result["rebuilt_rounds"])
        self.assertEqual((0, 1), (self.encounter.home_score, self.encounter.away_score))

        state = await self.map_state()
        self.assertEqual(2, state["current_round"], "round 2 is open again, not lost")
        # Away now won map 1, so `result_winner_first` hands away the first ban.
        self.assertEqual(["ban_away", "ban_home", "decider"], state["sequence"][-3:])
        self.assertEqual(6, len(state["sequence"]), "the scrapped round's tokens were replaced, not appended to")
        self.assertEqual(MapPickSide.AWAY.value, state["turn_side"])

        round_two = [entry for entry in self.store.all_of(PickBanEntry) if entry.round == 2]
        self.assertEqual(3, len(round_two), "round 2 offers its slot's three candidates again")
        self.assertTrue(all(entry.picked_by is None for entry in round_two))
        self.assertTrue(all(entry.action_index is None for entry in round_two))

    async def test_flipping_the_winner_is_refused_once_the_next_round_has_a_ban(self) -> None:
        await self.play_position_one(2, 1)
        state = await self.map_state()
        candidate = next(
            entry["item_id"]
            for entry in state["pool"]
            if entry["round"] == 2 and entry["status"] == MapPoolEntryStatus.AVAILABLE.value
        )
        await pick_ban_action_service.perform_pick_ban_action(
            self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], candidate, "ban"
        )

        with self.assertRaises(HTTPException) as caught:
            await self.correct(1, 1, 2)

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual(["downstream_started"], [item.code for item in caught.exception.detail])
        self.assertEqual(
            EncounterGameState.CONFIRMED.value,
            (await self.map_state())["games"][0]["state"],
            "the refusal changed nothing",
        )
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

    # -- case 1: never accepted at all -------------------------------------
    async def test_correcting_a_disputed_game_accepts_it_and_opens_the_next_round(self) -> None:
        await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.claim(1, MapPickSide.HOME.value, 2, 1)
        disputed = await self.claim(1, MapPickSide.AWAY.value, 0, 2)
        self.assertEqual(EncounterGameState.DISPUTED.value, disputed["game"]["state"])
        self.assertTrue((await self.map_state())["is_complete"], "a disputed position holds map 2 closed")

        result = await self.correct(1, 2, 1)

        self.assertEqual([], result["rebuilt_rounds"], "nothing downstream existed to rebuild")
        self.assertEqual(EncounterGameState.CONFIRMED.value, result["game"]["state"])
        self.assertEqual(EncounterGameResultSource.ADMIN.value, result["game"]["result_source"])
        self.assertEqual(1, result["game"]["result_version"], "the admin made the position's first result")
        self.assertEqual(
            [("home", 2, 1), ("away", 0, 2)],
            [(row["side"], row["home_score"], row["away_score"]) for row in result["game"]["reports"]],
            "both claims stand as the record of what was disputed",
        )

        state = await self.map_state()
        self.assertEqual(2, state["current_round"], "the admin's decision opened map 2's bans")
        self.assertEqual(MapPickSide.HOME.value, state["turn_side"])
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))


class MaplessGameTests(IsolatedAsyncioTestCase):
    """A freeplay position that has no map yet is not a game anybody played, so
    there is no result for an organizer to record on it either."""

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.encounter = _encounter()
        self.store.seed(self.encounter)
        self.store.seed(
            EncounterReadiness(encounter_id=self.encounter.id, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=self.encounter.id, side=MapPickSide.AWAY.value, ready_user_id=None),
        )

    async def test_a_planned_freeplay_position_cannot_be_admin_confirmed(self) -> None:
        # No map config at all: reading the room opens position 1 with no map on it.
        state = await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter.id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )
        self.assertIsNone(state["session"], "freeplay: there is no veto to run")
        self.assertEqual([(1, None, EncounterGameState.PLANNED.value)], [
            (game["position"], game["map_id"], game["state"]) for game in state["games"]
        ])

        with self.assertRaises(HTTPException) as caught:
            await game_correction_service.correct(
                self.store,
                self.encounter,
                game_id=state["games"][0]["id"],
                home_score=2,
                away_score=1,
                actor_user_id=ADMIN_ID,
                reason="VOD review",
            )

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual(["map_not_selected"], [item.code for item in caught.exception.detail])
        after = await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter.id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )
        self.assertEqual(
            [(1, EncounterGameState.PLANNED.value)],
            [(game["position"], game["state"]) for game in after["games"]],
            "nothing was accepted, so no second position opened",
        )
        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))
