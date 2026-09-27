"""Publish order for ``rpc.balancer.custom.post_signup``.

A queued Discord command cannot be recalled: once the card is on the broker the
bot posts it, whatever the database ends up saying. So the open signup window
has to be durable BEFORE the card is announced -- otherwise a failed commit
leaves a post in the channel whose every button answers ``signup_closed``, the
one outcome the card exists to avoid. Same commit-then-publish order the
achievement runner uses (``parser-service/src/services/achievement/engine/runner.py``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.schemas.events import DiscordCard  # noqa: E402
from src.rpc import custom  # noqa: E402

SUBJECT = "rpc.balancer.custom.post_signup"
WORKSPACE_ID = 9
GAME_ID = 11


class _CapturingBroker:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


class _Session:
    """A session that records the order of everything the handler does to it."""

    def __init__(self, calls: list[str], *, commit_fails: bool = False) -> None:
        self.calls = calls
        self.commit_fails = commit_fails

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.calls.append("commit")
        if self.commit_fails:
            raise RuntimeError("commit failed")


def _identity() -> dict:
    return {
        "user_id": 501,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [
            {
                "workspace_id": WORKSPACE_ID,
                "role": "organizer",
                "rbac_roles": ["organizer"],
                "rbac_permissions": [{"resource": "custom_game", "action": "update"}],
            }
        ],
    }


def _card() -> DiscordCard:
    return DiscordCard(text="**Запись на микс**")


class PostSignupPublishOrderTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def _call(self, *, commit_fails: bool) -> tuple[dict, list[str]]:
        calls: list[str] = []
        session = _Session(calls, commit_fails=commit_fails)
        broker = _CapturingBroker()
        custom.register(broker, _FakeLogger())
        service = AsyncMock()
        service.signup_post = AsyncMock(return_value=(555, _card()))
        self.publish = AsyncMock(side_effect=lambda *_a, **_kw: calls.append("publish"))
        with (
            patch.object(custom, "_SF", lambda: session),
            patch.object(custom, "custom_game_service", service),
            patch.object(custom, "publish_message", self.publish),
            patch.object(custom, "emit_pickup_mix_updated", AsyncMock()),
        ):
            data = {
                "identity": _identity(),
                "workspace_id": WORKSPACE_ID,
                "custom_game_id": GAME_ID,
                "payload": {"self_signup": "pool"},
            }
            return await broker.handlers[SUBJECT](data, None), calls

    async def test_the_card_is_queued_only_after_the_commit(self) -> None:
        result, calls = await self._call(commit_fails=False)

        self.assertTrue(result["ok"], result)
        self.assertEqual({"status": "queued", "channel_id": "555"}, result["data"])
        self.assertEqual(["commit", "publish"], calls)

    async def test_a_failed_commit_queues_no_card(self) -> None:
        result, calls = await self._call(commit_fails=True)

        self.assertFalse(result["ok"], result)
        self.assertEqual(["commit"], calls)
        self.publish.assert_not_awaited()
