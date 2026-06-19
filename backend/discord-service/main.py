import asyncio
import base64
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
import httpx
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from shared.messaging.config import (
    DISCORD_COMMANDS_QUEUE,
    MATCH_LOG_RESULT_EXCHANGE,
    UPLOAD_MATCH_LOG_QUEUE,
)
from shared.models import Tournament, TournamentDiscordChannel
from shared.models.log_processing import LogProcessingRecord, LogProcessingStatus
from shared.observability import (
    observe_message_processing,
    publish_message,
    setup_logging,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.schemas.events import DiscordCommandEvent, MatchLogProcessedEvent, UploadMatchLogEvent
from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session_maker
from src.feedback import (
    AttachmentFeedbackResult,
    AttachmentFeedbackState,
    build_message_feedback,
)
from src.result_waiter import ResultWaiter

# Setup structured logging (replaces old src.core.logging)
logger = setup_logging(
    service_name="discord-service",
    log_level=settings.log_level,
    logs_root_path=settings.logs_root_path,
    json_output=settings.json_logging,
)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.guilds = True

PROXY_CONF = settings.proxy_url

client = discord.Client(intents=intents, proxy=PROXY_CONF)

rabbit_broker: RabbitBroker | None = None

# Cache for active tournaments and their channels
active_channels: dict[int, int] = {}  # channel_id -> tournament_id
processing_messages: set[int] = set()  # message IDs being processed

_service_token: str | None = None
_service_token_expires_at: float = 0.0
_service_token_lock = asyncio.Lock()


async def get_service_token() -> str:
    """Get cached service token for internal calls."""
    global _service_token, _service_token_expires_at

    now = time.time()
    if _service_token and now < (_service_token_expires_at - settings.service_token_skew_seconds):
        return _service_token

    async with _service_token_lock:
        now = time.time()
        if _service_token and now < (_service_token_expires_at - settings.service_token_skew_seconds):
            return _service_token

        async with httpx.AsyncClient(
            base_url=settings.auth_service_url,
            timeout=httpx.Timeout(5.0),
        ) as client:
            res = await client.post(
                "/service/token",
                json={
                    "client_id": settings.service_client_id,
                    "client_secret": settings.service_client_secret,
                },
            )

        if res.status_code != 200:
            logger.error(f"Failed to obtain service token (status={res.status_code})")
            raise RuntimeError("Failed to obtain service token")

        data = res.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 300))
        if not token:
            raise RuntimeError("Invalid service token response")

        _service_token = token
        _service_token_expires_at = time.time() + expires_in
        return token


async def get_httpx_client(destination: str = "internal") -> httpx.AsyncClient:
    """Create HTTP client for parser service"""
    headers: dict[str, str] = {}
    if destination == "internal":
        headers["Authorization"] = f"Bearer {await get_service_token()}"

    return httpx.AsyncClient(
        base_url=settings.parser_url,
        headers=headers,
        proxy=PROXY_CONF if destination != "internal" else None,
        timeout=httpx.Timeout(30, read=60),
    )


async def get_tournament_discord_channels(tournament_id: int) -> list[int]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(TournamentDiscordChannel.channel_id).where(
                TournamentDiscordChannel.tournament_id == tournament_id,
                TournamentDiscordChannel.is_active,
            )
        )
        return list(result.scalars().all())


async def get_text_channel(channel_id: int):
    channel = client.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await client.fetch_channel(channel_id)
    except discord.NotFound:
        return None
    except discord.Forbidden:
        return None


async def load_active_channels():
    """Load active tournament channels from database"""
    global active_channels

    async with async_session_maker() as session:
        # Get tournaments that are not finished or finished less than 1 day ago
        one_day_ago = datetime.now(UTC) - timedelta(days=1)

        result = await session.execute(
            select(TournamentDiscordChannel, Tournament)
            .join(Tournament, TournamentDiscordChannel.tournament_id == Tournament.id)
            .where(
                TournamentDiscordChannel.is_active,
                (
                    (~Tournament.is_finished)
                    | (
                        Tournament.is_finished
                        & (Tournament.end_date.is_not(None))
                        & (Tournament.end_date >= one_day_ago)
                    )
                ),
            )
        )

        new_channels = {}
        for discord_channel, tournament in result:
            new_channels[discord_channel.channel_id] = tournament.id
            logger.info(
                f"📌 Monitoring channel {discord_channel.channel_id} "
                f"for tournament #{tournament.number} - {tournament.name}"
            )

        active_channels = new_channels
        logger.success(f"✅ Loaded {len(active_channels)} active channels")


