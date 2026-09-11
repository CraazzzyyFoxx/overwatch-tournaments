"""Wires the bot's Discord-facing services onto RabbitMQ: match-log uploads,
Discord-triggered commands, and read-only guild/member RPC lookups consumed by
other services.
"""

from __future__ import annotations

import base64
import binascii
import io
from typing import Any

import discord
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger
from pydantic import ValidationError

from shared.messaging.config import (
    DISCORD_COMMANDS_QUEUE,
    DISCORD_GUILD_CHANNELS_QUEUE,
    DISCORD_GUILD_INFO_QUEUE,
    DISCORD_GUILD_ROLES_QUEUE,
    DISCORD_MEMBER_ROLES_QUEUE,
    MATCH_LOG_RESULT_EXCHANGE,
)
from shared.observability import make_rabbit_broker, observe_message_processing
from shared.schemas.events import DiscordCommandEvent, MatchLogProcessedEvent
from shared.schemas.rpc import rpc_error, rpc_ok
from src.core.broker import set_worker_broker
from src.core.config import Settings
from src.result_waiter import ResultWaiter
from src.services.attachment_processor import AttachmentProcessor
from src.services.channel_registry import ChannelRegistry
from src.services.directory import DirectoryOutcome, DiscordDirectoryService

_DIRECTORY_CODES = {
    "guild_not_found": "not_found",
    "invalid": "bad_request",
    "error": "internal",
}


def _directory_reply(outcome: DirectoryOutcome) -> dict[str, Any]:
    if outcome.status == "success":
        return rpc_ok(outcome.payload)
    code = _DIRECTORY_CODES.get(outcome.status, "internal")
    message = str(outcome.payload.get("error") or outcome.status)
    return rpc_error(code, message)


