"""Gate contract for ``rpc.balancer.admin.workspace_config_upsert``.

The workspace balancer config carries two unrelated things in one blob: the
pool's rank-delta knobs (a balancer-tool setting, ``team.update``) and the
Discord channel every mix announces in (the workspace's own server,
``workspace.update``). The write used to demand ``workspace.update`` for the
whole payload, so an organizer saving a threshold was rejected over a channel
they were not touching.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from src.rpc import admin as admin_rpc  # noqa: E402

SUBJECT = "rpc.balancer.admin.workspace_config_upsert"
WORKSPACE_ID = 9


class _CapturingBroker:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

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


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _handler():
    broker = _CapturingBroker()
    admin_rpc.register(broker, _FakeLogger())
    return broker.handlers[SUBJECT]


def _identity(*permissions: tuple[str, str]) -> dict:
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
                "rbac_permissions": [{"resource": resource, "action": action} for resource, action in permissions],
            }
        ],
    }


# Builds teams, does not administer the workspace.
ORGANIZER = _identity(("team", "read"), ("team", "update"))
ADMIN = _identity(("team", "update"), ("workspace", "update"))
# Admin-panel access (tournament.update) but no say over the balancer pool.
BYSTANDER = _identity(("team", "read"), ("tournament", "update"))


def _stored(channel: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        workspace_id=WORKSPACE_ID,
        config_json={
            "rank_delta_threshold": 500,
            "rank_delta_hide_from_pool": True,
            "mix_discord_channel_id": channel,
        },
        updated_by=None,
    )


def _request(identity: dict, channel: str | None, threshold: int | None = 700) -> dict:
    return {
        "id": WORKSPACE_ID,
        "identity": identity,
        "payload": {
            "rank_delta_threshold": threshold,
            "rank_delta_hide_from_pool": True,
            "mix_discord_channel_id": channel,
        },
    }


class WorkspaceConfigUpsertGateTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def _call(self, data: dict, *, stored_channel: str | None) -> dict:
        self.upsert = AsyncMock(return_value=_stored(stored_channel))
        with (
            patch.object(admin_rpc, "_SF", lambda: _FakeSession()),
            patch.object(
                admin_rpc.balancer_admin_service,
                "get_workspace_balancer_config",
                AsyncMock(return_value=_stored(stored_channel)),
            ),
            patch.object(admin_rpc.balancer_admin_service, "upsert_workspace_balancer_config", self.upsert),
        ):
            return await _handler()(data, None)

    async def test_organizer_saves_the_pool_knobs_with_the_channel_unchanged(self) -> None:
        response = await self._call(_request(ORGANIZER, "555"), stored_channel="555")

        assert response["ok"] is True, response
        assert self.upsert.await_args.kwargs["rank_delta_threshold"] == 700
        # The unchanged channel still rides along: the upsert rewrites the blob.
        assert self.upsert.await_args.kwargs["mix_discord_channel_id"] == "555"

    async def test_organizer_may_not_repoint_the_mix_channel(self) -> None:
        response = await self._call(_request(ORGANIZER, "777"), stored_channel="555")

        assert response["ok"] is False
        assert response["error"]["code"] == "forbidden"
        self.upsert.assert_not_awaited()

    async def test_organizer_may_not_clear_the_mix_channel(self) -> None:
        response = await self._call(_request(ORGANIZER, None), stored_channel="555")

        assert response["ok"] is False
        assert response["error"]["code"] == "forbidden"
        self.upsert.assert_not_awaited()

    async def test_admin_repoints_the_mix_channel(self) -> None:
        response = await self._call(_request(ADMIN, "777"), stored_channel="555")

        assert response["ok"] is True, response
        assert self.upsert.await_args.kwargs["mix_discord_channel_id"] == "777"

    async def test_pool_knobs_still_need_team_update(self) -> None:
        response = await self._call(_request(BYSTANDER, "555"), stored_channel="555")

        assert response["ok"] is False
        assert response["error"]["code"] == "forbidden"
        self.upsert.assert_not_awaited()
