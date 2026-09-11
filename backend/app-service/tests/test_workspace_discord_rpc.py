import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.schemas.rpc import rpc_ok
from shared.services.discord_client import DiscordClient
from shared.services.subscriptions.providers.discord_role import DiscordUnavailable
from src.rpc.workspaces import register

_IDENTITY = {"user_id": 1, "is_superuser": True, "is_active": True}


def _rpc_reply(body):
    """A FastStream RPC reply.

    ``broker.request`` returns the whole MESSAGE, not the handler's return value
    -- mocking it as a bare dict is what let the un-decoded call sites ship
    green while every real request degraded to the empty fallback.
    """
    return MagicMock(decode=AsyncMock(return_value=body))


def _register(fake_broker):
    """Register the subjects and hand back {subject: handler}."""
    registered: dict[str, object] = {}

    def fake_sub(topic):
        def dec(fn):
            registered[topic] = fn
            return fn

        return dec

    fake_broker.subscriber = fake_sub
    register(fake_broker, MagicMock())
    return registered


class WorkspaceDiscordRPCTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # These reads are gated on workspace.update like every sibling workspace
        # endpoint; the cases here cover the RPC round trip, so the gate is
        # stubbed and gets its own test below.
        self._perm = patch("src.rpc.workspaces.ensure_workspace_permission", MagicMock())
        self._perm.start()
        self.addCleanup(self._perm.stop)

    async def _call(self, subject: str, *, reply=None, error=None):
        fake_broker = MagicMock()
        handler = _register(fake_broker)[subject]
        fake_broker.request = AsyncMock(return_value=reply, side_effect=error)
        fake_ws = MagicMock(id=1, discord_guild_id="999")
        with patch("src.rpc.workspaces.workspace_service.get_by_id", AsyncMock(return_value=fake_ws)):
            return await handler({"workspace_id": 1, "identity": _IDENTITY}, MagicMock())

    async def test_discord_roles_handler(self) -> None:
        result = await self._call(
            "rpc.app.workspaces.discord_roles",
            reply=_rpc_reply(rpc_ok({"guild_id": "999", "roles": [{"id": "100", "name": "Admin"}]})),
        )
        self.assertEqual(result["data"]["roles"][0]["name"], "Admin")

    async def test_discord_channels_handler(self) -> None:
        result = await self._call(
            "rpc.app.workspaces.discord_channels",
            reply=_rpc_reply(rpc_ok({"guild_id": "999", "channels": [{"id": "555", "name": "match-logs"}]})),
        )
        self.assertEqual(result["data"]["channels"][0]["name"], "match-logs")

    async def test_discord_guild_handler(self) -> None:
        result = await self._call(
            "rpc.app.workspaces.discord_guild",
            reply=_rpc_reply(rpc_ok({"guild_id": "999", "connected": True, "name": "Server"})),
        )
        self.assertTrue(result["data"]["connected"])
        self.assertEqual(result["data"]["name"], "Server")

    async def test_non_object_reply_falls_back_to_discord_rest(self) -> None:
        """A peer answering with something other than an object is not a verdict:
        the picker asks Discord's REST API itself and still renders."""
        roles = [{"id": "1", "name": "Admin", "color": 0xFF0000, "position": 2, "managed": False}]
        with patch.object(DiscordClient, "_http_get", AsyncMock(return_value=roles)) as rest:
            result = await self._call("rpc.app.workspaces.discord_roles", reply=_rpc_reply("nope"))
        rest.assert_awaited_once()
        self.assertEqual(
            result["data"]["roles"], [{"id": "1", "name": "Admin", "color": "#ff0000", "position": 2, "managed": False}]
        )
        self.assertEqual(result["data"]["guild_id"], "999")

    async def test_both_transports_down_is_reported_not_raised(self) -> None:
        with patch.object(DiscordClient, "_http_get", AsyncMock(side_effect=DiscordUnavailable("down"))):
            result = await self._call("rpc.app.workspaces.discord_channels", error=TimeoutError("no reply"))
        self.assertEqual(result["data"]["channels"], [])
        self.assertIn("error", result["data"])


class WorkspaceDiscordPermissionTests(IsolatedAsyncioTestCase):
    async def test_discord_roles_requires_workspace_permission(self) -> None:
        """A guild's role list is private; the gate must run before the RPC."""
        from shared.core.errors import BaseAPIException

        fake_broker = MagicMock()
        handler = _register(fake_broker)["rpc.app.workspaces.discord_roles"]
        fake_broker.request = AsyncMock()

        denied = MagicMock(side_effect=BaseAPIException(status_code=403, detail="Forbidden"))
        with (
            patch("src.rpc.workspaces.ensure_workspace_permission", denied),
            patch(
                "src.rpc.workspaces.workspace_service.get_by_id",
                AsyncMock(return_value=MagicMock(id=1, discord_guild_id="999")),
            ),
        ):
            result = await handler({"workspace_id": 1, "identity": _IDENTITY}, MagicMock())

        self.assertNotIn("data", result)
        fake_broker.request.assert_not_awaited()

    async def test_discord_roles_rejects_anonymous_caller(self) -> None:
        fake_broker = MagicMock()
        handler = _register(fake_broker)["rpc.app.workspaces.discord_roles"]
        fake_broker.request = AsyncMock()

        result = await handler({"workspace_id": 1}, MagicMock())

        self.assertNotIn("data", result)
        fake_broker.request.assert_not_awaited()
