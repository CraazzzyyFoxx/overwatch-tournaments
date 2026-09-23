"""Answers the action buttons on notification cards.

One listener for every button the bot ever sent, keyed by ``custom_id``
rather than by a per-message view: cards outlive restarts and deploys, and a
DM fan-out would otherwise leave a view in memory for every message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from loguru import logger

from src.interactions import copy
from src.interactions.actions import is_ours, parse_custom_id

if TYPE_CHECKING:
    from src.bot import LogCollectorBot


class InteractionsCog(commands.Cog):
    def __init__(self, bot: LogCollectorBot) -> None:
        self._dispatcher = bot.action_dispatcher

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        value = (interaction.data or {}).get("custom_id")
        if not is_ours(value):
            return
        parsed = parse_custom_id(value)
        try:
            if parsed is None:
                # Ours, but an action since retired or a mangled target: answer
                # rather than let Discord show "This interaction failed".
                locale = copy.locale_of(interaction.locale)
                await interaction.response.send_message(copy.text(locale, "expired_button"), ephemeral=True)
                return
            await self._dispatcher.handle(interaction, *parsed)
        except discord.HTTPException as exc:
            # Typically a click that reached us after Discord's 3-second window:
            # nothing ran, and the clicker can press again.
            logger.warning(f"Could not answer Discord button {value}: {exc!r}")
