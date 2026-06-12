"""Tests for the shared balancer realtime publisher helper."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.services import balancer_realtime  # noqa: E402


class PublishBalancerEventTests(IsolatedAsyncioTestCase):
    async def test_targets_tournament_balancer_topic_and_folds_tournament_id(self) -> None:
        session = MagicMock()
        redis = MagicMock()
        with patch.object(
            balancer_realtime, "publish_event", AsyncMock(return_value="envelope")
        ) as publish_event:
            result = await balancer_realtime.publish_balancer_event(
                session,
                redis,
                tournament_id=7,
                event_type=balancer_realtime.BALANCER_BALANCE_SAVED,
                payload={"balance_id": 12},
                workspace_id=3,
                actor_user_id=9,
            )

        self.assertEqual(result, "envelope")
        publish_event.assert_awaited_once()
        kwargs = publish_event.await_args.kwargs
        self.assertEqual(kwargs["topic"], "tournament:7:balancer")
        self.assertEqual(kwargs["event_type"], "balancer.balance_saved")
        self.assertEqual(kwargs["workspace_id"], 3)
        self.assertEqual(kwargs["tournament_id"], 7)
        self.assertEqual(kwargs["actor_user_id"], 9)
        # tournament_id is always present in the payload so a multi-topic client
        # can route locally, alongside the caller-provided fields.
        self.assertEqual(kwargs["payload"], {"tournament_id": 7, "balance_id": 12})

    async def test_defaults_payload_to_just_tournament_id(self) -> None:
        with patch.object(balancer_realtime, "publish_event", AsyncMock()) as publish_event:
            await balancer_realtime.publish_balancer_event(
                MagicMock(),
                None,
                tournament_id=5,
                event_type=balancer_realtime.BALANCER_REGISTRATIONS_CHANGED,
            )
        kwargs = publish_event.await_args.kwargs
        self.assertEqual(kwargs["payload"], {"tournament_id": 5})
        self.assertIsNone(kwargs["workspace_id"])


class EventTypeConstantsTests(IsolatedAsyncioTestCase):
    async def test_event_type_literals_are_stable(self) -> None:
        # The frontend mirrors these literals; changing them is a breaking change.
        self.assertEqual(balancer_realtime.BALANCER_REGISTRATIONS_CHANGED, "balancer.registrations_changed")
        self.assertEqual(balancer_realtime.BALANCER_BALANCE_SAVED, "balancer.balance_saved")
        self.assertEqual(balancer_realtime.BALANCER_TEAMS_CHANGED, "balancer.teams_changed")
        self.assertEqual(balancer_realtime.BALANCER_CONFIG_CHANGED, "balancer.config_changed")
        self.assertEqual(balancer_realtime.BALANCER_JOB_QUEUED, "balancer_job.queued")
        self.assertEqual(balancer_realtime.BALANCER_JOB_RUNNING, "balancer_job.running")
        self.assertEqual(balancer_realtime.BALANCER_JOB_PROGRESS, "balancer_job.progress")
        self.assertEqual(balancer_realtime.BALANCER_JOB_SUCCEEDED, "balancer_job.succeeded")
        self.assertEqual(balancer_realtime.BALANCER_JOB_FAILED, "balancer_job.failed")
        self.assertEqual(balancer_realtime.BALANCER_PRESENCE, "balancer.presence")
