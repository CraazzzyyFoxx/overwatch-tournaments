"""Correcting a contested map, and refusing to correct a settled one.

A position's result is accepted once, on its ``EncounterGame``, the moment both
captains' claims agree. While they disagree the game sits ``disputed`` and a
corrected pair of claims still resolves it -- that is how captains get out of a
typo without an organizer. Once the game is ``confirmed`` the door closes: a new
claim is a 409 ``result_locked`` and changing the score is the admin correction
command, with a reason (spec §6.5).

The old failure this replaces: the series score was frozen behind
``if not already_played``, so a 2:0 corrected to 0:2 left the encounter reading
1:0 for the wrong team. The score is now derived from the confirmed games rather
than incremented, so it cannot drift from them at all.
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
    EncounterStatus,
    MapPickSide,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from shared.models.tournament.encounter_report import EncounterMapReport  # noqa: E402
from src.services.encounter.map_report import map_report_service  # noqa: E402
from tests._pregame_store import _Store  # noqa: E402

HOME_TEAM, AWAY_TEAM = 1, 2
MAP_ID = 77


class DisputedMapIsCorrectedByAgreeingClaims(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.encounter = Encounter(
            tournament_id=1,
            stage_id=None,
            stage_item_id=None,
            round=1,
            best_of=3,
            home_team_id=HOME_TEAM,
            away_team_id=AWAY_TEAM,
            home_score=0,
            away_score=0,
        )
        self.encounter.status = EncounterStatus.OPEN
        self.game = EncounterGame(
            encounter_id=1,
            position=1,
            map_id=MAP_ID,
            state=EncounterGameState.AWAITING_RESULT,
        )
        self.store.seed(self.encounter, self.game)
        self.game.encounter_id = self.encounter.id

    async def claim(self, side: str, home_score: int, away_score: int) -> dict:
        return await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            game_id=self.game.id,
            side=side,
            reporter_user_id=99,
            home_score=home_score,
            away_score=away_score,
        )

    async def test_a_disputed_game_accepts_a_corrected_pair_of_claims(self) -> None:
        await self.claim(MapPickSide.HOME.value, 2, 0)
        disputed = await self.claim(MapPickSide.AWAY.value, 0, 2)
        self.assertTrue(disputed["disputed"])
        self.assertEqual(EncounterGameState.DISPUTED, self.game.state)
        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))

        # Home concedes the typo: the two claims now agree, and that resolves it.
        resolved = await self.claim(MapPickSide.HOME.value, 0, 2)

        self.assertTrue(resolved["resolved"])
        self.assertEqual(EncounterGameState.CONFIRMED, self.game.state)
        self.assertEqual((0, 2), (self.game.accepted_home_score, self.game.accepted_away_score))
        self.assertEqual(EncounterGameResultSource.CAPTAIN_AGREEMENT, self.game.result_source)
        # Pre-fix this read (1, 0): the row was corrected, the series was not.
        self.assertEqual((0, 1), (self.encounter.home_score, self.encounter.away_score))
        # One claim per side -- the corrected one replaced home's, never added to it.
        self.assertEqual(2, len(self.store.all_of(EncounterMapReport)))

    async def test_a_confirmed_game_refuses_a_correction_by_claim(self) -> None:
        await self.claim(MapPickSide.HOME.value, 2, 0)
        await self.claim(MapPickSide.AWAY.value, 2, 0)
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

        with self.assertRaises(HTTPException) as caught:
            await self.claim(MapPickSide.HOME.value, 0, 2)

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual(["result_locked"], [item.code for item in caught.exception.detail])
        self.assertEqual((2, 0), (self.game.accepted_home_score, self.game.accepted_away_score))
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))
        self.assertEqual(1, self.game.result_version, "the refused claim did not bump the version")

    async def test_a_claim_for_another_encounters_game_is_a_404(self) -> None:
        other = EncounterGame(encounter_id=999, position=1, map_id=MAP_ID, state=EncounterGameState.AWAITING_RESULT)
        self.store.seed(other)

        with self.assertRaises(HTTPException) as caught:
            await map_report_service.submit_map_report(
                self.store,
                self.encounter,
                game_id=other.id,
                side=MapPickSide.HOME.value,
                reporter_user_id=99,
                home_score=2,
                away_score=0,
            )

        self.assertEqual(404, caught.exception.status_code)

    async def test_a_position_with_no_map_yet_cannot_be_reported(self) -> None:
        planned = EncounterGame(encounter_id=self.encounter.id, position=2, state=EncounterGameState.PLANNED)
        self.store.seed(planned)

        with self.assertRaises(HTTPException) as caught:
            await map_report_service.submit_map_report(
                self.store,
                self.encounter,
                game_id=planned.id,
                side=MapPickSide.HOME.value,
                reporter_user_id=99,
                home_score=2,
                away_score=0,
            )

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual(["map_not_selected"], [item.code for item in caught.exception.detail])
