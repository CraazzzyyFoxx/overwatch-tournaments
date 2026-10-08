"""Who the voice RPCs think is asking, and for which workspace.

The page calls them with the mix's workspace in the path; the bot's buttons and
slash commands know only a ``custom_game_id``, so the mix row itself has to
supply the workspace before the membership gate can run at all.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.rpc import custom  # noqa: E402

WORKSPACE_ID = 9
GAME_ID = 11
REPORT = {"moved": 1, "results": []}


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
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False


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


class MixVoiceRpcTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.session = _Session()
        self.broker = _CapturingBroker()
        custom.register(self.broker, _FakeLogger())
        self.service = AsyncMock()
        self.service.voice_move = AsyncMock(return_value=REPORT)
        self.service.voice_return = AsyncMock(return_value=REPORT)
        self.service.games.get = AsyncMock(return_value=SimpleNamespace(id=GAME_ID, workspace_id=WORKSPACE_ID))
        patches = (
            patch.object(custom, "_SF", lambda: self.session),
            patch.object(custom, "custom_game_service", self.service),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_the_bots_move_takes_the_workspace_from_the_mix_it_names(self) -> None:
        result = await self.broker.handlers["rpc.balancer.custom.voice_move"](
            {"identity": _identity(), "custom_game_id": GAME_ID, "payload": {"lobby_index": 0}}, None
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(REPORT, result["data"])
        kwargs = self.service.voice_move.await_args.kwargs
        self.assertEqual(
            (WORKSPACE_ID, GAME_ID, 0),
            (kwargs["workspace_id"], kwargs["custom_game_id"], kwargs["lobby_index"]),
        )

    async def test_the_pages_return_needs_no_lookup_for_the_workspace_it_states(self) -> None:
        result = await self.broker.handlers["rpc.balancer.custom.voice_return"](
            {
                "identity": _identity(),
                "workspace_id": WORKSPACE_ID,
                "custom_game_id": GAME_ID,
                "payload": {"lobby_index": None},
            },
            None,
        )

        self.assertTrue(result["ok"], result)
        self.service.games.get.assert_not_awaited()
        self.assertIsNone(self.service.voice_return.await_args.kwargs["lobby_index"])

    async def test_a_move_naming_a_mix_that_is_gone_404(self) -> None:
        self.service.games.get = AsyncMock(return_value=None)

        result = await self.broker.handlers["rpc.balancer.custom.voice_move"](
            {"identity": _identity(), "custom_game_id": GAME_ID, "payload": {}}, None
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual("not_found", result["error"]["code"])
        self.service.voice_move.assert_not_awaited()
