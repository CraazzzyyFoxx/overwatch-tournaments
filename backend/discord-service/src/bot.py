"""The platform's Discord bot.

Subclasses ``commands.Bot`` (rather than a bare ``discord.Client``) for its
Cog/extension machinery. It reacts to gateway events (via Cogs), RabbitMQ
commands and RPC (via ``DiscordRabbitGateway``), and the action buttons on the
notification cards it sends (``InteractionsCog``, which also carries the
``/mix`` slash command). The command tree is never synced from here: a sync is
a deploy step, run by hand through ``python -m src.tools.sync_commands``.
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks

from src.cogs.interactions import InteractionsCog
from src.cogs.log_ingestion import LogIngestionCog
from src.cogs.membership import MembershipEventsCog
from src.core.config import Settings
from src.core.db import async_session_maker
from src.interactions.dispatcher import ActionDispatcher
from src.interactions.emoji import registry as emoji_registry
from src.rabbit.gateway import DiscordRabbitGateway
from src.result_waiter import ResultWaiter
from src.services.attachment_processor import AttachmentProcessor
from src.services.channel_registry import ChannelRegistry
from src.services.directory import DiscordDirectoryService
from src.services.parser_client import ParserClientFactory
from src.services.subscription_sync import MemberSubscriptionSyncService
from src.watchdog import GatewayWatchdog

# Seconds before giving up on a parser processing result for an uploaded log.
_PROCESSING_RESULT_TIMEOUT = 120


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.messages = True
    intents.message_content = True
    intents.reactions = True
    intents.guilds = True
    intents.members = True
    return intents


class LogCollectorBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            # No prefix commands are registered -- kept only so the Cog
            # machinery (unavailable on a bare discord.Client) works.
            command_prefix=commands.when_mentioned,
            intents=_build_intents(),
            proxy=settings.proxy_url,
        )
        self.settings = settings
        self.session_maker = async_session_maker

        self.channel_registry = ChannelRegistry(session_maker=self.session_maker)
        self.result_waiter = ResultWaiter(timeout=_PROCESSING_RESULT_TIMEOUT)
        self.attachment_processor = AttachmentProcessor(
            client=self,
            session_maker=self.session_maker,
            parser_clients=ParserClientFactory(settings),
            result_waiter=self.result_waiter,
        )
        self.directory = DiscordDirectoryService(self)
        self.subscription_sync = MemberSubscriptionSyncService(settings=settings, session_maker=self.session_maker)
        self.action_dispatcher = ActionDispatcher(site_url=settings.public_site_url, session_maker=self.session_maker)
        self.rabbit_gateway = DiscordRabbitGateway(
            settings=settings,
            processor=self.attachment_processor,
            registry=self.channel_registry,
            directory=self.directory,
            result_waiter=self.result_waiter,
            bot=self,
            session_maker=self.session_maker,
        )
        self.watchdog = GatewayWatchdog(
            self,
            heartbeat_path=settings.gateway_heartbeat_path,
            unready_timeout=settings.gateway_unready_timeout_seconds,
        )

    async def setup_hook(self) -> None:
        # Before anything can send a card: the first post must already wear the emoji.
        await emoji_registry.load(self)
        self._reload_emoji.start()
        await self.add_cog(LogIngestionCog(self))
        await self.add_cog(MembershipEventsCog(self))
        await self.add_cog(InteractionsCog(self))
        await self.rabbit_gateway.start()
        self.watchdog.start()

    @tasks.loop(minutes=10)
    async def _reload_emoji(self) -> None:
        """Pick up emoji uploaded while the bot runs (``discord-emoji`` job, ``--grids``).

        The registry is a name -> emoji map read from Discord; re-reading it is
        one REST call, cheaper than making every upload restart the bot.
        """
        await emoji_registry.load(self)

    async def close(self) -> None:
        self._reload_emoji.cancel()
        self.watchdog.stop()
        await self.rabbit_gateway.close()
        await super().close()
