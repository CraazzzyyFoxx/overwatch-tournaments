from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

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

captain = importlib.import_module("src.services.encounter.captain")
encounter_service = importlib.import_module("src.services.encounter.service")


class _Result:
    def __init__(self, row: object) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object:
        return self.row


class _Session:
    def __init__(self, row: object) -> None:
        self.row = row
        self.statement = None
        self.committed = False

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.row)

    async def commit(self) -> None:
        self.committed = True


def _compiled_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class EncounterWriteLockTests(IsolatedAsyncioTestCase):
    async def test_captain_load_encounter_locks_row_for_update(self) -> None:
        session = _Session(SimpleNamespace(id=12))

        loaded = await captain._load_encounter(session, 12)

        self.assertEqual(12, loaded.id)
        self.assertIn("FOR UPDATE", _compiled_sql(session.statement))

    async def test_update_encounter_logs_locks_row_before_write(self) -> None:
        encounter = SimpleNamespace(id=12, has_logs=False)
        session = _Session(encounter)

        updated = await encounter_service.update_encounter_logs(session, 12, has_logs=True)

        self.assertIs(updated, encounter)
        self.assertTrue(updated.has_logs)
        self.assertTrue(session.committed)
        self.assertIn("FOR UPDATE", _compiled_sql(session.statement))
