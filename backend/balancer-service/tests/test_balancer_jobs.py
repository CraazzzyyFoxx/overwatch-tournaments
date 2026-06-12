from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.services.balancer import jobs  # noqa: E402
from src.services.balancer import solver as solver_module  # noqa: E402
from src.services.balancer.config.provider import get_balancer_config_payload  # noqa: E402

JOBS = "src.services.balancer.jobs"


def _noop_limiter() -> SimpleNamespace:
    return SimpleNamespace(
        check_request=AsyncMock(),
        reserve_job=AsyncMock(),
        release_job=AsyncMock(),
    )


class GetConfigTests(TestCase):
    def test_returns_same_payload_as_provider(self) -> None:
        self.assertEqual(jobs.get_config(), get_balancer_config_payload())


class CreateJobTests(IsolatedAsyncioTestCase):
    async def test_creates_job_and_publishes_queue_event(self) -> None:
        created: dict = {}

        class FakeStore:
            async def create_job(self, input_data, config_overrides, *, job_id, workspace_id,
                                 created_by, credential_type, api_key_id, tournament_id=None):
                created.update(
                    input_data=input_data,
                    config_overrides=config_overrides,
                    job_id=job_id,
                    workspace_id=workspace_id,
                    tournament_id=tournament_id,
                    created_by=created_by,
                    credential_type=credential_type,
                    api_key_id=api_key_id,
                )
                return "job-123"

            async def mark_failed(self, *a, **k):  # pragma: no cover - not expected here
                raise AssertionError("mark_failed should not be called")

        class FakeParser:
            async def parse_player_data(self, uploaded_file) -> dict:
                return {"players": {"1": {"name": "Player One"}}}

            def parse_config_overrides(self, raw_config):
                return {"algorithm": "moo"}

        class FakePublisher:
            def __init__(self, broker, logger):
                self.broker = broker

            async def publish_job_requested(self, job_id: str) -> None:
                created["published_job_id"] = job_id

        access_policy = SimpleNamespace(ensure_workspace_access=lambda *a, **k: created.update(access=True))

        with (
            patch(f"{JOBS}.get_job_store", return_value=FakeStore()),
            patch(f"{JOBS}.get_api_key_limiter", return_value=_noop_limiter()),
            patch(f"{JOBS}._access_policy", access_policy),
            patch(f"{JOBS}._payload_parser", FakeParser()),
            patch(f"{JOBS}.is_api_key_principal", return_value=False),
            patch(f"{JOBS}.BalancerJobPublisher", FakePublisher),
        ):
            response = await jobs.create_job(
                uploaded_file=SimpleNamespace(filename="players.json"),
                raw_config='{"algorithm": "moo"}',
                workspace_id=77,
                user=SimpleNamespace(id=9),
                broker=SimpleNamespace(),
            )

        self.assertEqual(response.job_id, "job-123")
        self.assertEqual(response.status, "queued")
        self.assertEqual(created["workspace_id"], 77)
        self.assertEqual(created["created_by"], 9)
        self.assertEqual(created["published_job_id"], "job-123")
        self.assertEqual(created["config_overrides"], {"algorithm": "moo"})
        self.assertEqual(created["credential_type"], "access_token")
        self.assertIsNone(created["api_key_id"])

    async def test_publishes_realtime_queued_event_when_tournament_scoped(self) -> None:
        class FakeStore:
            async def create_job(self, *a, **k):
                return "job-xyz"

            async def mark_failed(self, *a, **k):  # pragma: no cover - not expected here
                raise AssertionError("mark_failed should not be called")

        class FakeParser:
            async def parse_player_data(self, uploaded_file) -> dict:
                return {"players": {"1": {"name": "Player One"}}}

            def parse_config_overrides(self, raw_config):
                return {}

        class FakePublisher:
            def __init__(self, broker, logger):
                pass

            async def publish_job_requested(self, job_id: str) -> None:
                pass

        access_policy = SimpleNamespace(ensure_workspace_access=lambda *a, **k: None)
        emit = AsyncMock()

        with (
            patch(f"{JOBS}.get_job_store", return_value=FakeStore()),
            patch(f"{JOBS}.get_api_key_limiter", return_value=_noop_limiter()),
            patch(f"{JOBS}._access_policy", access_policy),
            patch(f"{JOBS}._payload_parser", FakeParser()),
            patch(f"{JOBS}.is_api_key_principal", return_value=False),
            patch(f"{JOBS}.BalancerJobPublisher", FakePublisher),
            patch(f"{JOBS}.emit_balancer_job_event", emit),
        ):
            await jobs.create_job(
                uploaded_file=SimpleNamespace(filename="players.json"),
                raw_config=None,
                workspace_id=77,
                user=SimpleNamespace(id=9),
                broker=SimpleNamespace(),
                tournament_id=42,
            )

        emit.assert_awaited_once()
        args, kwargs = emit.await_args
        self.assertEqual(args[0], 42)
        self.assertEqual(args[1], "balancer_job.queued")
        self.assertEqual(kwargs["job_id"], "job-xyz")
        self.assertEqual(kwargs["status"], "queued")
        self.assertEqual(kwargs["workspace_id"], 77)
        self.assertEqual(kwargs["actor_user_id"], 9)

    async def test_api_key_create_job_reserves_limit_and_stores_metadata(self) -> None:
        created: dict = {}

        class FakeStore:
            async def create_job(self, input_data, config_overrides, *, job_id, workspace_id,
                                 created_by, credential_type, api_key_id, tournament_id=None):
                created.update(job_id=job_id, credential_type=credential_type, api_key_id=api_key_id)
                return job_id

        class FakeParser:
            async def parse_player_data(self, uploaded_file) -> dict:
                return {"players": {"1": {"name": "Player One"}}}

            def parse_config_overrides(self, raw_config):
                return {"population_size": 150}

        class FakePublisher:
            def __init__(self, broker, logger):
                pass

            async def publish_job_requested(self, job_id: str) -> None:
                created["published_job_id"] = job_id

        limiter = SimpleNamespace(
            check_request=AsyncMock(side_effect=lambda user: created.update(checked=user._api_key_id)),
            reserve_job=AsyncMock(side_effect=lambda user, job_id: created.update(reserved=(user._api_key_id, job_id))),
            release_job=AsyncMock(),
        )
        access_policy = SimpleNamespace(ensure_workspace_access=lambda *a, **k: None)
        user = SimpleNamespace(id=9, _credential_type="api_key", _api_key_id=42)

        with (
            patch(f"{JOBS}.get_job_store", return_value=FakeStore()),
            patch(f"{JOBS}.get_api_key_limiter", return_value=limiter),
            patch(f"{JOBS}._access_policy", access_policy),
            patch(f"{JOBS}._payload_parser", FakeParser()),
            patch(f"{JOBS}.is_api_key_principal", return_value=True),
            patch(f"{JOBS}.get_api_key_id", return_value=42),
            patch(f"{JOBS}.get_api_key_limits", return_value={"max_upload_bytes": 10 * 1024 * 1024, "max_players": 500}),
            patch(f"{JOBS}.validate_api_key_config_policy"),
            patch(f"{JOBS}.BalancerJobPublisher", FakePublisher),
        ):
            response = await jobs.create_job(
                uploaded_file=SimpleNamespace(filename="players.json", size=1024),
                raw_config='{"algorithm": "moo", "population_size": 150}',
                workspace_id=77,
                user=user,
                broker=SimpleNamespace(),
            )

        self.assertEqual(response.job_id, created["job_id"])
        self.assertEqual(created["reserved"], (42, created["job_id"]))
        self.assertEqual(created["checked"], 42)
        self.assertEqual(created["credential_type"], "api_key")
        self.assertEqual(created["api_key_id"], 42)
        limiter.release_job.assert_not_awaited()


