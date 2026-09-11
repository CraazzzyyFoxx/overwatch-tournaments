"""Guild/member introspection served over RabbitMQ RPC to other services.

Wraps discord.py's gateway cache with a REST fallback, since a guild the bot
hasn't cached (e.g. right after a restart, before ``GUILD_CREATE`` events land)
still needs to answer these lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord
from loguru import logger


@dataclass(slots=True, frozen=True)
class DirectoryOutcome:
    """An RPC-ready result: ``status`` for observability, ``payload`` for the wire."""

    status: str
    payload: dict[str, Any]


class DiscordDirectoryService:
    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def _lookup_guild(self, guild_id: str) -> tuple[discord.Guild | None, bool]:
        """Resolve a snowflake to a guild, preferring discord.py's gateway cache.

        The flag says whether the guild came from that cache. It matters: the
        ``fetch_guild`` fallback is a single REST call whose payload carries roles
        but NO channels, members or threads, so ``guild.text_channels`` on a fetched
        guild is silently empty and ``member_count`` is ``None``. Callers needing
        those must fetch them explicitly -- see ``get_guild_channels``.
        """
        try:
            guild_id_int = int(guild_id)
        except ValueError:
            return None, False

        cached = self._client.get_guild(guild_id_int)
        if cached is not None:
            return cached, True

        try:
            # NotFound/Forbidden both derive from HTTPException: "we cannot see this
            # guild" is one outcome here, not three.
            return await self._client.fetch_guild(guild_id_int), False
        except discord.HTTPException:
            return None, False

    @staticmethod
    async def _lookup_member(guild: discord.Guild, user_id: str) -> discord.Member | None:
        """Member from the guild's member cache, else one REST lookup."""
        try:
            user_id_int = int(user_id)
        except ValueError:
            return None

        cached = guild.get_member(user_id_int)
        if cached is not None:
            return cached

        try:
            return await guild.fetch_member(user_id_int)
        except discord.HTTPException:
            return None

    async def get_member_roles(self, guild_id: str, user_ids: list[str]) -> DirectoryOutcome:
        if not guild_id:
            return DirectoryOutcome("invalid", {"error": "guild_id_required", "guild_role_ids": [], "members": {}})

        try:
            guild, _cached = await self._lookup_guild(guild_id)
            if guild is None:
                return DirectoryOutcome(
                    "guild_not_found", {"error": "guild_not_found", "guild_role_ids": [], "members": {}}
                )

            guild_role_ids = [str(role.id) for role in guild.roles]
            members_out: dict[str, dict[str, Any]] = {}

            for uid_str in user_ids:
                member = await self._lookup_member(guild, uid_str)
                if member is None:
                    members_out[uid_str] = {"found": False, "roles": []}
                    continue
                # Drop @everyone. Discord's REST member object omits it, and
                # the caller's HTTP fallback reads that object -- so leaving
                # it in would let a tier mapped to @everyone resolve ACTIVE
                # over RPC and INACTIVE over HTTP for the very same patron.
                members_out[uid_str] = {
                    "found": True,
                    "roles": [str(role.id) for role in member.roles if not role.is_default()],
                }

            return DirectoryOutcome("success", {"guild_role_ids": guild_role_ids, "members": members_out})
        except Exception as e:
            logger.error(f"❌ Error getting member roles for guild {guild_id}: {e}")
            return DirectoryOutcome("error", {"error": str(e), "guild_role_ids": [], "members": {}})

    async def get_guild_roles(self, guild_id: str) -> DirectoryOutcome:
        if not guild_id:
            return DirectoryOutcome("invalid", {"error": "guild_id_required", "guild_id": guild_id, "roles": []})

        try:
            guild, _cached = await self._lookup_guild(guild_id)
            if guild is None:
                return DirectoryOutcome(
                    "guild_not_found", {"error": "guild_not_found", "guild_id": guild_id, "roles": []}
                )

            roles_out = []
            # Highest first: that is the order the Discord client shows, and
            # the picker on the other end renders the list as-is.
            for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
                color_hex = f"#{role.color.value:06x}" if role.color.value else None
                roles_out.append(
                    {
                        "id": str(role.id),
                        "name": role.name,
                        "color": color_hex,
                        "position": role.position,
                        "managed": role.managed,
                    }
                )

            return DirectoryOutcome("success", {"guild_id": guild_id, "roles": roles_out})
        except Exception as e:
            logger.error(f"❌ Error getting guild roles for {guild_id}: {e}")
            return DirectoryOutcome("error", {"error": str(e), "guild_id": guild_id, "roles": []})

    async def get_guild_channels(self, guild_id: str) -> DirectoryOutcome:
        if not guild_id:
            return DirectoryOutcome("invalid", {"error": "guild_id_required", "guild_id": guild_id, "channels": []})

        try:
            guild, cached = await self._lookup_guild(guild_id)
            if guild is None:
                return DirectoryOutcome(
                    "guild_not_found", {"error": "guild_not_found", "guild_id": guild_id, "channels": []}
                )

            if cached:
                text_channels = list(guild.text_channels)
            else:
                # A fetched guild has no channel cache at all, so reading
                # ``guild.text_channels`` here would answer "no channels" for
                # a server that has plenty.
                text_channels = [ch for ch in await guild.fetch_channels() if isinstance(ch, discord.TextChannel)]

            channels_out = [
                {
                    "id": str(ch.id),
                    "name": ch.name,
                    "category_name": ch.category.name if ch.category else None,
                    "position": ch.position,
                }
                for ch in sorted(text_channels, key=lambda c: c.position)
            ]

            return DirectoryOutcome("success", {"guild_id": guild_id, "channels": channels_out})
        except Exception as e:
            logger.error(f"❌ Error getting guild channels for {guild_id}: {e}")
            return DirectoryOutcome("error", {"error": str(e), "guild_id": guild_id, "channels": []})

    async def get_guild_info(self, guild_id: str) -> DirectoryOutcome:
        if not guild_id:
            return DirectoryOutcome("invalid", {"error": "guild_id_required", "connected": False})

        try:
            guild, cached = await self._lookup_guild(guild_id)
            if guild is None:
                return DirectoryOutcome(
                    "guild_not_found",
                    {
                        "guild_id": guild_id,
                        "connected": False,
                        "name": None,
                        "icon_url": None,
                        "member_count": 0,
                        "owner_id": None,
                        "owner_name": None,
                        "owner_avatar_url": None,
                    },
                )

            icon_url = str(guild.icon.url) if guild.icon else None
            # ``member_count`` is only populated from the gateway payload; a
            # guild we had to fetch carries ``approximate_member_count``
            # instead, and an empty member cache would otherwise report 0.
            member_count = (guild.member_count if cached else guild.approximate_member_count) or 0
            owner = getattr(guild, "owner", None)
            owner_id = getattr(guild, "owner_id", None)
            owner_avatar = None
            if owner is not None:
                display_avatar = getattr(owner, "display_avatar", None)
                owner_avatar = str(display_avatar.url) if display_avatar else None

            return DirectoryOutcome(
                "success",
                {
                    "guild_id": guild_id,
                    "connected": True,
                    "name": guild.name,
                    "icon_url": icon_url,
                    "member_count": member_count,
                    "owner_id": str(owner_id) if owner_id is not None else None,
                    "owner_name": (owner.display_name if owner is not None else None),
                    "owner_avatar_url": owner_avatar,
                },
            )
        except Exception as e:
            logger.error(f"❌ Error getting guild info for {guild_id}: {e}")
            return DirectoryOutcome("error", {"error": str(e), "guild_id": guild_id, "connected": False})
