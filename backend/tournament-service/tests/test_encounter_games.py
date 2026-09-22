"""``EncounterGameService``: who owns a series position and its accepted score.

Five properties, each one a rule the rest of the vertical leans on:

  * the map pick-ban opens the positions, and taking a pick back retires the
    position it opened (without touching the one that was already played);
  * freeplay opens exactly ONE position at a time, and stops at `best_of`
    or as soon as the series is mathematically decided;
  * the running series score is materialised onto the encounter only while the
    encounter is unofficial -- after finalize the official score is untouchable;
  * a draw consumes a position without being a win for anyone;
  * cancelling a confirmed position journals it and gives its win back.

Runs against the in-memory store from ``tests/_pregame_store.py`` -- the same
fake ``AsyncSession`` the pre-game loop suite uses -- so the writes are real
repository calls, not mocks.
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
    EncounterResultAuditAction,
    EncounterStatus,
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoSessionStatus,
    PickBanKind,
    VetoSeedSource,
)
from shared.domain.pick_ban_engine import SeriesScore  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from shared.models.tournament.encounter_report import EncounterMapReport  # noqa: E402
from shared.models.tournament.encounter_result_audit import EncounterResultAudit  # noqa: E402
from shared.models.tournament.pick_ban import PickBanEntry, PickBanSession  # noqa: E402
from src.services.encounter.games import encounter_game_service  # noqa: E402
from tests._pregame_store import _Store  # noqa: E402

HOME_TEAM, AWAY_TEAM = 10, 20


def _encounter(*, best_of: int = 3) -> Encounter:
    return Encounter(
        tournament_id=7,
        stage_id=None,
        stage_item_id=None,
        round=1,
        best_of=best_of,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_score=0,
        away_score=0,
        status=EncounterStatus.OPEN,
    )


class GameLifecycleTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.encounter = _encounter()
        self.store.seed(self.encounter)
        self.service = encounter_game_service

    # -- helpers ----------------------------------------------------------
    def _map_session(self, *picked_map_ids: int) -> PickBanSession:
        session = PickBanSession(
            encounter_id=self.encounter.id,
            kind=PickBanKind.MAP,
            config_id=None,
            first_side=MapPickSide.HOME,
            seed_source=VetoSeedSource.FALLBACK_HOME,
            resolved_sequence_json=[],
            status=MapVetoSessionStatus.ACTIVE,
        )
        self.store.seed(session)
        for index, map_id in enumerate(picked_map_ids):
            self.store.seed(
                PickBanEntry(
                    session_id=session.id,
                    item_id=map_id,
                    order=index,
                    action_index=index,
                    status=MapPoolEntryStatus.PICKED,
                    picked_by=MapPickSide.DECIDER,
                )
            )
        return session

    def _games(self, *, include_cancelled: bool = False) -> list[EncounterGame]:
        games = sorted(self.store.all_of(EncounterGame), key=lambda game: game.position)
        if include_cancelled:
            return games
        return [game for game in games if game.state != EncounterGameState.CANCELLED]

    def _audits(self) -> list[EncounterResultAudit]:
        return self.store.all_of(EncounterResultAudit)

    # -- the properties ---------------------------------------------------
    async def test_picks_create_awaiting_games_and_an_undone_pick_cancels_its_game(self) -> None:
        session = self._map_session(11, 22)

        games = await self.service.sync_games_with_picks(self.store, self.encounter, session)

        self.assertEqual([(1, 11), (2, 22)], [(game.position, game.map_id) for game in games])
        self.assertEqual(
            [EncounterGameState.AWAITING_RESULT, EncounterGameState.AWAITING_RESULT],
            [game.state for game in games],
        )

        # The second captain takes the pick back: the entry returns to the pool.
        second = self.store.all_of(PickBanEntry)[1]
        second.status = MapPoolEntryStatus.AVAILABLE
        second.action_index = None

        games = await self.service.sync_games_with_picks(self.store, self.encounter, session)

        self.assertEqual([(1, 11)], [(game.position, game.map_id) for game in games])
        self.assertEqual(EncounterGameState.AWAITING_RESULT, games[0].state, "position 1 is untouched")
        cancelled = [game for game in self._games(include_cancelled=True) if game.position == 2]
        self.assertEqual([EncounterGameState.CANCELLED], [game.state for game in cancelled])

    async def test_freeplay_opens_one_planned_game_at_a_time_until_the_series_is_complete(self) -> None:
        first = await self.service.ensure_freeplay_game(self.store, self.encounter)
        self.assertIsNotNone(first)
        self.assertEqual((1, EncounterGameState.PLANNED), (first.position, first.state))

        self.assertIs(first, await self.service.ensure_freeplay_game(self.store, self.encounter))
        self.assertEqual(1, len(self._games()), "an open position is never doubled up")

        await self.service.accept_result(
            self.store,
            self.encounter,
            first,
            home_score=2,
            away_score=0,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )
        second = await self.service.ensure_freeplay_game(self.store, self.encounter)
        self.assertEqual((2, EncounterGameState.PLANNED), (second.position, second.state))

        await self.service.accept_result(
            self.store,
            self.encounter,
            second,
            home_score=2,
            away_score=0,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )
        self.assertIsNone(
            await self.service.ensure_freeplay_game(self.store, self.encounter),
            "2:0 in a Bo3 decides the series; the third map is never opened",
        )
        self.assertEqual(2, len(self._games()))

    async def test_accept_result_materialises_live_score_only_before_official_finalize(self) -> None:
        session = self._map_session(11, 22)
        games = await self.service.sync_games_with_picks(self.store, self.encounter, session)

        confirmed = await self.service.accept_result(
            self.store,
            self.encounter,
            games[0],
            home_score=2,
            away_score=1,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )

        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))
        self.assertEqual(EncounterGameState.CONFIRMED, confirmed.state)
        self.assertEqual(1, confirmed.result_version)
        self.assertIsNotNone(confirmed.confirmed_at)
        audit = self._audits()[-1]
        self.assertEqual(EncounterResultAuditAction.GAME_CONFIRM, audit.action)
        self.assertEqual((confirmed.id, 1), (audit.game_id, audit.game_result_version))
        self.assertEqual((None, None), (audit.home_score_before, audit.away_score_before))
        self.assertEqual((2, 1), (audit.home_score_after, audit.away_score_after))

        # Official finalize happened and wrote its own score; the live path is now
        # a read-only observer.
        self.encounter.status = EncounterStatus.COMPLETED
        self.encounter.home_score, self.encounter.away_score = 0, 0

        await self.service.accept_result(
            self.store,
            self.encounter,
            games[1],
            home_score=0,
            away_score=2,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )

        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))
        self.assertEqual(
            {"home_score": 0, "away_score": 0},
            self.service.serialize_series(self.encounter, self._games())["official"],
        )

    async def test_a_draw_counts_as_played_but_not_as_a_win(self) -> None:
        session = self._map_session(11)
        games = await self.service.sync_games_with_picks(self.store, self.encounter, session)

        await self.service.accept_result(
            self.store,
            self.encounter,
            games[0],
            home_score=1,
            away_score=1,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )

        live = self._games()
        self.assertEqual(SeriesScore(0, 0, 1), self.service.live_score(live))
        series = self.service.serialize_series(self.encounter, live)
        self.assertEqual((0, 0, 1), (series["home_wins"], series["away_wins"], series["played"]))
        self.assertFalse(series["complete"])
        self.assertIsNone(series["official"], "an unofficial encounter has no official score to show")
        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))

    async def test_cancelling_a_confirmed_game_writes_a_cancel_audit_and_rematerialises(self) -> None:
        session = self._map_session(11, 22)
        games = await self.service.sync_games_with_picks(self.store, self.encounter, session)
        for game in games:
            await self.service.accept_result(
                self.store,
                self.encounter,
                game,
                home_score=2,
                away_score=0,
                source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
                actor_user_id=None,
            )
        self.assertEqual((2, 0), (self.encounter.home_score, self.encounter.away_score))

        await self.service.cancel_games(
            self.store,
            self.encounter,
            [games[1]],
            actor_user_id=99,
            reason="admin voided the map",
        )

        self.assertEqual(EncounterGameState.CANCELLED, games[1].state)
        self.assertEqual(
            (1, 0),
            (self.encounter.home_score, self.encounter.away_score),
            "the cancelled position gives its win back",
        )
        audit = self._audits()[-1]
        self.assertEqual(EncounterResultAuditAction.GAME_CANCEL, audit.action)
        self.assertEqual(games[1].id, audit.game_id)
        self.assertEqual(99, audit.actor_user_id)
        self.assertEqual("admin voided the map", audit.reason)
        self.assertEqual((2, 0), (audit.home_score_before, audit.away_score_before))
        self.assertEqual((2, 0), (audit.home_score_after, audit.away_score_after))
        self.assertEqual([1], [game.position for game in self._games()])


class GameSerializationTests(IsolatedAsyncioTestCase):
    async def test_serialize_puts_home_before_away_and_iso_formats_the_confirmation(self) -> None:
        store = _Store()
        encounter = _encounter()
        store.seed(encounter)
        game = EncounterGame(
            encounter_id=encounter.id,
            position=1,
            map_id=11,
            state=EncounterGameState.AWAITING_RESULT,
        )
        store.seed(game)
        reports = [
            EncounterMapReport(game_id=game.id, side="away", home_score=1, away_score=2),
            EncounterMapReport(game_id=game.id, side="home", home_score=1, away_score=2),
        ]
        store.seed(*reports)

        payload = encounter_game_service.serialize(game, reports)
        self.assertEqual(["home", "away"], [report["side"] for report in payload["reports"]])
        self.assertIsNone(payload["confirmed_at"])
        self.assertIsNone(payload["result_source"])

        await encounter_game_service.accept_result(
            store,
            encounter,
            game,
            home_score=1,
            away_score=2,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )
        payload = encounter_game_service.serialize(game, reports)
        self.assertEqual(EncounterGameState.CONFIRMED.value, payload["state"])
        self.assertEqual(EncounterGameResultSource.CAPTAIN_AGREEMENT.value, payload["result_source"])
        self.assertEqual(game.confirmed_at.isoformat(), payload["confirmed_at"])
