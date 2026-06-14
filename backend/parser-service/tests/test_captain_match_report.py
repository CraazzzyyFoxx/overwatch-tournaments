"""Tests for captain encounter-level match report submission.

Manual captain reports update Encounter only. Per-map Match rows are created by
log ingestion, not by the report flow.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

captain_service = importlib.import_module("src.services.encounter.captain")
enums = importlib.import_module("shared.core.enums")


def _mk_user(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _mk_encounter(
    *,
    enc_id: int = 10,
    tournament_id: int = 1,
    home_captain_player_id: int = 100,
    away_captain_player_id: int = 200,
) -> SimpleNamespace:
    home_team = SimpleNamespace(id=1, captain_id=home_captain_player_id)
    away_team = SimpleNamespace(id=2, captain_id=away_captain_player_id)
    return SimpleNamespace(
        id=enc_id,
        tournament_id=tournament_id,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        home_team=home_team,
        away_team=away_team,
        stage=SimpleNamespace(stage_type="round_robin"),
        result_status=enums.EncounterResultStatus.NONE,
        home_score=0,
        away_score=0,
        closeness=None,
        submitted_by_id=None,
        submitted_at=None,
        confirmed_by_id=None,
        confirmed_at=None,
        challonge_id=None,
    )


def _mk_session(
    encounter: SimpleNamespace | None,
    captain_player_ids: list[int],
) -> SimpleNamespace:
    execute_count = 0

    async def fake_execute(_query):
        nonlocal execute_count
        execute_count += 1

        if execute_count == 1:
            result_mock = Mock()
            result_mock.scalar_one_or_none.return_value = encounter
            return result_mock

        if execute_count == 2:
            scalars_mock = Mock()
            scalars_mock.all.return_value = [
                SimpleNamespace(player_id=pid) for pid in captain_player_ids
            ]
            result_mock = Mock()
            result_mock.scalars.return_value = scalars_mock
            return result_mock

        result_mock = Mock()
        result_mock.scalar_one_or_none.return_value = None
        scalars_mock = Mock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        return result_mock

    added: list[object] = []

    return SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        add=lambda obj: added.append(obj),
        _added=added,
    )


class CaptainMatchReportValidation(IsolatedAsyncioTestCase):
    async def test_rejects_closeness_out_of_range(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        user = _mk_user()
        with self.assertRaises(HTTPException) as ctx:
            await captain_service.submit_match_report(
                session,
                user,
                encounter_id=10,
                home_score=2,
                away_score=1,
                closeness_stars=6,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_non_captain_gets_forbidden(self) -> None:
        encounter = _mk_encounter(
            home_captain_player_id=100, away_captain_player_id=200
        )
        session = _mk_session(encounter, [999])
        user = _mk_user()
        with self.assertRaises(HTTPException) as ctx:
            await captain_service.submit_match_report(
                session,
                user,
                encounter_id=10,
                home_score=2,
                away_score=1,
                closeness_stars=3,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_updates_encounter_result_without_creating_matches(self) -> None:
        encounter = _mk_encounter()
        session = _mk_session(encounter, [100])
        user = _mk_user()

        with patch.object(
            captain_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            AsyncMock(),
        ) as enqueue_recalc:
            await captain_service.submit_match_report(
                session,
                user,
                encounter_id=10,
                home_score=2,
                away_score=1,
                closeness_stars=4,
            )

        enqueue_recalc.assert_awaited_once_with(encounter.tournament_id)
        self.assertEqual(encounter.home_score, 2)
        self.assertEqual(encounter.away_score, 1)
        self.assertEqual(encounter.closeness, 4 / 5)
        self.assertEqual(
            encounter.result_status, enums.EncounterResultStatus.PENDING_CONFIRMATION
        )
        self.assertEqual(encounter.submitted_by_id, 100)
        self.assertEqual(session._added, [])

    async def test_does_not_delete_existing_matches(self) -> None:
        encounter = _mk_encounter()
        session = _mk_session(encounter, [100])
        user = _mk_user()

        with patch.object(
            captain_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            AsyncMock(),
        ):
            await captain_service.submit_match_report(
                session,
                user,
                encounter_id=10,
                home_score=1,
                away_score=1,
                closeness_stars=2,
            )

        executed_queries = [
            str(call.args[0]).lower() for call in session.execute.await_args_list
        ]
        self.assertFalse(
            any("delete" in q and "match" in q for q in executed_queries),
            f"did not expect DELETE against Match table, got: {executed_queries}",
        )

    async def test_same_linked_player_cannot_confirm_own_submission(self) -> None:
        encounter = _mk_encounter()
        encounter.result_status = enums.EncounterResultStatus.PENDING_CONFIRMATION
        encounter.submitted_by_id = 100
        session = _mk_session(encounter, [100])
        user = _mk_user()

        with self.assertRaises(HTTPException) as ctx:
            await captain_service.confirm_result(session, user, encounter_id=10)

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_confirm_stores_linked_player_id(self) -> None:
        encounter = _mk_encounter()
        encounter.result_status = enums.EncounterResultStatus.PENDING_CONFIRMATION
        encounter.submitted_by_id = 100
        session = _mk_session(encounter, [200])
        user = _mk_user()

        with patch.object(
            captain_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            AsyncMock(),
        ) as enqueue_recalc:
            await captain_service.confirm_result(session, user, encounter_id=10)

        enqueue_recalc.assert_awaited_once_with(encounter.tournament_id)
        self.assertEqual(encounter.confirmed_by_id, 200)
        self.assertEqual(encounter.status, enums.EncounterStatus.COMPLETED)
