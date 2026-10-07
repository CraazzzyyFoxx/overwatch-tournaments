"""Moves guild members between voice channels on a mix host's behalf.

The platform decides who goes where; this checks only what Discord can see
right now -- who is connected, and whether a channel is a voice of the
workspace's category -- and answers per person. Voice state lives in the
gateway cache alone, which is why there is no REST fallback: an uncached guild
is "not found".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import discord

from src.services.directory import DirectoryOutcome

__all__ = ("VoiceMover",)

_REASON = "OWT mix"


class VoiceMover:
    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def move(
        self,
        guild_id: str,
        *,
        category_id: str,
        moves: Sequence[Mapping[str, Any]],
        drain: Mapping[str, Any] | None,
    ) -> DirectoryOutcome:
        if not guild_id.isdigit() or not category_id.isdigit():
            return DirectoryOutcome("invalid", {"error": "guild_id_and_category_id_required", "results": []})
        guild = self._client.get_guild(int(guild_id))
        if guild is None:
            return DirectoryOutcome("guild_not_found", {"error": "guild_not_found", "results": []})
        category = int(category_id)
        results: list[dict[str, Any]] = []
        # ponytail: one member at a time; discord.py waits out the per-guild rate limit.
        for move in moves:
            user_id, channel_id = str(move["discord_user_id"]), str(move["channel_id"])
            member = guild.get_member(int(user_id)) if user_id.isdigit() else None
            current = member.voice.channel if member is not None and member.voice is not None else None
            if current is None or getattr(current, "category_id", None) != category:
                results.append(_row(user_id, member, channel_id, "not_in_voice"))
                continue
            results.append(await self._apply(member, self._voice(guild, category, channel_id), channel_id))
        if drain:
            to_channel_id = str(drain["to_channel_id"])
            target = self._voice(guild, category, to_channel_id)
            for source_id in drain.get("channel_ids") or []:
                source = self._voice(guild, category, str(source_id))
                for member in list(source.members) if source is not None else []:
                    results.append(await self._apply(member, target, to_channel_id))
        return DirectoryOutcome("success", {"results": results})

    @staticmethod
    def _voice(guild: discord.Guild, category: int, channel_id: str) -> discord.VoiceChannel | None:
        """A voice channel of the category, or ``None`` for anything else."""
        channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if isinstance(channel, discord.VoiceChannel) and channel.category_id == category:
            return channel
        return None

    @staticmethod
    async def _apply(member: discord.Member, target: discord.VoiceChannel | None, channel_id: str) -> dict[str, Any]:
        user_id = str(member.id)
        if target is None:
            return _row(user_id, member, channel_id, "channel_outside_category")
        if member.voice is not None and member.voice.channel is not None and member.voice.channel.id == target.id:
            return _row(user_id, member, channel_id, "moved")
        try:
            await member.move_to(target, reason=_REASON)
        except discord.Forbidden:
            return _row(user_id, member, channel_id, "missing_permission")
        except discord.HTTPException:
            return _row(user_id, member, channel_id, "failed")
        return _row(user_id, member, channel_id, "moved")


def _row(user_id: str, member: discord.Member | None, channel_id: str, status: str) -> dict[str, Any]:
    return {
        "discord_user_id": user_id,
        "name": member.display_name if member is not None else None,
        "channel_id": channel_id,
        "status": status,
    }
