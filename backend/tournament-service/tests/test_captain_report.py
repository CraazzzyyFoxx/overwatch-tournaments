"""Tests for per-captain encounter report submission in tournament-service."""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

captain_service = importlib.import_module("src.services.encounter.captain")
enums = importlib.import_module("shared.core.enums")


@contextmanager
def assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - inspect status_code attribute
        status_code = getattr(exc, "status_code", None)
        test_case.assertEqual(status_code, expected_status)
        return
    test_case.fail(f"expected an exception with status_code {expected_status}")


def _mk_user(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _mk_report(*, team_id: int, home: int, away: int, closeness: int, report_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=report_id,
        team_id=team_id,
        reporter_user_id=None,
        home_score=home,
        away_score=away,
        closeness=closeness,
        map_codes=[],
    )


def _mk_encounter(
    *,
    result_status=enums.EncounterResultStatus.NONE,
    captain_reports: list | None = None,
    home_captain_player_id: int = 100,
    away_captain_player_id: int = 200,
) -> SimpleNamespace:
    home_team = SimpleNamespace(id=1, captain_id=home_captain_player_id)
    away_team = SimpleNamespace(id=2, captain_id=away_captain_player_id)
    return SimpleNamespace(
        id=10,
        tournament_id=1,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        home_team=home_team,
        away_team=away_team,
        stage=SimpleNamespace(stage_type="round_robin"),
        result_status=result_status,
        status=enums.EncounterStatus.OPEN,
        home_score=0,
        away_score=0,
        closeness=None,
        submitted_by_id=None,
        submitted_at=None,
        confirmed_by_id=None,
        confirmed_at=None,
        captain_reports=captain_reports if captain_reports is not None else [],
    )


def _mk_session(
    encounter: SimpleNamespace | None,
    captain_player_ids: list[int],
    *,
    picked_rows: list[tuple[int, int]] | None = None,
) -> SimpleNamespace:
    linked_player_id = captain_player_ids[0] if captain_player_ids else None
    execute_count = 0
    rows = picked_rows or []

    async def fake_execute(_query):
        nonlocal execute_count
        execute_count += 1

        if execute_count == 1:
            result_mock = Mock()
            result_mock.scalar_one_or_none.return_value = encounter
            return result_mock

        if execute_count == 2:
            result_mock = Mock()
            player = SimpleNamespace(id=linked_player_id) if linked_player_id is not None else None
            result_mock.scalar_one_or_none.return_value = player
            return result_mock

        # Any later execute: delete(codes) is ignored; the picked-pool select
        # reads .all(); challonge resolve reads .all() (empty -> not linked).
        result_mock = Mock()
        result_mock.scalar_one_or_none.return_value = None
        scalars_mock = Mock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        result_mock.all.return_value = list(rows)
        return result_mock

    added: list[object] = []

    return SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        flush=AsyncMock(),
        add=lambda obj: added.append(obj),
        _added=added,
    )


class CaptainReportValidation(IsolatedAsyncioTestCase):
    async def test_rejects_closeness_out_of_range(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        with assert_http_status(self, 422):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=11
            )

    async def test_rejects_negative_score(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        with assert_http_status(self, 422):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=-1, away_score=1, closeness=5
            )

    async def test_rejects_duplicate_map_index(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        with assert_http_status(self, 422):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=5,
                map_codes=[(1, "AAA"), (1, "BBB")],
            )

    async def test_non_captain_forbidden(self) -> None:
        session = _mk_session(_mk_encounter(), [999])
        with assert_http_status(self, 403):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=5
            )

    async def test_confirmed_encounter_rejects_report(self) -> None:
        encounter = _mk_encounter(result_status=enums.EncounterResultStatus.CONFIRMED)
        session = _mk_session(encounter, [100])
        with assert_http_status(self, 400):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=5
            )


