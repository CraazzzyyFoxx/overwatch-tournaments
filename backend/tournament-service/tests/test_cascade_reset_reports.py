"""A cascade reset must void the whole old matchup, not just two numbers.

Review item 7: when a corrected upstream result swaps a team into an encounter
that was already played, the old pairing's captain reports, ``ended_at``,
``current_map_index`` and veto session all survived — so the replaced opponent's
report could pair with the NEW team's report and auto-confirm a series nobody
played. An admin REOPEN of the same matchup keeps its reports (they are still
evidence about the same two teams).

Also pins review §6's "Завершение BoN": a captain report is a FINAL series
score, so it has to be one the configured best-of can actually produce.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

advancement = importlib.import_module("shared.services.bracket.advancement")
captain_service = importlib.import_module("src.services.encounter.captain")
pick_ban_session = importlib.import_module("src.services.encounter.pick_ban_session")
enums = importlib.import_module("shared.core.enums")
PickBanKind = enums.PickBanKind


@contextmanager
def assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - inspect status_code attribute
        test_case.assertEqual(expected_status, getattr(exc, "status_code", None))
        return
    test_case.fail(f"expected an exception with status_code {expected_status}")


# ---------------------------------------------------------------------------
# Cascade reset clears the old matchup's artefacts
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list | None = None) -> None:
        self._rows = rows or []

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return list(self._rows)


class _ResetSession:
    def __init__(
        self,
        *,
        confirmed: list[tuple[int, int]] | None = None,
        games: list | None = None,
    ) -> None:
        self.statements: list[str] = []
        self.added: list = []
        # ``(accepted_home_score, accepted_away_score)`` per CONFIRMED game --
        # what a REOPEN re-derives the live series score from.
        self.confirmed = confirmed or []
        # The live game ROWS a cascade loads to cancel one by one.
        self.games = games or []

    async def execute(self, statement):
        self.statements.append(str(statement))
        if "SELECT tournament.encounter_game.accepted_home_score" in str(statement):
            return _Result(list(self.confirmed))
        if "FROM tournament.encounter_game" in str(statement):
            return _Result(list(self.games))
        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def get(self, _model, _pk, **_kwargs):  # pragma: no cover - no links here
        return None

    def deleted_captain_reports(self) -> bool:
        return any("DELETE FROM tournament.encounter_captain_report" in s for s in self.statements)

    def loaded_live_games(self) -> bool:
        return any(s.startswith("SELECT tournament.encounter_game.id") for s in self.statements)

    def audits(self, action) -> list:
        return [row for row in self.added if getattr(row, "action", None) == action]


def _live_game(game_id: int, state, scores: tuple[int | None, int | None] = (None, None)):
    return SimpleNamespace(
        id=game_id,
        state=state,
        accepted_home_score=scores[0],
        accepted_away_score=scores[1],
        result_version=1,
    )


def _played_encounter() -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.CONFIRMED,
        home_score=2,
        away_score=0,
        confirmed_at=datetime(2026, 9, 1, tzinfo=UTC),
        closeness=0.7,
        ended_at=datetime(2026, 9, 1, tzinfo=UTC),
        current_map_index=3,
    )


class CascadeResetClearsOldMatchup(IsolatedAsyncioTestCase):
    async def test_cascade_deletes_captain_reports_and_clears_series_progress(self) -> None:
        session = _ResetSession()
        encounter = _played_encounter()

        await advancement.reset_encounter_result(session, encounter)

        self.assertTrue(session.deleted_captain_reports())
        self.assertIsNone(encounter.ended_at)
        self.assertIsNone(encounter.current_map_index)
        self.assertEqual((0, 0), (encounter.home_score, encounter.away_score))
        self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)

    async def test_cascade_cancels_the_old_pairings_games_and_journals_each_one(self) -> None:
        """The matchup changed, so a position the REPLACED team played is not a
        position of this encounter any more. Leaving one confirmed would
        re-materialise its win onto the new pairing on the next live read -- and
        dropping a confirmed game's wins IS a score change, so it owes the journal
        a row naming the game (spec §5.1), which a bulk UPDATE could never write.
        """
        confirmed = _live_game(1, enums.EncounterGameState.CONFIRMED, (2, 1))
        unplayed = _live_game(2, enums.EncounterGameState.AWAITING_RESULT)
        session = _ResetSession(games=[confirmed, unplayed])
        encounter = _played_encounter()

        await advancement.reset_encounter_result(session, encounter)

        self.assertEqual(enums.EncounterGameState.CANCELLED, confirmed.state)
        self.assertEqual(enums.EncounterGameState.CANCELLED, unplayed.state)
        cancels = session.audits(enums.EncounterResultAuditAction.GAME_CANCEL)
        self.assertEqual(1, len(cancels), "the cancelled confirmed game was not journalled")
        self.assertEqual(confirmed.id, cancels[0].game_id)
        self.assertEqual((2, 1), (cancels[0].home_score_before, cancels[0].away_score_before))
        self.assertEqual("cascade_reset", cancels[0].reason)
        self.assertEqual((0, 0), (encounter.home_score, encounter.away_score))

    async def test_admin_reopen_keeps_the_reports(self) -> None:
        """Same two teams, only the result reopened: the reports are still a
        valid statement about THIS matchup."""
        session = _ResetSession()
        encounter = _played_encounter()

        await advancement.reset_encounter_result(
            session,
            encounter,
            action=enums.EncounterResultAuditAction.REOPEN,
            actor_user_id=1,
        )

        self.assertFalse(session.deleted_captain_reports())
        self.assertFalse(session.loaded_live_games())
        self.assertIsNotNone(encounter.ended_at)
        self.assertEqual(3, encounter.current_map_index)

    async def test_admin_reopen_re_materialises_the_live_score_from_the_confirmed_games(self) -> None:
        """A reopen un-officialises the result; it does not un-play the maps.
        Zeroing the score would make the room disagree with every game row it
        renders, and the next captain claim would count from the wrong base."""
        session = _ResetSession(confirmed=[(2, 1), (0, 3), (1, 1)])
        encounter = _played_encounter()

        await advancement.reset_encounter_result(
            session,
            encounter,
            action=enums.EncounterResultAuditAction.REOPEN,
            actor_user_id=1,
        )

        # One win each; the draw played a position without being a win.
        self.assertEqual((1, 1), (encounter.home_score, encounter.away_score))

    async def test_admin_reopen_of_a_series_with_no_confirmed_game_reads_zero(self) -> None:
        session = _ResetSession(confirmed=[])
        encounter = _played_encounter()

        await advancement.reset_encounter_result(
            session,
            encounter,
            action=enums.EncounterResultAuditAction.REOPEN,
            actor_user_id=1,
        )

        self.assertEqual((0, 0), (encounter.home_score, encounter.away_score))


class CascadeResetClearsVeto(IsolatedAsyncioTestCase):
    """``sync_pick_ban_session_after_team_change`` refused to reset a session
    with a played map -- which is exactly the stale state a cascade leaves,
    since the cascade cancels the old pairing's games first."""

    async def _sync(self, *, game_state) -> AsyncMock:
        encounter = SimpleNamespace(id=500, home_team_id=10, away_team_id=20, home_score=0, away_score=0)
        game = SimpleNamespace(id=700, encounter_id=500, position=1, state=game_state)
        session = SimpleNamespace()
        reset = AsyncMock()
        with (
            patch.object(
                pick_ban_session.pick_ban_session_service,
                "get_pick_ban_session",
                AsyncMock(return_value=SimpleNamespace(id=900)),
            ),
            patch.object(
                pick_ban_session.pick_ban_session_service.games,
                "list_games",
                AsyncMock(return_value=[] if game_state is None else [game]),
            ),
            patch.object(pick_ban_session.pick_ban_session_service, "reset_pick_ban_session", reset),
        ):
            await pick_ban_session.pick_ban_session_service.sync_pick_ban_session_after_team_change(
                session, encounter, PickBanKind.MAP
            )
        return reset

    async def test_a_cancelled_or_unplayed_position_is_reset(self) -> None:
        reset = await self._sync(game_state=enums.EncounterGameState.AWAITING_RESULT)
        reset.assert_awaited_once()

    async def test_no_games_at_all_is_reset(self) -> None:
        reset = await self._sync(game_state=None)
        reset.assert_awaited_once()

    async def test_a_confirmed_position_is_left_alone(self) -> None:
        reset = await self._sync(game_state=enums.EncounterGameState.CONFIRMED)
        reset.assert_not_awaited()


