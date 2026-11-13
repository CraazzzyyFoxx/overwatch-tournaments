"""Bulk delivery fans native job IDs out; real enumeration lives in test_stats_ingest_db."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))


import aio_pika
from aiormq.exceptions import DeliveryError
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from shared.messaging import config, topology
from src.services.match_logs.log_records import TournamentRequeue
from tests._fakes import session_factory

logs = importlib.import_module("src.services.match_logs.consumers")
ingest = importlib.import_module("src.services.ingest.consumers")
BROKER = object()


def _undeliverable() -> DeliveryError:
    # aiormq's DeliveryError.__str__ reads frame.name, so a frameless one cannot even be logged.
    return DeliveryError(None, SimpleNamespace(name="Basic.Return"))


async def _fan_out() -> None:
    await logs.process_tournament_log(
        {"tournament_id": 42},
        SimpleNamespace(headers={}, message_id=None, raw_message=None),
        broker=BROKER,
        logger=logger,
    )


async def _replay(discipline: str, data: dict, msg) -> None:
    await ingest.process_replay_message(discipline, data, msg, logger=logger)


class TournamentLogsFanoutTests(IsolatedAsyncioTestCase):
    async def test_requeue_runs_in_the_consumer_without_inline_parsing_or_direct_publishes(self):
        session = SimpleNamespace()
        required = AsyncMock()
        with (
            patch.object(logs.db, "async_session_maker", session_factory(session)),
            patch.object(
                logs.log_records_service,
                "requeue_tournament",
                AsyncMock(return_value=TournamentRequeue(discipline="overwatch", queue=[501, 502], replay={})),
            ) as requeue,
            patch.object(logs, "publish_required", required),
            patch.object(ingest, "process_ingest_job", AsyncMock()) as parse,
        ):
            await _fan_out()
        # The queued jobs' requests were committed by requeue_tournament itself (the outbox); nothing is sent here.
        requeue.assert_awaited_once_with(session, 42)
        parse.assert_not_awaited()
        required.assert_not_awaited()

    async def test_unknown_tournament_fails_the_request(self):
        with (
            patch.object(logs.db, "async_session_maker", session_factory(SimpleNamespace())),
            patch.object(
                logs.log_records_service, "requeue_tournament", AsyncMock(side_effect=RuntimeError("not found"))
            ),
            self.assertRaises(RuntimeError),
        ):
            await _fan_out()

    async def test_done_job_replays_go_to_the_ttl_less_replay_queue_with_their_revision_and_are_never_decoded_here(
        self,
    ):
        declare, required = AsyncMock(), AsyncMock()
        reparse = AsyncMock()
        with (
            patch.object(logs.db, "async_session_maker", session_factory(SimpleNamespace())),
            patch.object(
                logs.log_records_service,
                "requeue_tournament",
                AsyncMock(return_value=TournamentRequeue(discipline="overwatch", queue=[501], replay={601: 3})),
            ),
            patch.object(logs, "declare_replay_queues", declare),
            patch.object(logs, "publish_required", required),
            patch.object(ingest, "reparse_authorized_job", reparse),
        ):
            await _fan_out()
        reparse.assert_not_awaited()
        declare.assert_awaited_once_with(BROKER, "overwatch")  # before any replay publish, no consumer needed
        ((_, replay_queue, body),) = [c.args for c in required.await_args_list]
        self.assertEqual("stats.ingest.overwatch.replay", replay_queue.name)
        self.assertEqual(
            {"ingest_job_id": 601, "reparse_expected_revision": 3},
            {k: json.loads(body)[k] for k in ("ingest_job_id", "reparse_expected_revision")},
        )
        # A replay outlives any backlog: DONE jobs are not reaper-recoverable, so its queue must not expire messages.
        self.assertNotIn("x-message-ttl", replay_queue.arguments)
        self.assertTrue(replay_queue.durable)

    async def test_an_unroutable_replay_fails_the_request_instead_of_acknowledging_it(self):
        with (
            patch.object(logs.db, "async_session_maker", session_factory(SimpleNamespace())),
            patch.object(
                logs.log_records_service,
                "requeue_tournament",
                AsyncMock(return_value=TournamentRequeue(discipline="overwatch", queue=[], replay={601: 3})),
            ),
            patch.object(logs, "declare_replay_queues", AsyncMock()),
            patch.object(logs, "publish_required", AsyncMock(side_effect=_undeliverable())),
            self.assertRaises(DeliveryError),
        ):
            await _fan_out()

    async def test_publish_required_is_mandatory_on_a_raising_channel_and_declare_needs_no_consumer(self):
        published, declared = [], []

        class Exchange:
            async def publish(self, message, routing_key, mandatory):
                published.append((routing_key, mandatory, message.delivery_mode, message.body))
                if routing_key == "gone":
                    raise _undeliverable()

        channel = SimpleNamespace(default_exchange=Exchange())
        asked = []

        class Channels:
            async def get_channel(self, wanted):
                asked.append(wanted)
                return channel

        class Broker:
            config = SimpleNamespace(broker_config=SimpleNamespace(channel_manager=Channels()))

            async def declare_exchange(self, exchange):
                return exchange

            async def declare_queue(self, queue):
                declared.append(queue.name)
                return SimpleNamespace(bind=AsyncMock())

        broker = Broker()
        await topology.declare_replay_queues(broker, "overwatch")
        self.assertEqual(["stats.ingest.overwatch.replay.dlq", "stats.ingest.overwatch.replay"], declared)
        await topology.publish_required(broker, config.ingest_replay_queue("overwatch"), '{"a":1}')
        self.assertEqual(
            [("stats.ingest.overwatch.replay", True, aio_pika.DeliveryMode.PERSISTENT, b'{"a":1}')], published
        )
        self.assertTrue(asked[0].on_return_raises)
        with self.assertRaises(DeliveryError):
            await topology.publish_required(broker, SimpleNamespace(name="gone"), "{}")

    async def test_the_replay_consumer_runs_the_revision_fenced_reparse_and_reports_stale(self):
        msg = SimpleNamespace(headers={}, message_id=None, raw_message=None)
        session = SimpleNamespace(scalar=AsyncMock(return_value="overwatch"), rollback=AsyncMock())
        for outcome, effect in (("ok", None), ("stale", ingest.IngestRejected(409, "stale_revision", "stale"))):
            reparse = AsyncMock(side_effect=effect)
            claim = AsyncMock()
            with (
                self.subTest(outcome),
                patch.object(ingest.db, "async_session_maker", session_factory(session)),
                patch.object(ingest, "reparse_authorized_job", reparse),
                patch.object(ingest, "process_ingest_job", claim),
            ):
                await _replay("overwatch", {"ingest_job_id": 601, "reparse_expected_revision": 3}, msg)
            reparse.assert_awaited_once_with(session, job_id=601, expected_revision=3, s3=ingest.s3_client)
            claim.assert_not_awaited()

    async def test_the_replay_consumer_requeues_transient_failures_and_rejects_poison(self):
        session = SimpleNamespace(scalar=AsyncMock(return_value="overwatch"), rollback=AsyncMock())
        transient = (ingest.IngestRejected(503, "ingest_unavailable", "down"), SQLAlchemyError("conn"))
        for effect in transient:
            msg = SimpleNamespace(headers={}, message_id=None, raw_message=None, nack=AsyncMock())
            with (
                self.subTest(type(effect).__name__),
                patch.object(ingest.db, "async_session_maker", session_factory(session)),
                patch.object(ingest, "reparse_authorized_job", AsyncMock(side_effect=effect)),
            ):
                await _replay("overwatch", {"ingest_job_id": 601, "reparse_expected_revision": 3}, msg)
            msg.nack.assert_awaited_once_with(requeue=True)
        for effect in (ingest.IngestRejected(409, "stale_revision", "stale"), None):
            msg = SimpleNamespace(headers={}, message_id=None, raw_message=None, nack=AsyncMock())
            with (
                self.subTest("acknowledged"),
                patch.object(ingest.db, "async_session_maker", session_factory(session)),
                patch.object(ingest, "reparse_authorized_job", AsyncMock(side_effect=effect)),
            ):
                await _replay("overwatch", {"ingest_job_id": 601, "reparse_expected_revision": 3}, msg)
            msg.nack.assert_not_awaited()
        msg = SimpleNamespace(headers={}, message_id=None, raw_message=None, nack=AsyncMock())
        with (
            patch.object(ingest.db, "async_session_maker", session_factory(session)),
            patch.object(ingest, "reparse_authorized_job", AsyncMock(side_effect=RuntimeError("poison"))),
            self.assertRaises(RuntimeError),
        ):
            await _replay("overwatch", {"ingest_job_id": 601, "reparse_expected_revision": 3}, msg)
        msg.nack.assert_not_awaited()

    async def test_a_replay_delivered_to_a_worker_of_another_discipline_is_refused_undecoded(self):
        msg = SimpleNamespace(headers={}, message_id=None, raw_message=None)
        session = SimpleNamespace(scalar=AsyncMock(return_value="overwatch"), rollback=AsyncMock())
        reparse = AsyncMock()
        with (
            patch.object(ingest.db, "async_session_maker", session_factory(session)),
            patch.object(ingest, "reparse_authorized_job", reparse),
            self.assertRaises(ValueError),
        ):
            await _replay("lol", {"ingest_job_id": 601, "reparse_expected_revision": 3}, msg)
        reparse.assert_not_awaited()

    async def test_a_replay_request_on_the_ttl_ingest_queue_is_refused_and_a_plain_one_on_replay_too(self):
        msg = SimpleNamespace(headers={}, message_id=None, raw_message=None)
        reparse, claim = AsyncMock(), AsyncMock()
        with patch.object(ingest, "reparse_authorized_job", reparse), patch.object(ingest, "process_ingest_job", claim):
            with self.assertRaises(ValueError):
                await ingest.process_ingest_message(
                    "overwatch",
                    {"ingest_job_id": 601, "reparse_expected_revision": 3},
                    msg,
                    broker=BROKER,
                    logger=logger,
                )
            with self.assertRaises(ValueError):
                await _replay("overwatch", {"ingest_job_id": 601}, msg)
        reparse.assert_not_awaited()
        claim.assert_not_awaited()
