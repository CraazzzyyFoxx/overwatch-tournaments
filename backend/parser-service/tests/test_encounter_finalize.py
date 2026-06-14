from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.dialects import postgresql

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
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

finalize = importlib.import_module("src.services.encounter.finalize")
enums = importlib.import_module("shared.core.enums")


class _Result:
    def __init__(self, row: object) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object:
        return self.row


class _Session:
    def __init__(self, row: object) -> None:
        self.row = row
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.row)


def _compiled_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class FinalizeEncounterScoreTests(IsolatedAsyncioTestCase):
    async def test_loads_row_for_update_when_encounter_not_supplied(self) -> None:
        encounter = SimpleNamespace(
            id=10,
            home_score=0,
            away_score=0,
            status=enums.EncounterStatus.OPEN,
            result_status=enums.EncounterResultStatus.NONE,
            confirmed_by_id=None,
            confirmed_at=None,
        )
        session = _Session(encounter)
        advance_winner = AsyncMock(return_value=[SimpleNamespace(id=20)])

        with patch.object(finalize.advancement, "advance_winner", advance_winner):
            result = await finalize.finalize_encounter_score(
                session,
                10,
                home_score=2,
                away_score=1,
                source="admin",
                result_status=enums.EncounterResultStatus.CONFIRMED,
                confirmed_by_id=200,
            )

        self.assertIs(result.encounter, encounter)
        self.assertEqual(2, encounter.home_score)
        self.assertEqual(1, encounter.away_score)
        self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, encounter.result_status)
        self.assertEqual(200, encounter.confirmed_by_id)
        self.assertIsNotNone(encounter.confirmed_at)
        self.assertEqual(1, advance_winner.await_count)
        self.assertIn("FOR UPDATE", _compiled_sql(session.statement))

    async def test_uses_supplied_locked_encounter_without_second_query(self) -> None:
        encounter = SimpleNamespace(id=10, home_score=0, away_score=0, status=enums.EncounterStatus.OPEN)
        session = Mock()
        session.execute = AsyncMock()

        with patch.object(finalize.advancement, "advance_winner", AsyncMock(return_value=[])):
            await finalize.finalize_encounter_score(
                session,
                10,
                encounter=encounter,
                home_score=3,
                away_score=0,
                source="captain",
            )

        session.execute.assert_not_awaited()
        self.assertEqual(3, encounter.home_score)
        self.assertEqual(0, encounter.away_score)
        self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)
