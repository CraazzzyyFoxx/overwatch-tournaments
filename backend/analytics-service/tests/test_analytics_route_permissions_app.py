"""Permission coverage for the analytics mutation RPC handlers.

The HTTP routes were decommissioned (FastAPI removed from analytics-service);
the mutations now run as ``rpc.analytics.*`` FastStream subscribers in
``serve_rpc.py``. This test drives the real ``src.rpc.mutations.register``
through a fake broker and asserts that the ``shift`` handler still gates on the
``analytics.update`` permission — the same contract the old
``POST /analytics/shift`` route enforced. The permission check fires before any
DB access, so a no-op session factory keeps this a pure unit test.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from unittest import TestCase

# Ensure the analytics-service ``src`` package resolves regardless of pytest
# collection order / invocation cwd (matches how the suite is run).
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.models.auth_user import AuthUser

from src.core import db
from src.rpc import mutations


class _FakeBroker:
    """Capture FastStream subscribers by subject so we can invoke them directly."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def _decorator(fn):
            self.handlers[subject] = fn
            return fn

        return _decorator


class _NoopSession:
    """A dummy async session context. ``envelope`` opens the session factory
    before running the handler body, but the ``shift`` permission gate raises
    before the session is ever queried — so a no-op session keeps this DB-free.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _no_permission_user() -> AuthUser:
    user = AuthUser(email="x@example.com", username="x", is_active=True, is_superuser=False)
    user.set_rbac_cache(role_names=[], permissions=[])
    return user


class AnalyticsMutationPermissionTests(TestCase):
    def setUp(self) -> None:
        self._original_sf = db.async_session_maker
        # The permission gate raises before the session factory is entered; the
        # noop factory asserts that invariant instead of touching a real DB.
        db.async_session_maker = lambda: _NoopSession()
        self.broker = _FakeBroker()
        mutations.register(self.broker, logging.getLogger("test"))

    def tearDown(self) -> None:
        db.async_session_maker = self._original_sf

    def test_shift_handler_is_registered(self) -> None:
        self.assertIn("rpc.analytics.shift", self.broker.handlers)

    def test_shift_requires_analytics_update_permission(self) -> None:
        handler = self.broker.handlers["rpc.analytics.shift"]
        identity = {
            "user_id": 1,
            "sub": "1",
            "is_active": True,
            "is_superuser": False,
            "roles": [],
            "permissions": [],
        }
        data = {"identity": identity, "payload": {"player_id": 1, "shift": 0}}

        envelope = asyncio.run(handler(data, msg=None))

        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "forbidden")
