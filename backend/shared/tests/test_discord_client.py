"""``DiscordClient``: discord-service first, Discord REST only when it is silent.

Stdlib unittest like its siblings. The REST hop is stubbed at ``_http_get`` so
nothing here touches the network.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from shared.schemas.rpc import rpc_error, rpc_ok
from shared.services.discord_client import DiscordClient
from shared.services.subscriptions.providers.discord_role import (
    DiscordForbidden,
    DiscordNotConfigured,
    MemberNotFound,
)


def _reply(body):
    return MagicMock(decode=AsyncMock(return_value=body))


def _broker(*replies):
    broker = AsyncMock()
    broker.request.side_effect = list(replies)
    return broker


class TestMembers(IsolatedAsyncioTestCase):
    async def test_batch_prefetch_serves_every_member_read_from_one_rpc(self):
        broker = _broker(
            _reply(
                rpc_ok(
                    {
                        "guild_role_ids": ["1", "2"],
                        "members": {"a": {"found": True, "roles": ["2"]}, "b": {"found": False, "roles": []}},
                    }
                )
            )
        )
        client = DiscordClient(broker=broker, bot_token="t")

        with patch.object(DiscordClient, "_http_get", AsyncMock()) as rest:
            assert await client.prefetch("g", ["b", "a", "a"])
            assert await client.member_roles("g", "a") == ["2"]
            with self.assertRaises(MemberNotFound):
                await client.member_roles("g", "b")
            assert await client.is_member("g", "a") is True
            assert await client.is_member("g", "b") is False
            # The role-id set rode along in the batch: no second RPC for it.
            assert await client.guild_role_ids("g") == {"1", "2"}

        broker.request.assert_awaited_once()
        assert broker.request.await_args.args[0] == {"guild_id": "g", "user_ids": ["a", "b"]}
        rest.assert_not_awaited()

    async def test_rest_answers_when_discord_service_is_down(self):
        broker = _broker(RuntimeError("no broker"), RuntimeError("no broker"))
        client = DiscordClient(broker=broker, bot_token="t")
        rest = AsyncMock(side_effect=[{"roles": ["7"]}, MemberNotFound("404")])

        with patch.object(DiscordClient, "_http_get", rest):
            assert await client.member_roles("g", "a") == ["7"]
            assert await client.is_member("g", "b") is False
            # Memoized: asking again costs nothing.
            assert await client.member_roles("g", "a") == ["7"]

        assert rest.await_count == 2

    async def test_peer_error_is_not_a_verdict(self):
        """``guild_not_found`` from discord-service means "ask Discord yourself"."""
        client = DiscordClient(broker=_broker(_reply(rpc_error("not_found", "guild_not_found"))), bot_token="t")
        with patch.object(DiscordClient, "_http_get", AsyncMock(return_value={"roles": ["9"]})):
            assert await client.member_roles("g", "a") == ["9"]

    async def test_no_broker_and_no_token_is_not_configured(self):
        client = DiscordClient()
        with self.assertRaises(DiscordNotConfigured):
            await client.member_roles("g", "a")


class TestGuildReads(IsolatedAsyncioTestCase):
    async def test_rest_role_and_channel_shapes_match_discord_service(self):
        client = DiscordClient(bot_token="t")
        rest = AsyncMock(
            side_effect=[
                [
                    {"id": 1, "name": "low", "color": 0, "position": 0, "managed": False},
                    {"id": 2, "name": "high", "color": 0xFF, "position": 5, "managed": True},
                ],
                [
                    {"id": 10, "type": 4, "name": "Cat", "position": 0},
                    {"id": 11, "type": 0, "name": "b", "position": 2, "parent_id": 10},
                    {"id": 12, "type": 0, "name": "a", "position": 1, "parent_id": None},
                    {"id": 13, "type": 2, "name": "voice", "position": 0},
                ],
            ]
        )
        with patch.object(DiscordClient, "_http_get", rest):
            roles = await client.guild_roles("g")
            channels = await client.guild_channels("g")

        assert roles == [
            {"id": "2", "name": "high", "color": "#0000ff", "position": 5, "managed": True},
            {"id": "1", "name": "low", "color": None, "position": 0, "managed": False},
        ]
        assert channels == [
            {"id": "12", "name": "a", "category_name": None, "position": 1},
            {"id": "11", "name": "b", "category_name": "Cat", "position": 2},
        ]

    async def test_guild_info_survives_an_unreadable_owner(self):
        client = DiscordClient(bot_token="t")
        rest = AsyncMock(
            side_effect=[
                {"name": "S", "icon": "abc", "owner_id": "5", "approximate_member_count": 42},
                DiscordForbidden("403"),
            ]
        )
        with patch.object(DiscordClient, "_http_get", rest):
            info = await client.guild_info("g")

        assert info == {
            "guild_id": "g",
            "connected": True,
            "name": "S",
            "icon_url": "https://cdn.discordapp.com/icons/g/abc.png",
            "member_count": 42,
            "owner_id": "5",
            "owner_name": None,
            "owner_avatar_url": None,
        }

    async def test_a_guild_the_bot_cannot_see_is_forbidden(self):
        client = DiscordClient(bot_token="t")
        response = MagicMock(status_code=404)
        http = MagicMock()
        http.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=response)))
        http.__aexit__ = AsyncMock(return_value=False)
        with patch("shared.services.discord_client.httpx.AsyncClient", return_value=http):
            with self.assertRaises(DiscordForbidden):
                await client.guild_roles("g")