# ---------------------------------------------------------------------------
# A captain report must be a valid FINAL score for the configured best-of
# ---------------------------------------------------------------------------


def _encounter(best_of: int = 3) -> SimpleNamespace:
    home_team = SimpleNamespace(id=1, captain_id=100)
    away_team = SimpleNamespace(id=2, captain_id=200)
    return SimpleNamespace(
        id=10,
        tournament_id=1,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        home_team=home_team,
        away_team=away_team,
        stage_id=1,
        stage=SimpleNamespace(stage_type="round_robin"),
        result_status=enums.EncounterResultStatus.NONE,
        status=enums.EncounterStatus.OPEN,
        best_of=best_of,
        home_score=0,
        away_score=0,
        closeness=None,
        confirmed_at=None,
        captain_reports=[],
    )


def _session(encounter: SimpleNamespace) -> SimpleNamespace:
    """The three reads ``submit_captain_report`` makes before its Bo-N gate, in
    order: the encounter load, the stage (preview gate) and the linked player."""
    execute_count = 0
    added: list = []

    async def fake_execute(_query):
        nonlocal execute_count
        execute_count += 1
        result = Mock()
        scalars = Mock()
        scalars.all.return_value = []
        result.scalars.return_value = scalars
        result.unique.return_value = result
        result.all.return_value = []
        if execute_count == 1:
            scalars.first.return_value = encounter
        elif execute_count == 2:
            scalars.first.return_value = SimpleNamespace(id=100)  # home captain
        else:
            scalars.first.return_value = None
        return result

    async def fake_get(model, _pk):
        if model.__name__ == "Stage":
            return SimpleNamespace(is_published=True)
        raise AssertionError(f"unexpected get() model: {model}")

    return SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        get=AsyncMock(side_effect=fake_get),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        flush=AsyncMock(),
        add=added.append,
        _added=added,
    )


