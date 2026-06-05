from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "realtime-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

topic_acl = importlib.import_module("src.services.topic_acl")


class _ExplodingSession:
    """The public draft ACL must not hit the DB."""

    async def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("public draft ACL must not query the session")


class DraftAclTests(IsolatedAsyncioTestCase):
    async def test_anonymous_spectator_allowed(self) -> None:
        allowed = await topic_acl.topic_acl_registry.allow(None, "tournament:5:draft", _ExplodingSession())
        self.assertTrue(allowed)

    async def test_arbitrary_tournament_id_allowed(self) -> None:
        allowed = await topic_acl.topic_acl_registry.allow(None, "tournament:99999:draft", _ExplodingSession())
        self.assertTrue(allowed)

    async def test_non_draft_unknown_topic_denied(self) -> None:
        # A topic matching no rule is denied by default.
        allowed = await topic_acl.topic_acl_registry.allow(None, "tournament:5:unknown_topic", _ExplodingSession())
        self.assertFalse(allowed)
