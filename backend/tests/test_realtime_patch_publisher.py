"""Tests for the shared realtime patch publisher helper."""

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

from shared.services import realtime_publisher  # noqa: E402


class PublishPatchTests(IsolatedAsyncioTestCase):
    async def test_tags_payload_with_resource_and_delegates(self) -> None:
        session = MagicMock()
        redis = MagicMock()
        with patch.object(
            realtime_publisher, "publish_event", AsyncMock(return_value="envelope")
        ) as publish_event:
            result = await realtime_publisher.publish_patch(
                session,
                redis,
                topic="tournament:7:draft",
                resource="draft.board",
                event_type="draft.pick_made",
                payload={"pick_id": 3},
                tournament_id=7,
                workspace_id=2,
                actor_user_id=9,
            )

        self.assertEqual(result, "envelope")
        publish_event.assert_awaited_once()
        kwargs = publish_event.await_args.kwargs
        self.assertEqual(kwargs["topic"], "tournament:7:draft")
        self.assertEqual(kwargs["event_type"], "draft.pick_made")
        self.assertEqual(kwargs["tournament_id"], 7)
        self.assertEqual(kwargs["workspace_id"], 2)
        self.assertEqual(kwargs["actor_user_id"], 9)
        # The resource tag is folded in alongside the caller's delta so a generic
        # frontend applier can route it; the delta fields are preserved.
        self.assertEqual(kwargs["payload"], {"resource": "draft.board", "pick_id": 3})

    async def test_defaults_payload_to_just_resource(self) -> None:
        with patch.object(realtime_publisher, "publish_event", AsyncMock()) as publish_event:
            await realtime_publisher.publish_patch(
                MagicMock(),
                None,
                topic="tournament:5:draft",
                resource="draft.board",
                event_type="draft.paused",
            )
        kwargs = publish_event.await_args.kwargs
        self.assertEqual(kwargs["payload"], {"resource": "draft.board"})
        self.assertIsNone(kwargs["workspace_id"])
        self.assertEqual(kwargs["schema_version"], 1)

    async def test_resource_key_constant_is_stable(self) -> None:
        # The frontend applier mirrors this key; changing it is a breaking change.
        self.assertEqual(realtime_publisher.PATCH_RESOURCE_KEY, "resource")
