"""Gateway events of the tournament voice channels: the hub, drift, startup, and the deletion loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks
from loguru import logger

if TYPE_CHECKING:
    from src.bot import LogCollectorBot


class VoiceChannelsCog(commands.Cog):
    def __init__(self, bot: LogCollectorBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self._sweep.start()

    async def cog_unload(self) -> None:
        self._sweep.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Also after a reconnect: the sync is idempotent, and it is what notices what changed while the gateway was down.
        await self.bot.voice_sync.start()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        joined = after.channel
        if joined is not None and (before.channel is None or before.channel.id != joined.id):
            await self.bot.voice_sync.hub_joined(member, joined)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.voice_sync.channel_deleted(channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        self.bot.voice_sync.channel_updated(before, after)

    @tasks.loop(seconds=30)
    async def _sweep(self) -> None:
        # A loop dies on its first unhandled error; this one must outlive any single bad round.
        try:
            await self.bot.voice_sync.sweep_deleting()
        except Exception:
            logger.exception("❌ Voice channel deletion sweep failed")

    @_sweep.before_loop
    async def _before_sweep(self) -> None:
        await self.bot.wait_until_ready()
