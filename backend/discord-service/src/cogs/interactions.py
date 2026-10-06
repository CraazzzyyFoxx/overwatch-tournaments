"""Answers the action buttons on notification cards, the seat form, and ``/mix``.

One listener for every button the bot ever sent, keyed by ``custom_id``
rather than by a per-message view: cards outlive restarts and deploys, and a
DM fan-out would otherwise leave a view in memory for every message. A modal
is routed the same way -- its ``custom_id`` is the action it submits
(``owt:mix.seat_set:42``), so no ``discord.ui.Modal`` has to stay in memory
between opening the form and reading it back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from src.interactions import copy
from src.interactions.actions import is_ours, parse_custom_id
from src.interactions.cards import modal_fields

if TYPE_CHECKING:
    from src.bot import LogCollectorBot

#: Interaction types this cog answers: a component click, and the submit of a
#: form one of those clicks opened.
_ROUTED = (discord.InteractionType.component, discord.InteractionType.modal_submit)


class InteractionsCog(commands.Cog):
    def __init__(self, bot: LogCollectorBot) -> None:
        self._dispatcher = bot.action_dispatcher

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type not in _ROUTED:
            return
        data = interaction.data or {}
        value = data.get("custom_id")
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
            # A form submit sends what was filled in; a button sends nothing.
            fields = modal_fields(data) if interaction.type is discord.InteractionType.modal_submit else {}
            await self._dispatcher.handle(interaction, *parsed, fields)
        except discord.HTTPException as exc:
            # Typically a click that reached us after Discord's 3-second window:
            # nothing ran, and the clicker can press again.
            logger.warning(f"Could not answer Discord interaction {value}: {exc!r}")

    @app_commands.command(name="mix", description="Моё место в текущем миксе")
    @app_commands.guild_only()
    async def mix(self, interaction: discord.Interaction) -> None:
        """The seat panel without a card to click it from -- same reply, same buttons."""
        await self._dispatcher.show_current_mix(interaction)