class CaptainFinalScoreMustEndTheSeries(IsolatedAsyncioTestCase):
    async def _submit(self, encounter, home_score: int, away_score: int) -> None:
        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.captain_service.submit_captain_report(
                _session(encounter),
                SimpleNamespace(id=1),
                10,
                home_score=home_score,
                away_score=away_score,
                closeness=5,
            )

    async def test_bo3_cannot_end_one_nil(self) -> None:
        encounter = _encounter(best_of=3)
        with assert_http_status(self, 400):
            await self._submit(encounter, 1, 0)
        self.assertEqual([], encounter.captain_reports)

    async def test_bo3_cannot_be_won_three_nil(self) -> None:
        encounter = _encounter(best_of=3)
        with assert_http_status(self, 400):
            await self._submit(encounter, 3, 0)
        self.assertEqual([], encounter.captain_reports)

    async def test_bo3_two_nil_is_accepted(self) -> None:
        encounter = _encounter(best_of=3)

        await self._submit(encounter, 2, 0)

        self.assertEqual(1, len(encounter.captain_reports))
        self.assertEqual((2, 0), (encounter.captain_reports[0].home_score, encounter.captain_reports[0].away_score))
        self.assertEqual(enums.EncounterResultStatus.PENDING_CONFIRMATION, encounter.result_status)
