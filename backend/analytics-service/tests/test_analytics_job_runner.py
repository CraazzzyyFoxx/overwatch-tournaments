from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

job_runner = importlib.import_module("src.services.jobs.runner")
job_service = importlib.import_module("src.services.jobs.service")


def _job() -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        workspace_id=1,
        tournament_id=7,
        requested_by_user_id=5,
        kind=job_runner.JOB_KIND_COMPUTE,
        progress={},
        algorithms=None,
        training_workspace_ids=None,
    )


class _ExpiringJob:
    def __init__(self) -> None:
        self._expired = False
        self._id = 10
        self.workspace_id = 1
        self.tournament_id = 7
        self.requested_by_user_id = 5
        self.kind = job_runner.JOB_KIND_TRAIN_ML
        self.progress = {}
        self.algorithms = None
        self.training_workspace_ids = None

    @property
    def id(self) -> int:
        if self._expired:
            raise RuntimeError("expired ORM attribute access")
        return self._id

    def expire(self) -> None:
        self._expired = True


class AnalyticsJobRunnerFailureTests(IsolatedAsyncioTestCase):
    async def test_run_job_rolls_back_before_marking_job_failed(self) -> None:
        job = _job()
        session = SimpleNamespace(rollback=AsyncMock())

        with (
            patch.object(job_runner, "get_job", AsyncMock(side_effect=[job, job, job])),
            patch.object(job_runner, "mark_job_running", AsyncMock()),
            patch.object(job_runner, "_emit", AsyncMock()),
            patch.object(job_runner, "_run_compute", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(job_runner, "mark_job_failed", AsyncMock()) as mark_failed,
        ):
            await job_runner.run_job(session, None, job.id)

        session.rollback.assert_awaited()
        mark_failed.assert_awaited_once()
        self.assertIn("boom", mark_failed.await_args.kwargs["error"])

    async def test_run_job_uses_cached_job_id_after_inner_rollback_expires_orm_object(self) -> None:
        job = _ExpiringJob()
        session = SimpleNamespace(rollback=AsyncMock())

        async def fail_train(*_args, **_kwargs) -> None:
            job.expire()
            raise RuntimeError("lightgbm exploded")

        with (
            patch.object(job_runner, "get_job", AsyncMock(return_value=job)),
            patch.object(job_runner, "mark_job_running", AsyncMock()),
            patch.object(job_runner, "_emit", AsyncMock()),
            patch.object(job_runner, "_run_train_ml", AsyncMock(side_effect=fail_train)),
            patch.object(job_runner, "mark_job_failed", AsyncMock()) as mark_failed,
        ):
            await job_runner.run_job(session, None, 10)

        mark_failed.assert_awaited_once()
        self.assertEqual(10, mark_failed.await_args.args[1])
        self.assertIn("lightgbm exploded", mark_failed.await_args.kwargs["error"])

    async def test_compute_stage_rolls_back_before_failed_progress_update(self) -> None:
        job = _job()
        session = SimpleNamespace(rollback=AsyncMock())

        with (
            patch.object(job_runner, "update_progress", AsyncMock()) as update_progress,
            patch.object(job_runner, "get_job", AsyncMock(return_value=job)),
            patch.object(job_runner, "_emit", AsyncMock()),
            patch.object(
                job_runner.v1_flows,
                "recalculate_analytics",
                AsyncMock(side_effect=RuntimeError("v1 exploded")),
            ),
        ):
            with self.assertRaises(RuntimeError):
                await job_runner._run_compute(session, None, job)

        session.rollback.assert_awaited()
        failed_updates = [
            call
            for call in update_progress.await_args_list
            if call.kwargs.get("state") == "failed"
        ]
        self.assertEqual(1, len(failed_updates))
        self.assertEqual("v1_recalc", failed_updates[0].kwargs["stage"])

    async def test_train_job_uses_training_workspace_ids_as_sample_scope(self) -> None:
        job = _job()
        job.kind = job_runner.JOB_KIND_TRAIN_ML
        job.training_workspace_ids = [1, 3]
        session = SimpleNamespace(rollback=AsyncMock())

        with (
            patch.object(job_runner, "update_progress", AsyncMock()),
            patch.object(job_runner, "get_job", AsyncMock(return_value=job)),
            patch.object(job_runner, "_emit", AsyncMock()),
            patch.object(job_runner, "train_all_models", AsyncMock(return_value={})) as train_all,
        ):
            await job_runner._run_train_ml(session, None, job)

        train_all.assert_awaited_once_with(
            session,
            cutoff_tournament_id=job.tournament_id,
            model_kinds=None,
            workspace_id=None,
            workspace_ids=[1, 3],
        )


class AnalyticsJobServiceTests(TestCase):
    def test_failed_progress_stage_marks_job_as_reconcilable(self) -> None:
        self.assertTrue(
            job_service._progress_has_failed_stage(
                {"v2_inference": {"state": "failed", "detail": {"error": "boom"}}}
            )
        )
        self.assertFalse(
            job_service._progress_has_failed_stage(
                {"v2_inference": {"state": "running"}}
            )
        )
