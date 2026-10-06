"""Downloads Discord log-file attachments, hands them to the parser over
RabbitMQ, and reflects the outcome back onto the originating message via
reactions/replies.
"""

from __future__ import annotations

import asyncio
import base64

import discord
import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.domain.discord_ui import EMOJI
from shared.messaging.config import UPLOAD_MATCH_LOG_QUEUE
from shared.observability import publish_message
from shared.repository import LogProcessingRepository
from shared.schemas.events import UploadMatchLogEvent
from src.core.broker import optional_broker
from src.feedback import (
    AttachmentFeedbackResult,
    AttachmentFeedbackState,
    build_message_feedback,
)
from src.interactions.emoji import registry
from src.result_waiter import ResultWaiter
from src.services.parser_client import ParserClientFactory

_LOG_FILE_SUFFIXES = (".txt", ".log", ".json")

#: The three verdicts a log message can carry, as emoji names.
_FEEDBACK_STATES = ("ok", "warn", "error")

#: What the bot reacted with before any of this: ``❌`` is not the current
#: Unicode fallback for ``error`` (``⛔`` is), but it still sits on every
#: message processed by the older bot.
_LEGACY_REACTIONS = frozenset({"✅", "⚠️", "❌"})


class AttachmentProcessor:
    """Owns the log-upload pipeline and the per-message in-flight processing guard."""

    def __init__(
        self,
        *,
        client: discord.Client,
        session_maker: async_sessionmaker[AsyncSession],
        parser_clients: ParserClientFactory,
        result_waiter: ResultWaiter,
        log_records: LogProcessingRepository = LogProcessingRepository(),
    ) -> None:
        self._client = client
        self._session_maker = session_maker
        self._parser_clients = parser_clients
        self._result_waiter = result_waiter
        self._log_records = log_records
        self._processing_messages: set[int] = set()

    async def get_text_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                return None
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def _already_processed(self, tournament_id: int, filename: str) -> bool:
        async with self._session_maker() as session:
            return await self._log_records.exists_done(session, tournament_id=tournament_id, filename=filename)

    async def _get_latest_log_error(self, tournament_id: int, filename: str) -> str | None:
        async with self._session_maker() as session:
            return await self._log_records.get_latest_error_message(
                session, tournament_id=tournament_id, filename=filename
            )

    async def process_attachment(
        self,
        tournament_id: int,
        attachment: discord.Attachment,
        *,
        uploader_discord_name: str | None = None,
        wait_for_result: bool = True,
    ) -> AttachmentFeedbackResult:
        """
        Download and process a single attachment.
        If wait_for_result is True, polls until processing completes and returns
        the actual success/failure. If False, returns after queuing.
        """
        try:
            # Skip already-processed logs to avoid re-processing on restart
            if await self._already_processed(tournament_id, attachment.filename):
                logger.info(f"⏭️ Skipping {attachment.filename} - already processed")
                return AttachmentFeedbackResult(
                    filename=attachment.filename,
                    state=AttachmentFeedbackState.ALREADY_PROCESSED,
                )

            logger.info(f"📥 Downloading {attachment.filename} for tournament {tournament_id}")
            async with await self._parser_clients.create(destination="discord") as http_client:
                # Download file from Discord
                response = await http_client.get(attachment.url)
                response.raise_for_status()

            # Hand the log to parser over RabbitMQ (base64); the worker stores it to S3,
            # upserts the LogProcessingRecord, and queues processing. Replaces the former
            # direct HTTP upload (POST /logs/{id}/upload) so the bot no longer calls
            # parser over HTTP.
            broker = optional_broker()
            if broker is None:
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
                broker,
                event.model_dump(),
                UPLOAD_MATCH_LOG_QUEUE,
                logger=logger.bind(tournament_id=tournament_id, filename=attachment.filename),
            )
            logger.success(f"✅ {attachment.filename} uploaded and queued for processing")

            if wait_for_result:
                processing_result = await self._result_waiter.wait(tournament_id, attachment.filename)
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
                    error_message=await self._get_latest_log_error(tournament_id, attachment.filename),
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

    def _resolved_reaction(self, name: str) -> discord.Emoji | str:
        """The uploaded emoji for ``name``, its Unicode fallback until there is one."""
        return registry.component(name) or EMOJI[name]

    async def _apply_message_reactions(self, message: discord.Message, reactions: tuple[str, ...]) -> None:
        """Reconcile the bot's own reactions on ``message`` to exactly ``reactions`` (emoji names)."""
        wanted = [self._resolved_reaction(name) for name in reactions]
        keep = {str(item) for item in wanted}
        # Everything this message could be carrying from the bot: today's emoji
        # for each state, plus every character it reacted with before -- a
        # re-processed message still shows the Unicode ✅/⚠️/❌ of the old bot,
        # and leaving those beside the uploaded ones reads as two verdicts.
        ours = {str(self._resolved_reaction(name)) for name in _FEEDBACK_STATES}
        ours |= {EMOJI[name] for name in _FEEDBACK_STATES} | _LEGACY_REACTIONS
        stale = [
            reaction.emoji
            for reaction in message.reactions
            if reaction.me and str(reaction.emoji) in ours and str(reaction.emoji) not in keep
        ]

        async def _remove(emoji: discord.Emoji | discord.PartialEmoji | str) -> None:
            try:
                await message.remove_reaction(emoji, self._client.user)
            except discord.NotFound:
                pass

        # Independent per-emoji REST calls: run them concurrently instead of
        # paying up to three sequential round trips before the reply goes out.
        await asyncio.gather(
            *(message.add_reaction(item) for item in wanted),
            *(_remove(item) for item in stale),
        )

    @staticmethod
    async def _send_feedback_reply(message: discord.Message, reply_text: str) -> None:
        await message.reply(registry.render(reply_text), mention_author=False)

    async def process_message(
        self, message: discord.Message, tournament_id: int, *, wait_for_result: bool = True
    ) -> None:
        """
        Process a single message and its attachments.
        Adds reactions to indicate status.
        Set wait_for_result=False to fire-and-forget without waiting for processing outcome.
        """
        if message.id in self._processing_messages:
            return  # Already processing

        if not message.attachments:
            return  # No attachments to process

        self._processing_messages.add(message.id)

        try:
            results: list[AttachmentFeedbackResult] = []
            for attachment in message.attachments:
                # Only process log files
                if attachment.filename.lower().endswith(_LOG_FILE_SUFFIXES):
                    result = await self.process_attachment(
                        tournament_id,
                        attachment,
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
                    await self._apply_message_reactions(message, summary.reactions)
                except discord.Forbidden:
                    logger.warning("⚠️ Bot doesn't have permission to add reactions")
                except discord.HTTPException as e:
                    logger.warning(f"⚠️ Failed to add reaction: {e}")

            if summary.reply_text is not None:
                try:
                    await self._send_feedback_reply(message, summary.reply_text)
                except discord.Forbidden:
                    logger.warning("⚠️ Bot doesn't have permission to reply to messages")
                except discord.HTTPException as e:
                    logger.warning(f"⚠️ Failed to send reply: {e}")

        finally:
            self._processing_messages.discard(message.id)

    async def process_channel_history(self, channel_id: int, tournament_id: int, *, limit: int = 10) -> None:
        """
        Process recent message history in a channel.
        Used when the bot starts or a channel is newly added.
        """
        try:
            channel = await self.get_text_channel(channel_id)
            if not channel:
                logger.error(f"❌ Channel {channel_id} not found")
                return

            logger.info(f"🔍 Processing last {limit} messages in channel {channel_id}")

            processed = 0
            async for message in channel.history(limit=limit):
                if message.attachments:
                    await self.process_message(message, tournament_id, wait_for_result=False)
                    processed += 1

            logger.success(f"✅ Processed {processed} messages with attachments")

        except discord.Forbidden:
            logger.error(f"❌ No permission to read channel {channel_id}")
        except Exception as e:
            logger.error(f"❌ Error processing channel history: {e}")
