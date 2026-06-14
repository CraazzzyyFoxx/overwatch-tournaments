"""P0 pack: tests for bulk_update_encounters.

Verifies the critical property for 40+ team tournaments: one standings
recalc per tournament, not per encounter.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

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

encounter_service = importlib.import_module("src.services.admin.encounter")
admin_schemas = importlib.import_module("src.schemas.admin.encounter")
enums = importlib.import_module("shared.core.enums")


def _mk_encounter(*, enc_id: int, tournament_id: int, initial_status: str = "open"):
    return SimpleNamespace(
        id=enc_id,
        tournament_id=tournament_id,
        home_team_id=enc_id * 10,
        away_team_id=enc_id * 10 + 1,
        home_score=0,
        away_score=0,
        status=enums.EncounterStatus(initial_status),
    )


def _mk_session(encounters: list) -> SimpleNamespace:
    async def fake_execute(_query):
        result_mock = Mock()
        scalars_mock = Mock()
        scalars_mock.all.return_value = encounters
        result_mock.scalars.return_value = scalars_mock
        return result_mock

    return SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        commit=AsyncMock(),
    )


class BulkUpdateTests(IsolatedAsyncioTestCase):
    async def test_bulk_status_single_recalc_per_tournament(self) -> None:
        """20 encounters in 1 tournament → 1 recalc call, not 20."""
        encounters = [_mk_encounter(enc_id=i, tournament_id=42) for i in range(1, 21)]
        session = _mk_session(encounters)

        enqueue_mock = AsyncMock(return_value=True)
        advance_mock = AsyncMock()

        with patch.object(
            encounter_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            enqueue_mock,
        ), patch(
            "shared.services.bracket.advancement.advance_winner",
            advance_mock,
        ):
            result = await encounter_service.bulk_update_encounters(
                session,
                admin_schemas.BulkEncounterUpdate(
                    encounter_ids=[e.id for e in encounters],
                    status="completed",
                ),
            )

        # 20 encounters all set to COMPLETED
        for encounter in encounters:
            self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)

        # advance_winner called per newly-completed encounter (20 times)
        self.assertEqual(20, advance_mock.await_count)

        # CRITICAL: queued exactly once for tournament 42
        enqueue_mock.assert_awaited_once_with(42)

        self.assertEqual(20, result["updated"])
        self.assertEqual(20, result["newly_completed"])
        self.assertEqual([42], result["tournaments_recalculated"])

    async def test_bulk_across_multiple_tournaments(self) -> None:
        encounters = [
            _mk_encounter(enc_id=1, tournament_id=100),
            _mk_encounter(enc_id=2, tournament_id=100),
            _mk_encounter(enc_id=3, tournament_id=200),
        ]
        session = _mk_session(encounters)

        enqueue_calls: list[int] = []

        async def capture_enqueue(tid):
            enqueue_calls.append(tid)

        with patch.object(
            encounter_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            side_effect=capture_enqueue,
        ), patch(
            "shared.services.bracket.advancement.advance_winner",
            AsyncMock(),
        ):
            await encounter_service.bulk_update_encounters(
                session,
                admin_schemas.BulkEncounterUpdate(
                    encounter_ids=[1, 2, 3],
                    status="completed",
                ),
            )

        # Two unique tournaments → two recalcs, not three
        self.assertEqual(sorted(enqueue_calls), [100, 200])

    async def test_reset_scores(self) -> None:
        encounters = [_mk_encounter(enc_id=1, tournament_id=42, initial_status="completed")]
        encounters[0].home_score = 3
        encounters[0].away_score = 2
        session = _mk_session(encounters)

        with patch.object(
            encounter_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            AsyncMock(),
        ), patch(
            "shared.services.bracket.advancement.advance_winner",
            AsyncMock(),
        ):
            await encounter_service.bulk_update_encounters(
                session,
                admin_schemas.BulkEncounterUpdate(
                    encounter_ids=[1],
                    reset_scores=True,
                ),
            )

        self.assertEqual(0, encounters[0].home_score)
        self.assertEqual(0, encounters[0].away_score)

    async def test_advance_winner_only_on_transition_to_completed(self) -> None:
        """Already-completed encounters don't re-trigger advance."""
        encounters = [
            _mk_encounter(enc_id=1, tournament_id=42, initial_status="completed"),
            _mk_encounter(enc_id=2, tournament_id=42, initial_status="open"),
        ]
        session = _mk_session(encounters)

        advance_mock = AsyncMock()

        with patch.object(
            encounter_service.standings_recalculation,
            "enqueue_tournament_recalculation",
            AsyncMock(),
        ), patch(
            "shared.services.bracket.advancement.advance_winner",
            advance_mock,
        ):
            await encounter_service.bulk_update_encounters(
                session,
                admin_schemas.BulkEncounterUpdate(
                    encounter_ids=[1, 2],
                    status="completed",
                ),
            )

        # Only encounter #2 transitioned → advance called once
        self.assertEqual(1, advance_mock.await_count)

    async def test_rejects_empty_update(self) -> None:
        with self.assertRaises(Exception) as ctx:
            admin_schemas.BulkEncounterUpdate(encounter_ids=[1, 2])
        self.assertIn("at least one field", str(ctx.exception))

    async def test_rejects_conflicting_scores(self) -> None:
        with self.assertRaises(Exception) as ctx:
            admin_schemas.BulkEncounterUpdate(
                encounter_ids=[1],
                reset_scores=True,
                home_score=3,
            )
        self.assertIn("mutually exclusive", str(ctx.exception))

    async def test_rejects_invalid_status(self) -> None:
        encounters = [_mk_encounter(enc_id=1, tournament_id=42)]
        session = _mk_session(encounters)

        with self.assertRaises(Exception) as ctx:
            await encounter_service.bulk_update_encounters(
                session,
                admin_schemas.BulkEncounterUpdate(
                    encounter_ids=[1], status="garbage"
                ),
            )
        self.assertIn("Invalid status", str(ctx.exception))

    async def test_rejects_no_matching_encounters(self) -> None:
        session = _mk_session([])

        with self.assertRaises(Exception) as ctx:
            await encounter_service.bulk_update_encounters(
                session,
                admin_schemas.BulkEncounterUpdate(
                    encounter_ids=[999], status="completed"
                ),
            )
        self.assertIn("No encounters found", str(ctx.exception))

    async def test_enforces_max_500_ids(self) -> None:
        # pydantic catches this at schema construction
        with self.assertRaises(ValidationError):
            admin_schemas.BulkEncounterUpdate(
                encounter_ids=list(range(1, 502)),
                status="completed",
            )