def _make_fake_store(payload: dict, *, fail_marks: bool = False, optimizing_messages: list | None = None):
    class FakeStore:
        def __init__(self) -> None:
            self.meta = {"status": "queued", "created_at": 0.0, "events_count": 0}
            self.succeeded = None
            self.failed = None

        async def get_job_payload(self, job_id: str) -> dict:
            return payload

        async def get_job_meta(self, job_id: str) -> dict:
            return self.meta

        async def mark_running(self, job_id: str, meta=None) -> dict:
            self.meta = dict(meta or self.meta)
            self.meta["status"] = "running"
            return self.meta

        async def append_event(self, job_id, *, status, stage, message, level="info",
                               progress=None, update_meta=False, meta=None):
            if optimizing_messages is not None and stage == "optimizing":
                optimizing_messages.append(message)
            if meta is not None:
                meta["events_count"] = int(meta.get("events_count", 0)) + 1
                if update_meta:
                    meta["status"] = status
                    meta["stage"] = stage
                    if progress is not None:
                        meta["progress"] = progress
                self.meta = meta

        async def mark_succeeded(self, job_id, result, meta=None) -> dict:
            self.succeeded = (job_id, result)
            self.meta = dict(meta or self.meta)
            self.meta["status"] = "succeeded"
            return self.meta

        async def mark_failed(self, job_id, error_message, meta=None) -> dict:
            if fail_marks:
                raise AssertionError(error_message)
            self.failed = (job_id, error_message)
            self.meta = dict(meta or self.meta)
            self.meta["status"] = "failed"
            return self.meta

    return FakeStore()


