"""Tests for balancer realtime ACL gating and WebSocket-derived presence."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "realtime-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from src.services import topic_acl as topic_acl_module  # noqa: E402
from src.services.connection_manager import (  # noqa: E402
    ConnectionManager,
    ConnectionState,
    is_presence_topic,
)


def _member_user(*workspace_ids: int) -> SimpleNamespace:
    allowed = set(workspace_ids)
    return SimpleNamespace(is_workspace_member=lambda workspace_id: workspace_id in allowed)


class BalancerTopicAclTests(IsolatedAsyncioTestCase):
    async def test_member_of_owning_workspace_is_allowed(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=7))
        allowed = await topic_acl_module._allow_tournament_balancer(
            _member_user(7), ("42",), session
        )
        self.assertTrue(allowed)

    async def test_non_member_is_denied(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=7))
        allowed = await topic_acl_module._allow_tournament_balancer(
            _member_user(99), ("42",), session
        )
        self.assertFalse(allowed)

    async def test_anonymous_is_denied_without_db_lookup(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=7))
        allowed = await topic_acl_module._allow_tournament_balancer(None, ("42",), session)
        self.assertFalse(allowed)
        session.scalar.assert_not_awaited()

    async def test_unknown_tournament_is_denied(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=None))
        allowed = await topic_acl_module._allow_tournament_balancer(
            _member_user(7), ("42",), session
        )
        self.assertFalse(allowed)

    async def test_non_numeric_group_is_denied(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=7))
        allowed = await topic_acl_module._allow_tournament_balancer(
            _member_user(7), ("abc",), session
        )
        self.assertFalse(allowed)

    async def test_registry_routes_balancer_topic_to_membership_check(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=7))
        self.assertTrue(
            await topic_acl_module.topic_acl_registry.allow(
                _member_user(7), "tournament:42:balancer", session
            )
        )
        self.assertFalse(
            await topic_acl_module.topic_acl_registry.allow(
                _member_user(1), "tournament:42:balancer", session
            )
        )

    async def test_registry_keeps_draft_topic_public(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=7))
        self.assertTrue(
            await topic_acl_module.topic_acl_registry.allow(None, "tournament:42:draft", session)
        )


class PresenceTopicTests(TestCase):
    def test_is_presence_topic(self) -> None:
        self.assertTrue(is_presence_topic("tournament:42:balancer"))
        self.assertFalse(is_presence_topic("tournament:42:draft"))
        self.assertFalse(is_presence_topic("workspace:5:notifications"))


class PresenceUserIdsTests(TestCase):
    def _state(self, user_id: int | None, *topics: str) -> ConnectionState:
        user = SimpleNamespace(id=user_id) if user_id is not None else None
        return ConnectionState(websocket=MagicMock(), user=user, topics=set(topics))

    def test_dedupes_multiple_tabs_of_same_user(self) -> None:
        manager = ConnectionManager()
        manager._states.add(self._state(1, "tournament:1:balancer"))
        manager._states.add(self._state(1, "tournament:1:balancer"))
        manager._states.add(self._state(2, "tournament:1:balancer"))
        self.assertEqual(manager.presence_user_ids("tournament:1:balancer"), [1, 2])

    def test_excludes_other_topics_and_anonymous(self) -> None:
        manager = ConnectionManager()
        manager._states.add(self._state(1, "tournament:1:balancer"))
        manager._states.add(self._state(3, "tournament:2:balancer"))
        manager._states.add(self._state(None, "tournament:1:balancer"))
        self.assertEqual(manager.presence_user_ids("tournament:1:balancer"), [1])