class CaptainReportFlow(IsolatedAsyncioTestCase):
    async def test_first_report_sets_pending_no_closeness(self) -> None:
        encounter = _mk_encounter()
        session = _mk_session(encounter, [100])  # home captain
        with patch.object(captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc:
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=7
            )
        recalc.assert_awaited_once_with(session, encounter.tournament_id)
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.PENDING_CONFIRMATION)
        self.assertIsNone(encounter.closeness)
        self.assertEqual(encounter.submitted_by_id, 100)
        self.assertEqual(len(encounter.captain_reports), 1)
        self.assertEqual(encounter.captain_reports[0].team_id, 1)
        session.commit.assert_awaited_once()

    async def test_second_matching_report_auto_confirms_with_avg_closeness(self) -> None:
        existing = _mk_report(team_id=1, home=2, away=1, closeness=8)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        encounter.submitted_by_id = 100
        session = _mk_session(encounter, [200])  # away captain

        async def fake_finalize(*_args, **kwargs):
            encounter.status = enums.EncounterStatus.COMPLETED
            encounter.result_status = kwargs["result_status"]
            encounter.confirmed_by_id = kwargs["confirmed_by_id"]
            encounter.home_score = kwargs["home_score"]
            encounter.away_score = kwargs["away_score"]
            return SimpleNamespace(encounter=encounter, advanced_encounters=[])

        with (
            patch.object(captain_service, "finalize_encounter_score", AsyncMock(side_effect=fake_finalize)) as fin,
            patch.object(captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc,
            patch.object(captain_service, "_enqueue_encounter_completed", AsyncMock()) as completed,
        ):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=6
            )

        fin.assert_awaited_once()
        recalc.assert_awaited_once_with(session, encounter.tournament_id)
        completed.assert_awaited_once_with(session, encounter)
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.CONFIRMED)
        self.assertEqual(encounter.confirmed_by_id, 200)
        # avg(8, 6) / 10 == 0.7
        self.assertAlmostEqual(encounter.closeness, 0.7)
        session.commit.assert_awaited_once()

    async def test_second_mismatching_report_disputes(self) -> None:
        existing = _mk_report(team_id=1, home=2, away=1, closeness=8)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        session = _mk_session(encounter, [200])  # away captain
        with (
            patch.object(captain_service, "finalize_encounter_score", AsyncMock()) as fin,
            patch.object(captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc,
        ):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=3, away_score=0, closeness=4
            )
        fin.assert_not_awaited()
        recalc.assert_awaited_once_with(session, encounter.tournament_id)
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.DISPUTED)
        self.assertIsNone(encounter.closeness)

    async def test_upsert_replaces_own_report(self) -> None:
        existing = _mk_report(team_id=1, home=1, away=2, closeness=3)
        existing.map_codes = [SimpleNamespace(map_index=1, code="OLD", map_id=None)]
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        session = _mk_session(encounter, [100])  # home captain re-submits
        with patch.object(captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=0, closeness=9
            )
        self.assertEqual(len(encounter.captain_reports), 1)
        self.assertEqual(existing.home_score, 2)
        self.assertEqual(existing.away_score, 0)
        self.assertEqual(existing.closeness, 9)
        self.assertEqual(existing.map_codes, [])
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.PENDING_CONFIRMATION)

    async def test_map_codes_resolve_map_id_from_pool_softly(self) -> None:
        encounter = _mk_encounter()
        # Picked pool: order 1 -> map 55, order 2 -> map 66. Index 3 has no pick.
        session = _mk_session(encounter, [100], picked_rows=[(1, 55), (2, 66)])
        with patch.object(captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=7,
                map_codes=[(1, "AAA"), (2, "BBB"), (3, "CCC"), (4, "  ")],
            )
        report = encounter.captain_reports[0]
        by_index = {mc.map_index: mc for mc in report.map_codes}
        # blank code (index 4) is skipped
        self.assertEqual(set(by_index), {1, 2, 3})
        self.assertEqual(by_index[1].map_id, 55)
        self.assertEqual(by_index[2].map_id, 66)
        self.assertIsNone(by_index[3].map_id)  # soft: index beyond picks
        self.assertEqual(by_index[1].code, "AAA")
