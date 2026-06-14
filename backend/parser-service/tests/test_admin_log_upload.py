from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

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

from shared.models.log_processing import LogProcessingSource  # noqa: E402

admin_logs = importlib.import_module("src.routes.admin.logs")
match_logs = importlib.import_module("src.routes.match_logs")


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes = b"match-log") -> None:
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


class Result:
    def __init__(self, value=None, values=None) -> None:
        self._value = value
        self._values = [] if values is None else values

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(all=lambda: self._values)


class AdminLogUploadTests(IsolatedAsyncioTestCase):
    async def test_admin_upload_queues_each_file_with_attached_encounter(self) -> None:
        files = [FakeUploadFile("one.log"), FakeUploadFile("two.log")]
        session = SimpleNamespace(
            execute=AsyncMock(return_value=Result(SimpleNamespace(id=9, tournament_id=42, name="A vs B")))
        )
        user = SimpleNamespace(id=7)
        s3 = SimpleNamespace()

        async def store_uploaded_log(*args, **kwargs):
            uploaded_file = kwargs["uploaded_file"]
            return SimpleNamespace(
                id=100 + len(store_uploaded_log.calls),
                filename=uploaded_file.filename,
                attached_encounter_id=kwargs["attached_encounter_id"],
            )

        store_uploaded_log.calls = []

        async def store_side_effect(*args, **kwargs):
            store_uploaded_log.calls.append((args, kwargs))
            return await store_uploaded_log(*args, **kwargs)

        with (
            patch.object(
                admin_logs.tournament_flows,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=42, name="Cup")),
            ),
            patch.object(
                admin_logs.upload_service,
                "resolve_auth_uploader_id",
                AsyncMock(return_value=777),
            ),
            patch.object(
                admin_logs.upload_service,
                "store_uploaded_log",
                AsyncMock(side_effect=store_side_effect),
            ) as store_mock,
            patch.object(admin_logs, "publish_message", AsyncMock()) as publish_mock,
        ):
            response = await admin_logs.upload_admin_logs(
                tournament_id=42,
                files=files,
                encounter_id=9,
                session=session,
                user=user,
                s3=s3,
            )

        self.assertEqual([], response.errors)
        self.assertEqual(["one.log", "two.log"], [item.filename for item in response.uploaded])
        self.assertEqual([9, 9], [item.attached_encounter_id for item in response.uploaded])
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

    async def test_admin_upload_rejects_encounter_from_another_tournament(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(return_value=Result(SimpleNamespace(id=9, tournament_id=99, name="A vs B")))
        )

        with (
            patch.object(
                admin_logs.tournament_flows,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=42, name="Cup")),
            ),
            patch.object(admin_logs.upload_service, "store_uploaded_log", AsyncMock()) as store_mock,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await admin_logs.upload_admin_logs(
                    tournament_id=42,
                    files=[FakeUploadFile("one.log")],
                    encounter_id=9,
                    session=session,
                    user=SimpleNamespace(id=7),
                    s3=SimpleNamespace(),
                )

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("does not belong", ctx.exception.detail)
        store_mock.assert_not_awaited()

    async def test_history_query_filters_by_attached_encounter(self) -> None:
        captured_queries = []

        async def execute(query):
            captured_queries.append(query)
            return Result(values=[])

        session = SimpleNamespace(execute=AsyncMock(side_effect=execute))

        response = await admin_logs.get_log_history(
            tournament_id=42,
            encounter_id=9,
            workspace_id=None,
            limit=20,
            offset=0,
            session=session,
        )

        self.assertEqual({"items": [], "total": 0}, response)
        compiled_queries = [
            str(query.compile(compile_kwargs={"literal_binds": True}))
            for query in captured_queries
        ]
        self.assertTrue(any("attached_encounter_id = 9" in query for query in compiled_queries))

    async def test_discord_upload_route_keeps_encounter_optional(self) -> None:
        session = SimpleNamespace()

        with (
            patch.object(
                match_logs.tournaments_flows,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=42, name="Cup")),
            ),
            patch.object(
                match_logs.upload_service,
                "store_uploaded_log",
                AsyncMock(return_value=SimpleNamespace(id=1, filename="discord.log")),
            ) as store_mock,
        ):
            response = await match_logs.process_logs_async(
                tournament_id=42,
                file=FakeUploadFile("discord.log"),
                discord_username=None,
                session=session,
                auth_user=None,
                s3=SimpleNamespace(),
            )

        self.assertEqual({"message": "Logs uploaded successfully"}, response)
        store_mock.assert_awaited_once()
        self.assertEqual(LogProcessingSource.manual, store_mock.await_args.kwargs["source"])
        self.assertIsNone(store_mock.await_args.kwargs["uploader_id"])
        self.assertNotIn("attached_encounter_id", store_mock.await_args.kwargs)
