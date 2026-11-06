"""``flow.node.state.changed``: every replica reloads its channel registry; a stage going live or completing wakes a voice sync."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rabbit.gateway import DiscordRabbitGateway  # noqa: E402


def body(kind: str, new_status: str, old_status: str) -> dict[str, object]:
    return {
        "tournament_id": 7,
        "workspace_id": 1,
        "node_id": 11,
        "kind": kind,
        "old_status": old_status,
        "new_status": new_status,
    }


class FlowNodeStateChangedTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = MagicMock(reload=AsyncMock())
        self.voice_sync = MagicMock()
        self.gateway = DiscordRabbitGateway(
            settings=MagicMock(),
            processor=MagicMock(),
            registry=self.registry,
            directory=MagicMock(),
            voice=MagicMock(),
            voice_sync=self.voice_sync,
            bot=MagicMock(),
            session_maker=MagicMock(),
            projector=MagicMock(),
        )

    async def test_stage_completion_requests_voice_sync(self) -> None:
        await self.gateway._on_flow_node_state_changed(body("stage", "completed", "live"))

        self.registry.reload.assert_awaited_once()
        self.voice_sync.request.assert_called_once_with(7)

    async def test_stage_going_live_requests_voice_sync(self) -> None:
        await self.gateway._on_flow_node_state_changed(body("stage", "live", "ready"))

        self.registry.reload.assert_awaited_once()
        self.voice_sync.request.assert_called_once_with(7)

    async def test_registration_node_change_reloads_registry_only(self) -> None:
        await self.gateway._on_flow_node_state_changed(body("registration", "open", "draft"))

        self.registry.reload.assert_awaited_once()
        self.voice_sync.request.assert_not_called()