_VARIANT = {
    "teams": [],
    "statistics": {"average_mmr": 0, "mmr_std_dev": 0, "total_teams": 0, "players_per_team": 5},
    "benched_players": [],
}


class ExecuteJobTests(IsolatedAsyncioTestCase):
    async def test_executes_job_and_marks_result(self) -> None:
        store = _make_fake_store({"player_data": {"players": {}}, "config_overrides": {"algorithm": "moo"}})

        async def fake_run_balance(input_data, config_overrides, progress_callback):
            progress_callback({"status": "running", "stage": "optimizing", "message": "Working"})
            return {"variants": [dict(_VARIANT)]}

        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.run_balance", fake_run_balance),
        ):
            await jobs.execute_balance_job("job-42")

        self.assertEqual(store.succeeded[0], "job-42")
        self.assertEqual(store.succeeded[1]["variants"][0]["teams"], [])
        self.assertIsNone(store.failed)

    async def test_flushes_last_throttled_progress_update_before_completion(self) -> None:
        messages: list[str] = []
        store = _make_fake_store(
            {"player_data": {"players": {}}, "config_overrides": {"algorithm": "moo"}},
            fail_marks=True,
            optimizing_messages=messages,
        )

        async def fake_run_balance(input_data, config_overrides, progress_callback):
            progress_callback({"status": "running", "stage": "optimizing", "message": "Phase 1",
                               "progress": {"percent": 0.0}})
            progress_callback({"status": "running", "stage": "optimizing", "message": "Phase 2",
                               "progress": {"percent": 1.0}})
            return {"variants": [dict(_VARIANT)]}

        clock_values = iter([1.0, 1.1, 1.2])
        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.run_balance", fake_run_balance),
        ):
            await jobs.execute_balance_job("job-throttle", progress_clock=lambda: next(clock_values))

        self.assertEqual(messages, ["Phase 1", "Phase 2"])

    async def test_ignores_legacy_job_payload_config_key(self) -> None:
        store = _make_fake_store(
            {"player_data": {"players": {}}, "config": {"population_size": 50}},
            fail_marks=True,
        )
        seen: dict = {}

        async def fake_run_balance(input_data, config_overrides, progress_callback):
            seen["config_overrides"] = config_overrides
            return {"variants": [dict(_VARIANT)]}

        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.run_balance", fake_run_balance),
        ):
            await jobs.execute_balance_job("job-legacy")

        self.assertEqual(seen["config_overrides"], {})


class SolverTests(IsolatedAsyncioTestCase):
    async def test_run_balance_preserves_variants_shape(self) -> None:
        variants = [
            {"teams": [{"id": 1}], "statistics": {}, "benched_players": []},
            {"teams": [{"id": 2}], "statistics": {}, "benched_players": []},
        ]
        with patch(
            "src.services.balancer.solver.asyncio.to_thread",
            AsyncMock(return_value=variants),
        ) as to_thread:
            result = await solver_module.run_balance({"players": {}}, {"algorithm": "moo"}, None)

        self.assertEqual(result, {"variants": variants})
        to_thread.assert_awaited_once()
