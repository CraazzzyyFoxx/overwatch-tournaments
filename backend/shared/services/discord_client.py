"""The one door to Discord for every non-OAuth read in the platform.

discord-service holds discord.py's gateway cache, so every lookup goes there
first over RabbitMQ RPC; Discord's REST API is the fallback, used only when the
broker is absent, the round trip fails, or the peer answers with an error.
OAuth (identity-service) is the deliberate exception: it acts with the USER's
token, which the bot cannot do.

One instance per request. The RPC batch reply (``prefetch``) and the guild role
list are memoized on the instance so a batch of users costs one round trip and
the memo never outlives the request that filled it.

Errors are the ``DiscordError`` family from
``shared.services.subscriptions.providers.discord_role``: the resolver's decision
table already speaks that vocabulary and every caller here does too.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Final

import httpx
from loguru import logger

from shared.messaging.config import (
    DISCORD_GUILD_CHANNELS_QUEUE,
    DISCORD_GUILD_INFO_QUEUE,
    DISCORD_GUILD_ROLES_QUEUE,
    DISCORD_MEMBER_ROLES_QUEUE,
)
from shared.messaging.rpc import request_rpc
from shared.services.subscriptions.providers.discord_role import (
    DiscordError,
    DiscordForbidden,
    DiscordNotConfigured,
    DiscordUnavailable,
    MemberNotFound,
)

__all__ = ("DISCORD_API_BASE", "DiscordClient")

DISCORD_API_BASE: Final = "https://discord.com/api/v10"
_CDN: Final = "https://cdn.discordapp.com"
_TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)
_GUILD_TEXT: Final = 0
_GUILD_CATEGORY: Final = 4


class DiscordClient:
    def __init__(
        self,
        *,
        broker: Any | None = None,
        bot_token: str | None = None,
        proxy: str | None = None,
        api_base: str = DISCORD_API_BASE,
        rpc_timeout: float = 5.0,
    ) -> None:
        self._broker = broker
        self._bot_token = bot_token
        self._proxy = proxy
        self._api_base = api_base
        self._rpc_timeout = rpc_timeout
        # (guild_id, user_id) -> role ids, or None for "not a member".
        self._members: dict[tuple[str, str], list[str] | None] = {}
        self._guild_role_ids: dict[str, set[str]] = {}
        self._guild_roles_lock = asyncio.Lock()

    # --- members ------------------------------------------------------------

    async def prefetch(self, guild_id: str, user_ids: Sequence[str]) -> bool:
        """One RPC for a whole batch; ``False`` when discord-service did not answer.

        Fills the member memo and the guild's role-id set, so the per-user
        ``member_roles`` calls that follow never touch the network.
        """
        wanted = sorted({str(uid) for uid in user_ids if uid})
        if not wanted:
            return False
        data = await self._rpc(DISCORD_MEMBER_ROLES_QUEUE, {"guild_id": guild_id, "user_ids": wanted})
        if data is None or "members" not in data:
            return False
        self._guild_role_ids[guild_id] = {str(r) for r in (data.get("guild_role_ids") or [])}
        for uid, info in (data.get("members") or {}).items():
            found = isinstance(info, dict) and bool(info.get("found"))
            self._members[(guild_id, str(uid))] = [str(r) for r in (info.get("roles") or [])] if found else None
        return True

    async def member_roles(self, guild_id: str, user_id: str) -> list[str]:
        """Role ids one member holds in ``guild_id``. Raises ``MemberNotFound`` when absent."""
        key = (guild_id, str(user_id))
        if key not in self._members and not await self.prefetch(guild_id, [user_id]):
            self._members[key] = await self._http_member_roles(guild_id, str(user_id))
        roles = self._members[key]
        if roles is None:
            raise MemberNotFound("member not found")
        return roles

    async def is_member(self, guild_id: str, user_id: str) -> bool:
        try:
            await self.member_roles(guild_id, user_id)
        except MemberNotFound:
            return False
        return True

    # --- guild --------------------------------------------------------------

    async def guild_role_ids(self, guild_id: str) -> set[str]:
        # Lock, not just dict: a batch resolves concurrently and would otherwise
        # miss together and fire one roles request each into the same per-guild
        # rate-limit bucket.
        async with self._guild_roles_lock:
            cached = self._guild_role_ids.get(guild_id)
            if cached is None:
                cached = {str(role["id"]) for role in await self.guild_roles(guild_id)}
                self._guild_role_ids[guild_id] = cached
            return cached

    async def guild_roles(self, guild_id: str) -> list[dict[str, Any]]:
        """``[{id, name, color, position, managed}]``, highest position first."""
        data = await self._rpc(DISCORD_GUILD_ROLES_QUEUE, {"guild_id": guild_id})
        if data is not None and "roles" in data:
            return list(data["roles"])
        raw = await self._http_get(f"/guilds/{guild_id}/roles")
        return [
            {
                "id": str(role["id"]),
                "name": role.get("name"),
                "color": f"#{role['color']:06x}" if role.get("color") else None,
                "position": role.get("position", 0),
                "managed": bool(role.get("managed")),
            }
            for role in sorted(raw or [], key=lambda r: r.get("position", 0), reverse=True)
        ]

    async def guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        """Text channels as ``[{id, name, category_name, position}]`` by position."""
        data = await self._rpc(DISCORD_GUILD_CHANNELS_QUEUE, {"guild_id": guild_id})
        if data is not None and "channels" in data:
            return list(data["channels"])
        raw = await self._http_get(f"/guilds/{guild_id}/channels") or []
        categories = {str(ch["id"]): ch.get("name") for ch in raw if ch.get("type") == _GUILD_CATEGORY}
        text = [ch for ch in raw if ch.get("type") == _GUILD_TEXT]
        return [
            {
                "id": str(ch["id"]),
                "name": ch.get("name"),
                "category_name": categories.get(str(ch.get("parent_id") or "")),
                "position": ch.get("position", 0),
            }
            for ch in sorted(text, key=lambda c: c.get("position", 0))
        ]

    async def guild_info(self, guild_id: str) -> dict[str, Any]:
        """``{guild_id, connected, name, icon_url, member_count, owner_id, owner_name, owner_avatar_url}``."""
        data = await self._rpc(DISCORD_GUILD_INFO_QUEUE, {"guild_id": guild_id})
        if data is not None and "connected" in data:
            return dict(data)
        guild = await self._http_get(f"/guilds/{guild_id}", params={"with_counts": "true"})
        owner_id = guild.get("owner_id")
        owner: dict[str, Any] = {}
        if owner_id:
            try:
                owner = await self._http_get(f"/users/{owner_id}")
            except DiscordError:
                owner = {}
        icon = guild.get("icon")
        avatar = owner.get("avatar")
        return {
            "guild_id": guild_id,
            "connected": True,
            "name": guild.get("name"),
            "icon_url": f"{_CDN}/icons/{guild_id}/{icon}.png" if icon else None,
            "member_count": guild.get("approximate_member_count") or 0,
            "owner_id": str(owner_id) if owner_id else None,
            "owner_name": owner.get("global_name") or owner.get("username"),
            "owner_avatar_url": f"{_CDN}/avatars/{owner_id}/{avatar}.png" if avatar else None,
        }

    # --- transports ---------------------------------------------------------

    async def _rpc(self, queue: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
        """discord-service's ``data``, or ``None`` for anything that is not a usable answer.

        A peer error (``guild_not_found``, ``bad_request``...) is NOT a verdict:
        it means "ask Discord yourself", so it degrades to the REST path like a
        timeout does.
        """
        if self._broker is None:
            return None
        try:
            reply = await request_rpc(self._broker, payload, queue, timeout=self._rpc_timeout)
        except Exception as exc:  # noqa: BLE001 -- any transport failure means "fall back"
            logger.warning(f"discord-service RPC {queue} failed, falling back to REST: {exc}")
            return None
        if reply is None or not reply.ok or not isinstance(reply.data, dict):
            return None
        return reply.data

    async def _http_member_roles(self, guild_id: str, user_id: str) -> list[str] | None:
        # 404 = not a member (a real answer); it does NOT count toward Discord's
        # invalid-request ban budget, unlike 401/403/429.
        try:
            body = await self._http_get(f"/guilds/{guild_id}/members/{user_id}", not_found=MemberNotFound)
        except MemberNotFound:
            return None
        return [str(role_id) for role_id in (body.get("roles") or [])]

    async def _http_get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        not_found: type[DiscordError] = DiscordForbidden,
    ) -> Any:
        """GET against Discord. A 404 on a guild resource means the bot cannot see it."""
        if not self._bot_token:
            raise DiscordNotConfigured("discord bot token is not configured")
        # ponytail: a client per call; pool one per instance if the REST fallback ever gets hot.
        try:
            async with httpx.AsyncClient(
                proxy=self._proxy, timeout=_TIMEOUT, headers={"Authorization": f"Bot {self._bot_token}"}
            ) as client:
                response = await client.get(f"{self._api_base}{path}", params=params)
        except httpx.HTTPError as exc:
            raise DiscordUnavailable(str(exc)) from exc
        status = response.status_code
        if status == 404:
            raise not_found(f"status 404 for {path}")
        if status in (401, 403):
            raise DiscordForbidden(f"status {status}")
        if status != 200:
            raise DiscordUnavailable(f"status {status}")
        return response.json()