_PROCESSING_RESULT_TIMEOUT = 120  # seconds before giving up

# Tracks in-flight uploads waiting for their parser processing result. Results
# arrive over RabbitMQ (see handle_match_log_result in register_rabbit_handlers)
# instead of pg LISTEN/NOTIFY, which pgBouncer transaction pooling silently breaks.
result_waiter = ResultWaiter(timeout=_PROCESSING_RESULT_TIMEOUT)


async def _get_latest_log_error(tournament_id: int, filename: str) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(LogProcessingRecord.error_message)
            .where(
                LogProcessingRecord.tournament_id == tournament_id,
                LogProcessingRecord.filename == filename,
            )
            .order_by(LogProcessingRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def process_attachment(
    tournament_id: int,
    attachment: discord.Attachment,
    uploader_discord_name: str | None = None,
    wait_for_result: bool = True,
) -> AttachmentFeedbackResult:
    """
    Download and process a single attachment.
    If wait_for_result is True, polls the DB until processing completes and
     returns the actual success/failure. If False, returns True after queuing.
    """
    try:
        # Skip already-processed logs to avoid re-processing on restart
        async with async_session_maker() as session:
            result = await session.execute(
                select(LogProcessingRecord)
                .where(
                    LogProcessingRecord.tournament_id == tournament_id,
                    LogProcessingRecord.filename == attachment.filename,
                    LogProcessingRecord.status == LogProcessingStatus.done,
                )
                .limit(1)
            )
            if result.scalar_one_or_none() is not None:
                logger.info(f"⏭️ Skipping {attachment.filename} - already processed")
                return AttachmentFeedbackResult(
                    filename=attachment.filename,
                    state=AttachmentFeedbackState.ALREADY_PROCESSED,
                )

        logger.info(f"📥 Downloading {attachment.filename} for tournament {tournament_id}")
        async with await get_httpx_client(destination="discord") as http_client:
            # Download file from Discord
            response = await http_client.get(attachment.url)
            response.raise_for_status()

        # Hand the log to parser over RabbitMQ (base64); the worker stores it to S3,
        # upserts the LogProcessingRecord, and queues processing. Replaces the former
        # direct HTTP upload (POST /logs/{id}/upload) so the bot no longer calls
        # parser over HTTP.
        if rabbit_broker is None:
            logger.warning(f"⚠️ RabbitMQ not available, cannot upload {attachment.filename}")
            return AttachmentFeedbackResult(
                filename=attachment.filename,
                state=AttachmentFeedbackState.UPLOAD_FAILED,
                error_message="RabbitMQ unavailable",
            )

        event = UploadMatchLogEvent(
            tournament_id=tournament_id,
            filename=attachment.filename,
            content_b64=base64.b64encode(response.content).decode("ascii"),
            content_type=attachment.content_type,
            uploader_discord_name=uploader_discord_name,
        )
        await publish_message(
            rabbit_broker,
            event.model_dump(),
            UPLOAD_MATCH_LOG_QUEUE,
            logger=logger.bind(tournament_id=tournament_id, filename=attachment.filename),
        )
        logger.success(f"✅ {attachment.filename} uploaded and queued for processing")

        if wait_for_result:
            processing_result = await result_waiter.wait(tournament_id, attachment.filename)
            if processing_result is True:
                return AttachmentFeedbackResult(
                    filename=attachment.filename,
                    state=AttachmentFeedbackState.PROCESSED_OK,
                )
            if processing_result is None:
                logger.warning(f"⏱️ Timed out waiting for processing result of {attachment.filename}")
                return AttachmentFeedbackResult(
                    filename=attachment.filename,
                    state=AttachmentFeedbackState.TIMED_OUT,
                )

            return AttachmentFeedbackResult(
                filename=attachment.filename,
                state=AttachmentFeedbackState.PROCESSED_FAILED,
                error_message=await _get_latest_log_error(tournament_id, attachment.filename),
            )

        return AttachmentFeedbackResult(
            filename=attachment.filename,
            state=AttachmentFeedbackState.UPLOADED_QUEUED,
        )

    except httpx.HTTPError as e:
        logger.error(f"❌ HTTP error processing {attachment.filename}: {e}")
        return AttachmentFeedbackResult(
            filename=attachment.filename,
            state=AttachmentFeedbackState.UPLOAD_FAILED,
            error_message=str(e),
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error processing {attachment.filename}: {e}")
        return AttachmentFeedbackResult(
            filename=attachment.filename,
            state=AttachmentFeedbackState.UPLOAD_FAILED,
            error_message=str(e),
        )


async def _apply_message_reactions(message: discord.Message, reactions: tuple[str, ...]) -> None:
    target_reactions = set(reactions)
    for emoji in ("✅", "⚠️", "❌"):
        if emoji in target_reactions:
            await message.add_reaction(emoji)
            continue
        try:
            await message.remove_reaction(emoji, client.user)
        except discord.NotFound:
            pass


async def _send_feedback_reply(message: discord.Message, reply_text: str) -> None:
    await message.reply(reply_text, mention_author=False)


async def process_message(message: discord.Message, tournament_id: int, wait_for_result: bool = True) -> None:
    """
    Process a single message and its attachments.
    Adds reactions to indicate status.
    Set wait_for_result=False to fire-and-forget without waiting for processing outcome.
    """
    if message.id in processing_messages:
        return  # Already processing

    if not message.attachments:
        return  # No attachments to process

    processing_messages.add(message.id)

    try:
        results: list[AttachmentFeedbackResult] = []
        for attachment in message.attachments:
            # Only process log files
            if attachment.filename.lower().endswith((".txt", ".log", ".json")):
                result = await process_attachment(
                    tournament_id, attachment,
                    uploader_discord_name=message.author.name,
                    wait_for_result=wait_for_result,
                )
                results.append(result)
            else:
                logger.info(f"⏭️ Skipping non-log file: {attachment.filename}")

        if not results:
            return

        # Update reactions based on results
        summary = build_message_feedback(results, wait_for_result=wait_for_result)
        if summary.reactions is not None:
            try:
                await _apply_message_reactions(message, summary.reactions)
            except discord.Forbidden:
                logger.warning("⚠️ Bot doesn't have permission to add reactions")
            except discord.HTTPException as e:
                logger.warning(f"⚠️ Failed to add reaction: {e}")

        if summary.reply_text is not None:
            try:
                await _send_feedback_reply(message, summary.reply_text)
            except discord.Forbidden:
                logger.warning("⚠️ Bot doesn't have permission to reply to messages")
            except discord.HTTPException as e:
                logger.warning(f"⚠️ Failed to send reply: {e}")

    finally:
        processing_messages.discard(message.id)


async def process_channel_history(channel_id: int, tournament_id: int, limit: int = 10):
    """
    Process recent message history in a channel
    Used when bot starts or channel is newly added
    """
    try:
        channel = await get_text_channel(channel_id)
        if not channel:
            logger.error(f"❌ Channel {channel_id} not found")
            return

        logger.info(f"🔍 Processing last {limit} messages in channel {channel_id}")

        processed = 0
        async for message in channel.history(limit=limit):
            if message.attachments:
                await process_message(message, tournament_id, wait_for_result=False)
                processed += 1

        logger.success(f"✅ Processed {processed} messages with attachments")

    except discord.Forbidden:
        logger.error(f"❌ No permission to read channel {channel_id}")
    except Exception as e:
        logger.error(f"❌ Error processing channel history: {e}")


def register_rabbit_handlers(broker: RabbitBroker) -> None:
    @broker.subscriber(DISCORD_COMMANDS_QUEUE)
    async def handle_discord_command(body: dict[str, Any], msg: RabbitMessage):
        await client.wait_until_ready()
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
                    channel_ids = await get_tournament_discord_channels(event.tournament_id)
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
                        await process_channel_history(channel_id, event.tournament_id, limit=500)

                    await msg.ack()
                    return

                if event.channel_id is None or event.message_id is None:
                    observation.set_status("invalid")
                    logger.error("❌ channel_id and message_id required for process_message action")
                    await msg.reject()
                    return

                channel = await get_text_channel(event.channel_id)
                if channel is None:
                    observation.set_status("not_found")
                    logger.error(f"❌ Channel {event.channel_id} not found for message fetch")
                    await msg.reject()
                    return

                try:
                    fetched_message = await channel.fetch_message(event.message_id)  # type: ignore[attr-defined]
                except discord.NotFound:
                    observation.set_status("not_found")
                    logger.warning(f"⚠️ Message {event.message_id} not found in channel {event.channel_id}")
                    await msg.reject()
                    return
                except discord.Forbidden:
                    observation.set_status("forbidden")
                    logger.error(f"❌ No permission to fetch message {event.message_id} in channel {event.channel_id}")
                    await msg.reject()
                    return

                logger.info(
                    f"📩 RabbitMQ command: process_message channel={event.channel_id} message={event.message_id} "
                    f"tournament={event.tournament_id}"
                )
                await process_message(fetched_message, event.tournament_id)
                await msg.ack()

            except Exception as e:
                logger.error(f"❌ Error handling discord command: {e}")
                await msg.nack()  # Requeue for retry
                raise

    # Per-instance, server-named exclusive queue bound to the fanout exchange so
    # every replica receives every result; the one holding the matching pending
    # future resolves it, the rest no-op. Replaces pg LISTEN/NOTIFY.
    result_queue = RabbitQueue("", exclusive=True, auto_delete=True)

    @broker.subscriber(result_queue, MATCH_LOG_RESULT_EXCHANGE)
    async def handle_match_log_result(body: dict[str, Any], msg: RabbitMessage):
        try:
            event = MatchLogProcessedEvent.model_validate(body)
        except ValidationError as e:
            logger.error(f"❌ Invalid match_log_processed payload: {e}")
            return
        result_waiter.resolve(event.tournament_id, event.filename, event.status == "done")


async def start_rabbitmq_listener() -> None:
    global rabbit_broker
    if not settings.broker_url:
        logger.info("ℹ️ RABBITMQ_URL not set; RabbitMQ listener disabled")
        return

    rabbit_broker = RabbitBroker(settings.broker_url, logger=logger)
    register_rabbit_handlers(rabbit_broker)
    await rabbit_broker.start()
    logger.success(f"✅ RabbitMQ listener started (queue='{DISCORD_COMMANDS_QUEUE}')")


async def stop_rabbitmq_listener() -> None:
    global rabbit_broker
    if rabbit_broker is None:
        return
    try:
        await rabbit_broker.close()
    finally:
        rabbit_broker = None


async def channel_monitor_task():
    """
    Background task to periodically reload active channels
    Runs every 5 minutes
    """
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            await load_active_channels()
        except Exception as e:
            logger.error(f"❌ Error reloading channels: {e}")

        await asyncio.sleep(300)  # 5 minutes


@client.event
async def on_ready():
    """Bot is ready and connected"""
    logger.success(f"✅ Bot started as {client.user}")
    logger.info(f"📡 Connected to {len(client.guilds)} guilds")

    # Load active channels
    await load_active_channels()

    # Process recent history for all active channels
    for channel_id, tournament_id in active_channels.items():
        await process_channel_history(channel_id, tournament_id, limit=500)

    # Start background monitor task
    client.loop.create_task(channel_monitor_task())


@client.event
async def on_message(message: discord.Message):
    """Handle new messages in monitored channels"""
    # Ignore bot's own messages
    if message.author == client.user:
        return

    # Check if this channel is being monitored
    tournament_id = active_channels.get(message.channel.id)
    if not tournament_id:
        return

    # Process message attachments
    if message.attachments:
        logger.info(
            f"📨 New message in monitored channel from {message.author.name} "
            f"with {len(message.attachments)} attachment(s)"
        )
        await process_message(message, tournament_id)


@client.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """Handle message edits (in case attachments were added)"""
    # Check if this channel is being monitored
    tournament_id = active_channels.get(after.channel.id)
    if not tournament_id:
        return

    # Check if attachments were added
    if len(after.attachments) > len(before.attachments):
        logger.info("📝 Message edited with new attachments")
        await process_message(after, tournament_id)


@client.event
async def on_guild_join(guild: discord.Guild):
    """Bot joined a new guild"""
    logger.info(f"🎉 Joined new guild: {guild.name} (ID: {guild.id})")


@client.event
async def on_guild_remove(guild: discord.Guild):
    """Bot removed from guild"""
    logger.warning(f"👋 Removed from guild: {guild.name} (ID: {guild.id})")


async def main():
    """Main entry point"""
    try:
        logger.info("🚀 Starting Discord Log Collection Bot...")
        setup_tracing(
            service_name="discord-service",
            otlp_endpoint=settings.otlp_endpoint,
            enabled=settings.tracing_enabled,
            sampler_name=settings.otel_traces_sampler,
            sampler_arg=settings.otel_traces_sampler_arg,
        )
        start_worker_metrics_server(settings.worker_metrics_port)
        await start_rabbitmq_listener()
        await client.start(settings.discord_token)
    except KeyboardInterrupt:
        logger.info("⏸️ Shutting down bot...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        await stop_rabbitmq_listener()
        await client.close()
        logger.info("👋 Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
