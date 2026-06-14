from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

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

flows = importlib.import_module("src.services.match_logs.flows")
record_service = importlib.import_module("src.services.match_logs.log_records")


class MatchLogDedupTests(IsolatedAsyncioTestCase):
    async def test_duplicate_log_finalizes_pending_record_without_reprocessing(self) -> None:
        session = SimpleNamespace()
        tournament = SimpleNamespace(id=42, name="Spring Cup")
        s3 = SimpleNamespace()
        raw_bytes = b"line1\nline2\n"

        with (
            patch.object(flows.tournament_flows, "get", AsyncMock(return_value=tournament)),
            patch.object(flows.s3_service, "get_log_by_filename", AsyncMock(return_value=raw_bytes)),
            patch.object(record_service, "is_already_processed", AsyncMock(return_value=True)),
            patch.object(record_service, "finish_duplicate_record", AsyncMock(), create=True) as finish_duplicate_record,
            patch.object(flows, "MatchLogProcessor") as processor_cls,
        ):
            await flows.process_match_log(session, 42, "match.log", s3, is_raise=True)

        processor_cls.assert_not_called()
        finish_duplicate_record.assert_awaited_once()

        args = finish_duplicate_record.await_args.args
        self.assertIs(args[0], session)
        self.assertEqual(42, args[1])
        self.assertEqual("match.log", args[2])
        self.assertEqual(record_service.compute_content_hash(raw_bytes), args[3])
