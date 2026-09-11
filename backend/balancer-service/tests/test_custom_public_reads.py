from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.rpc import custom  # noqa: E402


class _Broker:
    """Collects the handlers ``custom.register`` decorates, keyed by subject."""

    def __init__(self) -> None:
        self.ops: dict[str, Any] = {}

    def subscriber(self, subject: str):
        def decorate(fn):
            self.ops[subject] = fn
            return fn

        return decorate


class _Session:
    async def __aenter__(self) -> Any:
        return object()

    async def __aexit__(self, *_: Any) -> bool:
        return False


class CustomMixPublicReadTests(IsolatedAsyncioTestCase):
    """A mix board is readable with no identity at all; writing one is not.

    The gateway forwards no identity for the mix reads (``AuthNone`` in
    ``gateway/internal/balancer/routes.go``), so a handler that asks for an
    actor answers every signed-out visitor with ``unauthorized`` instead of the
    lobby board they came for.
    """

    def setUp(self) -> None:
        self.broker = _Broker()
        custom.register(self.broker, MagicMock())

    async def _call(self, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        with patch.object(custom, "_SF", _Session):
            return await self.broker.ops[subject](data, None)

    async def test_listing_and_scoring_a_workspace_mixes_needs_no_identity(self) -> None:
        service = MagicMock()
        service.list = AsyncMock(return_value=[])
        service.hosts = AsyncMock(return_value={})
        service.casual_matches.activity_for_games = AsyncMock(return_value={})
        service.workspace_discord_channel_id = AsyncMock(return_value=None)
        service.mix_stats = AsyncMock(return_value=[])

        with patch.object(custom, "custom_game_service", service):
            listed = await self._call("rpc.balancer.custom.list", {"workspace_id": 7})
            scored = await self._call("rpc.balancer.custom.stats", {"workspace_id": 7})

        self.assertTrue(listed["ok"], listed)
        self.assertEqual([], listed["data"])
        self.assertTrue(scored["ok"], scored)
        self.assertEqual({"since": None, "members": []}, scored["data"])

    async def test_writing_one_still_requires_an_authenticated_actor(self) -> None:
        service = MagicMock()
        service.close = AsyncMock()

        with patch.object(custom, "custom_game_service", service):
            closed = await self._call("rpc.balancer.custom.close", {"workspace_id": 7, "custom_game_id": 3})

        self.assertFalse(closed["ok"], closed)
        self.assertEqual("unauthorized", closed["error"]["code"])
        service.close.assert_not_awaited()