def _attachment(event: DiscordCommandEvent) -> discord.File | None:
    """The event's PNG as an upload, ``None`` when it carries no image.

    Raises ``ValueError`` on base64 the publisher mangled -- a malformed
    payload is not worth a requeue, so the caller rejects it.
    """
    if event.image_b64 is None:
        return None
    try:
        raw = base64.b64decode(event.image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_b64 is not valid base64") from exc
    return discord.File(io.BytesIO(raw), filename=event.image_filename)


class DiscordRabbitGateway:
    """Owns the broker's lifecycle and every RabbitMQ subscriber this service exposes."""

    def __init__(
        self,
        *,
        settings: Settings,
        processor: AttachmentProcessor,
        registry: ChannelRegistry,
        directory: DiscordDirectoryService,
        result_waiter: ResultWaiter,
        bot: discord.Client,
    ) -> None:
        self._settings = settings
        self._processor = processor
        self._registry = registry
        self._directory = directory
        self._result_waiter = result_waiter
        self._bot = bot
        self._broker: RabbitBroker | None = None

    async def start(self) -> None:
        if not self._settings.broker_url:
            logger.info("ℹ️ RABBITMQ_URL not set; RabbitMQ listener disabled")
            return

        broker = make_rabbit_broker(self._settings.broker_url, logger=logger)
        self._register(broker)
        await broker.start()
        # Publish to the global only once the broker is actually started: gateway
        # member events fire as soon as discord.py connects and reach
        # MemberSubscriptionSyncService, which resolves subscriptions through
        # this broker. A half-initialised global there means an RPC against a
        # broker with no connection.
        set_worker_broker(broker)
        self._broker = broker
        logger.success(f"✅ RabbitMQ listener started (queue='{DISCORD_COMMANDS_QUEUE}')")

    async def close(self) -> None:
        if self._broker is None:
            return
        try:
            await self._broker.close()
        finally:
            self._broker = None
            set_worker_broker(None)

    def _register(self, broker: RabbitBroker) -> None:
        @broker.subscriber(DISCORD_COMMANDS_QUEUE)
        async def handle_discord_command(body: dict[str, Any], msg: RabbitMessage) -> None:
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=DISCORD_COMMANDS_QUEUE,
                handler="handle_discord_command",
                message=msg,
                logger=logger,
            ) as observation:
                try:
                    event = DiscordCommandEvent.model_validate(body)
                except ValidationError as e:
                    observation.set_status("invalid")
                    logger.error(f"❌ Invalid discord command payload: {e}")
                    await msg.reject()  # Send to DLQ
                    return

                try:
                    if event.action == "process_all":
                        channel_ids = await self._registry.list_channel_ids_for_tournament(event.tournament_id)
                        if not channel_ids:
                            observation.set_status("no_channels")
                            logger.warning(f"⚠️ No active Discord channels found for tournament {event.tournament_id}")
                            await msg.ack()
                            return

                        logger.info(
                            f"📩 RabbitMQ command: process_all for tournament {event.tournament_id} "
                            f"({len(channel_ids)} channel(s))"
                        )
                        for channel_id in channel_ids:
                            await self._processor.process_channel_history(channel_id, event.tournament_id, limit=500)

                        await msg.ack()
                        return

                    if event.action == "post_message":
                        channel = await self._processor.get_text_channel(event.channel_id)
                        if channel is None:
                            observation.set_status("not_found")
                            logger.error(f"❌ Channel {event.channel_id} not found for post_message")
                            await msg.reject()
                            return

                        logger.info(f"📩 RabbitMQ command: post_message channel={event.channel_id}")
                        try:
                            attachment = _attachment(event)
                        except ValueError as exc:
                            observation.set_status("invalid")
                            logger.error(f"❌ Undecodable image for channel {event.channel_id}: {exc}")
                            await msg.reject()
                            return

                        try:
                            await channel.send(
                                content=event.content,
                                embed=discord.Embed.from_dict(event.embed) if event.embed else None,
                                file=attachment,
                            )
                        except discord.Forbidden:
                            observation.set_status("forbidden")
                            logger.error(f"❌ No permission to post in channel {event.channel_id}")
                            await msg.reject()
                            return

                        await msg.ack()
                        return

                    if event.channel_id is None or event.message_id is None:
                        observation.set_status("invalid")
                        logger.error("❌ channel_id and message_id required for process_message action")
                        await msg.reject()
                        return

                    channel = await self._processor.get_text_channel(event.channel_id)
                    if channel is None:
                        observation.set_status("not_found")
                        logger.error(f"❌ Channel {event.channel_id} not found for message fetch")
                        await msg.reject()
                        return

                    try:
                        fetched_message = await channel.fetch_message(event.message_id)
                    except discord.NotFound:
                        observation.set_status("not_found")
                        logger.warning(f"⚠️ Message {event.message_id} not found in channel {event.channel_id}")
                        await msg.reject()
                        return
                    except discord.Forbidden:
                        observation.set_status("forbidden")
                        logger.error(
                            f"❌ No permission to fetch message {event.message_id} in channel {event.channel_id}"
                        )
                        await msg.reject()
                        return

                    logger.info(
                        f"📩 RabbitMQ command: process_message channel={event.channel_id} "
                        f"message={event.message_id} tournament={event.tournament_id}"
                    )
                    await self._processor.process_message(fetched_message, event.tournament_id)
                    await msg.ack()

                except Exception as e:
                    logger.error(f"❌ Error handling discord command: {e}")
                    await msg.nack()  # Requeue for retry
                    raise

        @broker.subscriber(DISCORD_MEMBER_ROLES_QUEUE)
        async def handle_get_member_roles(body: dict[str, Any], msg: RabbitMessage) -> dict[str, Any]:
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=DISCORD_MEMBER_ROLES_QUEUE,
                handler="handle_get_member_roles",
                message=msg,
                logger=logger,
            ) as observation:
                guild_id = str(body.get("guild_id") or "").strip()
                user_ids = [str(u) for u in (body.get("user_ids") or []) if u]
                outcome = await self._directory.get_member_roles(guild_id, user_ids)
                observation.set_status(outcome.status)
                return _directory_reply(outcome)

        @broker.subscriber(DISCORD_GUILD_ROLES_QUEUE)
        async def handle_get_guild_roles(body: dict[str, Any], msg: RabbitMessage) -> dict[str, Any]:
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=DISCORD_GUILD_ROLES_QUEUE,
                handler="handle_get_guild_roles",
                message=msg,
                logger=logger,
            ) as observation:
                guild_id = str(body.get("guild_id") or "").strip()
                outcome = await self._directory.get_guild_roles(guild_id)
                observation.set_status(outcome.status)
                return _directory_reply(outcome)

        @broker.subscriber(DISCORD_GUILD_CHANNELS_QUEUE)
        async def handle_get_guild_channels(body: dict[str, Any], msg: RabbitMessage) -> dict[str, Any]:
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=DISCORD_GUILD_CHANNELS_QUEUE,
                handler="handle_get_guild_channels",
                message=msg,
                logger=logger,
            ) as observation:
                guild_id = str(body.get("guild_id") or "").strip()
                outcome = await self._directory.get_guild_channels(guild_id)
                observation.set_status(outcome.status)
                return _directory_reply(outcome)

        @broker.subscriber(DISCORD_GUILD_INFO_QUEUE)
        async def handle_get_guild_info(body: dict[str, Any], msg: RabbitMessage) -> dict[str, Any]:
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=DISCORD_GUILD_INFO_QUEUE,
                handler="handle_get_guild_info",
                message=msg,
                logger=logger,
            ) as observation:
                guild_id = str(body.get("guild_id") or "").strip()
                outcome = await self._directory.get_guild_info(guild_id)
                observation.set_status(outcome.status)
                return _directory_reply(outcome)

        # Per-instance, server-named exclusive queue bound to the fanout exchange so
        # every replica receives every result; the one holding the matching pending
        # future resolves it, the rest no-op. Replaces pg LISTEN/NOTIFY.
        result_queue = RabbitQueue("", exclusive=True, auto_delete=True)

        @broker.subscriber(result_queue, MATCH_LOG_RESULT_EXCHANGE)
        async def handle_match_log_result(body: dict[str, Any], msg: RabbitMessage) -> None:
            try:
                event = MatchLogProcessedEvent.model_validate(body)
            except ValidationError as e:
                logger.error(f"❌ Invalid match_log_processed payload: {e}")
                return
            self._result_waiter.resolve(event.tournament_id, event.filename, event.status == "done")
