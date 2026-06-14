from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

jobs = importlib.import_module("src.services.computation.jobs")
bracket_worker = importlib.import_module("src.services.computation.bracket_worker")
topology = importlib.import_module("shared.messaging.topology")
computation = importlib.import_module("shared.services.tournament_computation")


class ComputationJobTests(IsolatedAsyncioTestCase):
    async def test_active_job_is_reused_after_scope_lock(self) -> None:
        active = SimpleNamespace(id=7)
        session = SimpleNamespace(
            execute=AsyncMock(),
            add=Mock(),
            flush=AsyncMock(),
        )

        with (
            patch.object(computation, "_active_job", AsyncMock(return_value=active)),
            patch.object(computation, "dispatch_job", AsyncMock()) as dispatch,
        ):
            result = await computation.create_job(
                session,
                kind="bracket",
                operation="generate_stage",
                tournament_id=1,
                stage_id=2,
                stage_item_id=None,
                payload={},
                requested_by_user_id=3,
                idempotency_key="bracket:2:all:generate_stage:manual",
            )

        self.assertIs(active, result)
        session.execute.assert_awaited_once()
        session.add.assert_not_called()
        dispatch.assert_not_awaited()

    async def test_computation_message_contains_only_job_id(self) -> None:
        session = SimpleNamespace()
        job = SimpleNamespace(id=7, kind="bracket")

        with patch.object(computation, "enqueue_outbox_event", AsyncMock()) as enqueue:
            await computation.dispatch_job(session, job)

        self.assertEqual({"job_id": 7}, enqueue.await_args.args[1])
        self.assertEqual("tournament_computation_job", enqueue.await_args.kwargs["event_type"])

    async def test_running_job_is_reclaimed_after_worker_redelivery(self) -> None:
        job = SimpleNamespace(
            kind="standings",
            status="running",
            started_at=None,
            finished_at=None,
            error="old",
            attempts=1,
        )
        session = SimpleNamespace(commit=AsyncMock())

        with patch.object(jobs, "get_job", AsyncMock(return_value=job)):
            claimed = await jobs.claim_job(session, 7, kind="standings")

        self.assertIs(job, claimed)
        self.assertEqual("running", job.status)
        self.assertEqual(2, job.attempts)
        self.assertIsNone(job.error)
        session.commit.assert_awaited_once()

    async def test_bracket_operations_share_one_active_scope_key(self) -> None:
        session = SimpleNamespace()

        with patch.object(computation, "create_job", AsyncMock(return_value=SimpleNamespace())) as create:
            await computation.request_bracket_job(
                session,
                tournament_id=1,
                stage_id=2,
                operation="generate_stage",
            )
            await computation.request_bracket_job(
                session,
                tournament_id=1,
                stage_id=2,
                operation="activate_and_generate",
            )

        keys = [call.kwargs["idempotency_key"] for call in create.await_args_list]
        self.assertEqual(["bracket:2:all", "bracket:2:all"], keys)

    async def test_late_failure_does_not_overwrite_terminal_success(self) -> None:
        job = SimpleNamespace(status="succeeded")
        session = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(jobs, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.mark_job_failed(session, 7, "late failure")

        self.assertEqual("ignored", disposition)
        self.assertEqual("succeeded", job.status)
        session.commit.assert_not_awaited()
        dispatch.assert_not_awaited()

    async def test_failed_attempt_is_atomically_redispatched(self) -> None:
        job = SimpleNamespace(status="running", attempts=1, error=None, finished_at=None)
        session = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(jobs, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.mark_job_failed(session, 7, "temporary")

        self.assertEqual("retry", disposition)
        self.assertEqual("pending", job.status)
        self.assertEqual("temporary", job.error)
        dispatch.assert_awaited_once_with(session, job)
        session.commit.assert_awaited_once()

    async def test_last_failed_attempt_is_not_redispatched(self) -> None:
        job = SimpleNamespace(status="running", attempts=jobs.MAX_ATTEMPTS, error=None, finished_at=None)
        session = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(jobs, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.mark_job_failed(session, 7, "permanent")

        self.assertEqual("failed", disposition)
        self.assertEqual("failed", job.status)
        dispatch.assert_not_awaited()
        session.commit.assert_awaited_once()

    async def test_dead_letter_queue_is_declared_and_bound(self) -> None:
        declared_queue = SimpleNamespace(bind=AsyncMock())
        exchange = SimpleNamespace()
        broker = SimpleNamespace(
            declare_exchange=AsyncMock(return_value=exchange),
            declare_queue=AsyncMock(return_value=declared_queue),
        )
        queue = SimpleNamespace(routing=Mock(return_value="jobs.dlq"))

        await topology.declare_dead_letter_queue(broker, queue)

        broker.declare_exchange.assert_awaited_once_with(topology.DLX_EXCHANGE)
        broker.declare_queue.assert_awaited_once_with(queue)
        declared_queue.bind.assert_awaited_once_with(exchange, routing_key="jobs.dlq")

    async def test_all_bracket_operations_use_one_dispatcher(self) -> None:
        session = SimpleNamespace()
        operations = (
            ("generate_stage", "generate_encounters"),
            ("activate_and_generate", "activate_and_generate"),
            ("generate_next_swiss_round", "generate_next_swiss_round"),
        )

        for operation, expected_call in operations:
            job = SimpleNamespace(
                operation=operation,
                stage_id=2,
                stage_item_id=3,
                tournament_id=1,
                payload_json={"next_round": 2},
            )
            with (
                patch.object(bracket_worker.stage_service, "generate_encounters", AsyncMock(return_value=[])) as generate,
                patch.object(
                    bracket_worker.stage_service,
                    "activate_and_generate",
                    AsyncMock(return_value=(SimpleNamespace(), [])),
                ) as activate,
                patch.object(bracket_worker, "generate_next_swiss_round", AsyncMock(return_value=[])) as swiss,
            ):
                await bracket_worker._execute_bracket_operation(session, job)

            calls = {
                "generate_encounters": generate.await_count,
                "activate_and_generate": activate.await_count,
                "generate_next_swiss_round": swiss.await_count,
            }
            self.assertEqual(1, calls[expected_call])
            self.assertEqual(1, sum(calls.values()))
