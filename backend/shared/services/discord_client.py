"""The one door to Discord for every non-OAuth read in the platform.

discord-service holds discord.py's gateway cache and the only bot token, so
every lookup is a RabbitMQ RPC to it. There is no fallback: a bot that is down
cannot post either, so a read it cannot answer is honestly ``DiscordUnavailable``
rather than a second code path with a second copy of the token. OAuth
(identity-service) is the deliberate exception: it acts with the USER's token,
which the bot cannot do.

One instance per request. The RPC batch reply (``prefetch``) and the guild role
list are memoized on the instance so a batch of users costs one round trip and
the memo never outlives the request that filled it. A failed batch is memoized
too: its members raise the batch's error instead of each waiting out one more RPC.

Errors are the ``DiscordError`` family (:mod:`shared.services.discord_errors`):
the resolver's decision table already speaks that vocabulary and every caller
here does too.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from shared.messaging.config import (
    DISCORD_GUILD_CHANNELS_QUEUE,
    DISCORD_GUILD_ROLES_QUEUE,
    DISCORD_MEMBER_ROLES_QUEUE,
    DISCORD_VOICE_MOVE_QUEUE,
)
from shared.messaging.rpc import request_rpc
from shared.services.discord_errors import (
    DiscordError,
    DiscordForbidden,
    DiscordNotConfigured,
    DiscordUnavailable,
    MemberNotFound,
)

__all__ = ("DiscordClient",)

#: discord-service's own error codes (``_directory_reply``) as the caller's vocabulary.
_PEER_ERRORS: dict[str, type[DiscordError]] = {
    "not_found": DiscordForbidden,  # the bot is not in that guild
    "bad_request": DiscordError,  # a malformed id: a bug, not an outage
}


class DiscordClient:
    def __init__(self, *, broker: Any | None = None, rpc_timeout: float = 5.0) -> None:
        self._broker = broker
        self._rpc_timeout = rpc_timeout
        # (guild_id, user_id) -> role ids, or None for "not a member".
        self._members: dict[tuple[str, str], list[str] | None] = {}
        # guild_id -> why its batch failed.
        self._failed_batches: dict[str, DiscordError] = {}
        self._guild_role_ids: dict[str, set[str]] = {}
        self._guild_roles_lock = asyncio.Lock()

    # --- members ------------------------------------------------------------

    async def prefetch(self, guild_id: str, user_ids: Sequence[str]) -> None:
        """One RPC for a whole batch.

        Fills the member memo and the guild's role-id set, so the per-user
        ``member_roles`` calls that follow never touch the network — not even
        when the batch failed: they raise its error.
        """
        wanted = sorted({str(uid) for uid in user_ids if uid})
        if not wanted:
            return
        try:
            data = await self._rpc(DISCORD_MEMBER_ROLES_QUEUE, {"guild_id": guild_id, "user_ids": wanted})
        except DiscordError as exc:
            self._failed_batches[guild_id] = exc
            raise
        self._guild_role_ids[guild_id] = {str(r) for r in (data.get("guild_role_ids") or [])}
        for uid, info in (data.get("members") or {}).items():
            found = isinstance(info, dict) and bool(info.get("found"))
            self._members[(guild_id, str(uid))] = [str(r) for r in (info.get("roles") or [])] if found else None

    async def member_roles(self, guild_id: str, user_id: str) -> list[str]:
        """Role ids one member holds in ``guild_id``. Raises ``MemberNotFound`` when absent."""
        key = (guild_id, str(user_id))
        if key not in self._members:
            failure = self._failed_batches.get(guild_id)
            if failure is not None:
                raise type(failure)(*failure.args)
            await self.prefetch(guild_id, [user_id])
        roles = self._members.get(key)
        if roles is None:
            raise MemberNotFound("member not found")
        return roles

    # --- guild --------------------------------------------------------------

    async def guild_role_ids(self, guild_id: str) -> set[str]:
        # Lock, not just dict: a batch resolves concurrently and would otherwise
        # miss together and fire one roles request each.
        async with self._guild_roles_lock:
            cached = self._guild_role_ids.get(guild_id)
            if cached is None:
                cached = {str(role["id"]) for role in await self.guild_roles(guild_id)}
                self._guild_role_ids[guild_id] = cached
            return cached

    async def guild_roles(self, guild_id: str) -> list[dict[str, Any]]:
        """``[{id, name, color, position, managed}]``, highest position first."""
        data = await self._rpc(DISCORD_GUILD_ROLES_QUEUE, {"guild_id": guild_id})
        return list(data.get("roles") or [])

    async def guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        """Text, voice and category channels by position, with the bot's missing permissions."""
        data = await self._rpc(DISCORD_GUILD_CHANNELS_QUEUE, {"guild_id": guild_id})
        return list(data.get("channels") or [])

    # --- voice --------------------------------------------------------------

    async def voice_move(
        self,
        guild_id: str,
        *,
        category_id: str,
        moves: Sequence[Mapping[str, str]],
        drain: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Per-person results of one move."""
        payload = {"guild_id": guild_id, "category_id": category_id, "moves": list(moves), "drain": drain}
        data = await self._rpc(DISCORD_VOICE_MOVE_QUEUE, payload)
        return list(data.get("results") or [])

    # --- transport ----------------------------------------------------------

    async def _rpc(self, queue: Any, payload: dict[str, Any]) -> dict[str, Any]:
        """discord-service's ``data``; a peer error or a missing answer is a ``DiscordError``."""
        if self._broker is None:
            raise DiscordNotConfigured("no broker: discord-service cannot be asked")
        try:
            reply = await request_rpc(self._broker, payload, queue, timeout=self._rpc_timeout)
        except Exception as exc:  # noqa: BLE001 -- transport failure or timeout
            raise DiscordUnavailable(str(exc)) from exc
        if reply is None:
            raise DiscordUnavailable("discord-service did not answer")
        if not reply.ok:
            raise _PEER_ERRORS.get(reply.code or "", DiscordUnavailable)(reply.message or reply.code or "error")
        if not isinstance(reply.data, dict):
            raise DiscordUnavailable("discord-service answered without data")
        return reply.data
