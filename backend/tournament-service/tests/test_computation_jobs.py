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

jobs = importlib.import_module("src.services.computation.jobs")
bracket_worker = importlib.import_module("src.services.computation.bracket_worker")
standings_worker = importlib.import_module("src.services.computation.standings_worker")
topology = importlib.import_module("shared.messaging.topology")
computation = importlib.import_module("shared.services.tournament.computation")


def _session_maker(session):
    """Stand-in for ``db.async_session_maker``: every ``async with`` yields ``session``."""

    class _Maker:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return _Maker()


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

        with patch.object(jobs.jobs_service, "get_job", AsyncMock(return_value=job)):
            claimed = await jobs.jobs_service.claim_job(session, 7, kind="standings")

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
            patch.object(jobs.jobs_service, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.jobs_service.mark_job_failed(session, 7, RuntimeError("late failure"))

        self.assertEqual("ignored", disposition)
        self.assertEqual("succeeded", job.status)
        session.commit.assert_not_awaited()
        dispatch.assert_not_awaited()

    async def test_failed_attempt_is_atomically_redispatched(self) -> None:
        job = SimpleNamespace(status="running", attempts=1, error=None, finished_at=None)
        session = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(jobs.jobs_service, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.jobs_service.mark_job_failed(session, 7, RuntimeError("temporary"))

        self.assertEqual("retry", disposition)
        self.assertEqual("pending", job.status)
        self.assertEqual("RuntimeError: temporary", job.error)
        dispatch.assert_awaited_once_with(session, job)
        session.commit.assert_awaited_once()

    async def test_last_failed_attempt_is_not_redispatched(self) -> None:
        job = SimpleNamespace(status="running", attempts=jobs.MAX_ATTEMPTS, error=None, finished_at=None)
        session = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(jobs.jobs_service, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.jobs_service.mark_job_failed(session, 7, RuntimeError("permanent"))

        self.assertEqual("failed", disposition)
        self.assertEqual("failed", job.status)
        dispatch.assert_not_awaited()
        session.commit.assert_awaited_once()

    async def test_domain_refusal_fails_on_first_attempt_without_redispatch(self) -> None:
        job = SimpleNamespace(status="running", attempts=1, error=None, finished_at=None)
        session = SimpleNamespace(commit=AsyncMock())
        refusal = jobs.BaseAPIException(409, "This stage already has generated matches.")

        with (
            patch.object(jobs.jobs_service, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()) as dispatch,
        ):
            disposition = await jobs.jobs_service.mark_job_failed(session, 7, refusal)

        # "refused", not "failed": the worker acks instead of dead-lettering.
        self.assertEqual("refused", disposition)
        self.assertEqual("failed", job.status)
        self.assertEqual("This stage already has generated matches.", job.error)
        dispatch.assert_not_awaited()
        session.commit.assert_awaited_once()

    async def test_server_error_exception_is_still_retried(self) -> None:
        job = SimpleNamespace(status="running", attempts=1, error=None, finished_at=None)
        session = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(jobs.jobs_service, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs, "dispatch_job", AsyncMock()),
        ):
            disposition = await jobs.jobs_service.mark_job_failed(session, 7, jobs.BaseAPIException(503, "down"))

        self.assertEqual("retry", disposition)

    def test_failure_message_is_the_refusal_not_a_traceback(self) -> None:
        refusal = jobs.BaseAPIException(400, "Need at least 2 teams to generate a bracket")
        upstream = jobs.BaseAPIException(
            409, {"code": "upstream_stages_not_completed", "message": "Finish them first.", "pending_stage_ids": [1]}
        )

        self.assertEqual("Need at least 2 teams to generate a bracket", jobs.failure_message(refusal))
        # The admin client turns this substring into the force-activate prompt.
        self.assertEqual("upstream_stages_not_completed: Finish them first.", jobs.failure_message(upstream))
        self.assertEqual("RuntimeError: boom", jobs.failure_message(RuntimeError("boom")))

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
                patch.object(
                    bracket_worker.stage_service, "generate_encounters", AsyncMock(return_value=[])
                ) as generate,
                patch.object(
                    bracket_worker.stage_service,
                    "activate_and_generate",
                    AsyncMock(return_value=(SimpleNamespace(), [])),
                ) as activate,
                patch.object(
                    bracket_worker.swiss_rounds_service, "generate_next_swiss_round", AsyncMock(return_value=[])
                ) as swiss,
            ):
                await bracket_worker._execute_bracket_operation(session, job)

            calls = {
                "generate_encounters": generate.await_count,
                "activate_and_generate": activate.await_count,
                "generate_next_swiss_round": swiss.await_count,
            }
            self.assertEqual(1, calls[expected_call])
            self.assertEqual(1, sum(calls.values()))

    async def test_contended_tournament_lock_requeues_without_spending_an_attempt(self) -> None:
        """A standings job that loses the race for the tournament row must come
        back later with its retry budget intact: waiting out ``statement_timeout``
        three times used to mark it failed and leave the standings stale
        (OWT-TOURNAMENTS-R)."""
        job = SimpleNamespace(
            id=7, status="running", attempts=2, error="old", started_at="now", tournament_id=1, payload_json={}
        )
        session = SimpleNamespace(
            # FOR UPDATE SKIP LOCKED finds nothing, the tournament still exists.
            scalar=AsyncMock(side_effect=[None, 1]),
            commit=AsyncMock(),
        )

        with (
            patch.object(standings_worker.db, "async_session_maker", _session_maker(session)),
            patch.object(standings_worker.jobs_service, "claim_job", AsyncMock(return_value=job)),
            patch.object(standings_worker.jobs_service, "get_job", AsyncMock(return_value=job)),
            patch.object(standings_worker, "dispatch_job", AsyncMock()) as dispatch,
            patch.object(standings_worker.standings_service, "recalculate_for_tournament", AsyncMock()) as recalculate,
        ):
            await standings_worker.process_standings_job(7)

        self.assertEqual("pending", job.status)
        self.assertEqual(1, job.attempts)
        self.assertIsNone(job.error)
        self.assertEqual(2, session.scalar.await_count)
        dispatch.assert_awaited_once_with(session, job)
        session.commit.assert_awaited_once()
        recalculate.assert_not_awaited()
