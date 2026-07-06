"""Coverage for the match-log admin RPC handlers + extracted read helpers.

The HTTP routes in ``src/routes/admin/logs.py`` were decommissioned (FastAPI removed
from parser-service); the admin surface now runs as ``rpc.parser.logs.*`` FastStream
subscribers in ``src/rpc/logs.py``. These tests drive the real ``rpc.logs.register``
through a fake broker and assert the upload/history handlers still queue each file,
attach encounters, and filter history — the same contracts the old routes enforced.

The cross-tournament encounter rejection is exercised directly against the extracted
helper ``src/services/match_logs/admin_reads._validate_attached_encounter``.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.core.errors import BaseAPIException as HTTPException

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

from shared.models.ingestion.log_processing import LogProcessingSource  # noqa: E402

rpc_logs = importlib.import_module("src.rpc.logs")
admin_reads = importlib.import_module("src.services.match_logs.admin_reads")


# ── identity helper ──────────────────────────────────────────────────────────


def _active_identity() -> dict:
    """A gateway identity payload for an active admin user (permissions stubbed)."""
    return {
        "user_id": 7,
        "sub": "7",
        "is_active": True,
        "is_superuser": True,
        "roles": ["admin"],
        "permissions": [],
    }


# ── fake broker + session ──────────────────────────────────────────────────────


class _FakeBroker:
    """Capture FastStream subscribers by subject so we can invoke them directly."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def _decorator(fn):
            self.handlers[subject] = fn
            return fn

        return _decorator


class _Result:
    def __init__(self, value=None, values=None) -> None:
        self._value = value
        self._values = [] if values is None else values

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(all=lambda: self._values)


def _session_factory(session):
    """Build a ``session_factory()`` returning an async-context-managed session."""

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


class AdminLogUploadRpcTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.broker = _FakeBroker()
        rpc_logs.register(self.broker, logging.getLogger("test"))
        self._original_sf = rpc_logs._SF

    def tearDown(self) -> None:
        rpc_logs._SF = self._original_sf

    async def test_upload_queues_each_file_with_attached_encounter(self) -> None:
        session = SimpleNamespace()
        rpc_logs._SF = _session_factory(session)

        async def store_uploaded_log_bytes(*args, **kwargs):
            return SimpleNamespace(
                id=100,
                filename=kwargs["filename"],
                attached_encounter_id=kwargs["attached_encounter_id"],
            )

        with (
            patch.object(rpc_logs.auth, "require_tournament_id_permission", AsyncMock()),
            patch.object(
                rpc_logs.tournament_flows,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=42, name="Cup")),
            ),
            patch.object(
                rpc_logs,
                "_validate_attached_encounter",
                AsyncMock(return_value=SimpleNamespace(id=9)),
            ),
            patch.object(
                rpc_logs.upload_service,
                "validate_log_filename",
                side_effect=lambda name: name,
            ),
            patch.object(
                rpc_logs.upload_service,
                "resolve_auth_uploader_id",
                AsyncMock(return_value=777),
            ),
            patch.object(
                rpc_logs.upload_service,
                "store_uploaded_log_bytes",
                AsyncMock(side_effect=store_uploaded_log_bytes),
            ) as store_mock,
            patch.object(rpc_logs, "publish_message", AsyncMock()) as publish_mock,
        ):
            envelope = await self.broker.handlers["rpc.parser.logs.upload"](
                {
                    "identity": _active_identity(),
                    "tournament_id": 42,
                    "encounter_id": 9,
                    "files": [
                        {"filename": "one.log", "content_b64": ""},
                        {"filename": "two.log", "content_b64": ""},
                    ],
                },
                msg=None,
            )

        self.assertTrue(envelope["ok"], envelope)
        data = envelope["data"]
        self.assertEqual([], data["errors"])
        self.assertEqual(["one.log", "two.log"], [item["filename"] for item in data["uploaded"]])
        self.assertEqual([9, 9], [item["attached_encounter_id"] for item in data["uploaded"]])
        self.assertEqual(2, store_mock.await_count)
        for call in store_mock.await_args_list:
            self.assertEqual(42, call.kwargs["tournament_id"])
            self.assertEqual(777, call.kwargs["uploader_id"])
            self.assertEqual(9, call.kwargs["attached_encounter_id"])
            self.assertEqual(LogProcessingSource.upload, call.kwargs["source"])

        self.assertEqual(2, publish_mock.await_count)
        payloads = [call.args[1] for call in publish_mock.await_args_list]
        self.assertEqual(["one.log", "two.log"], [payload["filename"] for payload in payloads])
        self.assertEqual([42, 42], [payload["tournament_id"] for payload in payloads])

    async def test_history_query_filters_by_attached_encounter(self) -> None:
        captured_queries = []

        async def execute(query):
            captured_queries.append(query)
            return _Result(values=[])

        session = SimpleNamespace(execute=AsyncMock(side_effect=execute))
        rpc_logs._SF = _session_factory(session)

        with patch.object(rpc_logs.auth, "require_tournament_id_permission", AsyncMock()):
            envelope = await self.broker.handlers["rpc.parser.logs.history"](
                {
                    "identity": _active_identity(),
                    "query": {"tournament_id": ["42"], "encounter_id": ["9"]},
                },
                msg=None,
            )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual({"items": [], "total": 0}, envelope["data"])
        compiled_queries = [str(query.compile(compile_kwargs={"literal_binds": True})) for query in captured_queries]
        self.assertTrue(any("attached_encounter_id = 9" in query for query in compiled_queries))


class ValidateAttachedEncounterTests(IsolatedAsyncioTestCase):
    async def test_rejects_encounter_from_another_tournament(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_Result(SimpleNamespace(id=9, tournament_id=99, name="A vs B")))
        )

        with self.assertRaises(HTTPException) as ctx:
            await admin_reads._validate_attached_encounter(session, tournament_id=42, encounter_id=9)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("does not belong", ctx.exception.detail)

    async def test_returns_none_when_no_encounter_attached(self) -> None:
        session = SimpleNamespace(execute=AsyncMock())
        result = await admin_reads._validate_attached_encounter(session, tournament_id=42, encounter_id=None)
        self.assertIsNone(result)
        session.execute.assert_not_awaited()
