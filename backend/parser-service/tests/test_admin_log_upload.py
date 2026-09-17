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

from shared.models.ingestion.log_processing import LogProcessingSource  # noqa: E402
from tests._fakes import FakeBroker as _FakeBroker
from tests._fakes import active_identity as _active_identity
from tests._fakes import session_factory as _session_factory

rpc_logs = importlib.import_module("src.rpc.logs")
admin_reads = importlib.import_module("src.services.match_logs.admin_reads")


class _Result:
    def __init__(self, value=None, values=None, row=None) -> None:
        self._value = value
        self._values = [] if values is None else values
        self._row = row

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(all=lambda: self._values)

    def one(self):
        return self._row


class AdminLogUploadRpcTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.broker = _FakeBroker()
        rpc_logs.register(self.broker, logging.getLogger("test"))
        self._original_sf = rpc_logs._SF

    def tearDown(self) -> None:
        rpc_logs._SF = self._original_sf

    async def test_upload_queues_each_file_with_attached_encounter(self) -> None:
        audit_rows: list = []
        session = SimpleNamespace(add=audit_rows.append)
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
                AsyncMock(return_value=SimpleNamespace(id=42, name="Cup", workspace_id=5)),
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
            patch.object(rpc_logs, "quota", SimpleNamespace(charge=AsyncMock())) as quota_mock,
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

        # One audit row for the call — file names only, never the uploaded bytes.
        self.assertEqual(1, len(audit_rows))
        row = audit_rows[0]
        self.assertEqual("match_log.upload", row.action)
        self.assertEqual(5, row.workspace_id)
        self.assertEqual("tournament", row.entity_type)
        self.assertEqual(42, row.entity_id)
        self.assertEqual({"filenames": ["one.log", "two.log"]}, row.after_json)

        # One charge for the whole batch, carrying both dimensions the per-request
        # caps are compared against — not one charge per file.
        quota_mock.charge.assert_awaited_once()
        charge = quota_mock.charge.await_args
        self.assertEqual("parser.logs.upload", charge.args[1])
        self.assertEqual(5, charge.kwargs["workspace_id"])
        self.assertEqual(2, charge.kwargs["item_count"])
        self.assertEqual(0, charge.kwargs["size_bytes"])

    async def test_history_query_filters_by_attached_encounter(self) -> None:
        self._recording_session()

        with patch.object(rpc_logs.auth, "require_tournament_id_permission", AsyncMock()):
            envelope = await self.broker.handlers["rpc.parser.logs.history"](
                {
                    "identity": _active_identity(),
                    "query": {"tournament_id": ["42"], "encounter_id": ["9"]},
                },
                msg=None,
            )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual({"items": [], "total": 3}, envelope["data"])
        self.assertTrue(any("attached_encounter_id = 9" in query for query in self._compiled()))

    async def test_history_pushes_status_and_search_into_sql(self) -> None:
        """Both filters used to run in the browser over the current page only."""
        self._recording_session()

        with patch.object(rpc_logs.auth, "require_tournament_id_permission", AsyncMock()):
            envelope = await self.broker.handlers["rpc.parser.logs.history"](
                {
                    "identity": _active_identity(),
                    "query": {"tournament_id": ["42"], "status": ["failed"], "search": ["round_1"]},
                },
                msg=None,
            )

        self.assertTrue(envelope["ok"], envelope)
        compiled = " ".join(self._compiled())
        self.assertIn("status = 'failed'", compiled)
        # The underscore is escaped, so "round_1" cannot match "round-1".
        self.assertIn(r"'%round\_1%'", compiled)
        self.assertIn("lower(log_processing.record.filename) LIKE lower(", compiled)

    async def test_history_rejects_unknown_status(self) -> None:
        self._recording_session()

        with patch.object(rpc_logs.auth, "require_tournament_id_permission", AsyncMock()):
            envelope = await self.broker.handlers["rpc.parser.logs.history"](
                {
                    "identity": _active_identity(),
                    "query": {"tournament_id": ["42"], "status": ["burning"]},
                },
                msg=None,
            )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"])
        self.assertIn("status must be one of", envelope["error"]["message"])

    async def test_stats_returns_scope_wide_aggregate(self) -> None:
        """KPIs come from one aggregate over the whole scope, not the visible page."""
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_Result(row=(10, 1, 2, 6, 1, 3.5, "2026-07-30T10:00:00+00:00")))
        )
        rpc_logs._SF = _session_factory(session)

        with patch.object(rpc_logs.auth, "require_tournament_id_permission", AsyncMock()):
            envelope = await self.broker.handlers["rpc.parser.logs.stats"](
                {"identity": _active_identity(), "query": {"tournament_id": ["42"]}},
                msg=None,
            )

        self.assertTrue(envelope["ok"], envelope)
        data = envelope["data"]
        self.assertEqual(10, data["total"])
        self.assertEqual((1, 2, 6, 1), (data["pending"], data["processing"], data["done"], data["failed"]))
        self.assertEqual(3.5, data["avg_duration_seconds"])

        compiled = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("FILTER (WHERE", compiled)
        self.assertIn("tournament_id = 42", compiled)

    def _recording_session(self) -> None:
        """Install a session recording every statement; count -> 3, row fetch -> empty."""
        self._queries: list = []

        async def execute(query):
            self._queries.append(query)
            return _Result(values=[])

        async def scalar(query):
            self._queries.append(query)
            return 3

        session = SimpleNamespace(execute=AsyncMock(side_effect=execute), scalar=AsyncMock(side_effect=scalar))
        rpc_logs._SF = _session_factory(session)

    def _compiled(self) -> list[str]:
        return [str(query.compile(compile_kwargs={"literal_binds": True})) for query in self._queries]


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


class MatchLogOversizeMessageTests(IsolatedAsyncioTestCase):
    def test_under_cap_is_silent(self) -> None:
        from src.services.match_logs.limits import match_log_oversize_message

        self.assertIsNone(match_log_oversize_message(10, 10))

    def test_over_cap_names_the_file_when_given(self) -> None:
        from src.services.match_logs.limits import match_log_oversize_message

        self.assertEqual(
            "Log file exceeds the maximum size of 10 bytes",
            match_log_oversize_message(11, 10),
        )
        self.assertEqual(
            "Log file a.log exceeds the maximum size of 10 bytes",
            match_log_oversize_message(11, 10, filename="a.log"),
        )
