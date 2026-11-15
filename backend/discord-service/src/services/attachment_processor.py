"""Downloads Discord log-file attachments, hands them to stats-service over
RabbitMQ, and reflects the outcome back onto the originating message via
reactions/replies: the hand-off at once, stats's per-file verdict whenever its
``match_log_result`` names this message (:meth:`AttachmentProcessor.apply_result`).
"""

from __future__ import annotations

import asyncio
import base64

import discord
import httpx
from loguru import logger

from shared.messaging.config import UPLOAD_MATCH_LOG_QUEUE
from shared.observability import publish_message
from shared.schemas.events import MatchLogProcessedEvent, UploadMatchLogEvent
from src.core.broker import optional_broker
from src.feedback import (
    AttachmentFeedbackResult,
    AttachmentFeedbackState,
    build_message_feedback,
    upload_reactions,
)
from src.interactions import copy
from src.interactions.emoji import registry
from src.services.attachment_client import AttachmentClientFactory
from src.services.channel_registry import ChannelRegistry
from src.ui import EMOJI

_LOG_FILE_SUFFIXES = (".txt", ".log", ".json")

#: The three verdicts a log message can carry, as emoji names.
_FEEDBACK_STATES = ("ok", "warn", "error")

#: Unicode reactions still sitting on messages processed before the application
#: emoji existed: ``❌`` is not the current fallback for ``error`` (``⛔`` is).
_LEGACY_REACTIONS = frozenset({"✅", "⚠️", "❌"})


class AttachmentProcessor:
    """Owns the log-upload pipeline and the per-message in-flight processing guard."""

    def __init__(
        self, *, client: discord.Client, attachment_clients: AttachmentClientFactory, registry: ChannelRegistry
    ) -> None:
        self._client = client
        self._attachment_clients = attachment_clients
        self._registry = registry
        self._processing_messages: set[int] = set()

    async def get_text_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound, discord.Forbidden:
                return None
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def process_attachment(
        self, tournament_id: int, message: discord.Message, attachment: discord.Attachment
    ) -> AttachmentFeedbackResult:
        """Download one attachment and hand it to stats-service; ``UPLOADED_QUEUED`` once it is out.

        The event names ``message``, and stats echoes that back on its result, so
        whichever replica consumes the verdict knows where to put it.
        """
        try:
            logger.info(f"📥 Downloading {attachment.filename} for tournament {tournament_id}")
            async with self._attachment_clients.create() as http_client:
                response = await http_client.get(attachment.url)
                response.raise_for_status()

            # Hash identity is decided from the downloaded bytes by stats-service;
            # a display filename is never proof that an upload was processed.
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
                uploader_discord_name=message.author.name,
                channel_id=message.channel.id,
                message_id=message.id,
            )
            event.correlation_id = event.event_id
            await publish_message(
                broker,
                event.model_dump(),
                UPLOAD_MATCH_LOG_QUEUE,
                logger=logger.bind(tournament_id=tournament_id, filename=attachment.filename),
                correlation_id=event.event_id,
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
        # for each state plus ``_LEGACY_REACTIONS`` -- leaving those beside the
        # uploaded ones reads as two verdicts.
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

    async def apply_result(self, message: discord.Message, event: MatchLogProcessedEvent) -> None:
        """Put stats-service's verdict for one file on the message it came from.

        Only ever adds: a message carrying several logs gets one verdict per
        file, in any order, and a later success must not take back an earlier
        file's ``warn``. Adding a reaction the bot already has changes nothing.
        """
        if event.status == "done":
            state = AttachmentFeedbackState.PROCESSED_OK
        elif event.status == "awaiting_link":
            state = AttachmentFeedbackState.AWAITING_LINK
        elif event.ingest_job_id is None:
            state = AttachmentFeedbackState.UPLOAD_FAILED
        else:
            state = AttachmentFeedbackState.PROCESSED_FAILED
        # A channel message carries no reader locale: the guild's is the best guess.
        locale = copy.locale_of(message.guild.preferred_locale) if message.guild else "ru"
        summary = build_message_feedback(
            AttachmentFeedbackResult(filename=event.filename, state=state, error_message=event.error_message), locale
        )

        try:
            await asyncio.gather(*(message.add_reaction(self._resolved_reaction(name)) for name in summary.reactions))
        except discord.HTTPException as e:
            logger.warning(f"⚠️ Failed to react on message {message.id}: {e}")

        if summary.reply_text is not None:
            try:
                await self._send_feedback_reply(message, summary.reply_text)
            except discord.HTTPException as e:
                logger.warning(f"⚠️ Failed to reply on message {message.id}: {e}")

    async def process_message(self, message: discord.Message, tournament_id: int) -> None:
        """Hand every log file on ``message`` to stats-service and mark the hand-off.

        Returns once the files are published; nothing waits for stats. Its
        per-file verdict arrives later on ``match_log_result`` (:meth:`apply_result`).
        """
        if message.id in self._processing_messages:
            return  # Already processing

        if not message.attachments:
            return  # No attachments to process

        self._processing_messages.add(message.id)

        try:
            results: list[AttachmentFeedbackResult] = []
            for attachment in message.attachments:
                if attachment.filename.lower().endswith(_LOG_FILE_SUFFIXES):
                    results.append(await self.process_attachment(tournament_id, message, attachment))
                else:
                    logger.info(f"⏭️ Skipping non-log file: {attachment.filename}")

            if not results:
                return

            # ponytail: a verdict that lands before this reconcile (a pre-job failure
            # while later files still download) loses its ``warn`` here; its reply
            # stays. Reconcile before publishing if that ever shows up in practice.
            try:
                await self._apply_message_reactions(message, upload_reactions(results))
            except discord.Forbidden:
                logger.warning("⚠️ Bot doesn't have permission to add reactions")
            except discord.HTTPException as e:
                logger.warning(f"⚠️ Failed to add reaction: {e}")

        finally:
            self._processing_messages.discard(message.id)

    async def process_channel_history(
        self, channel_id: int, tournament_id: int, *, after_message_id: int | None = None, limit: int = 500
    ) -> None:
        """Hand a channel's log messages to stats-service, then move its rescan cursor.

        With ``after_message_id`` (the registry's cursor) only what came after it
        is read, oldest first; without one, the last ``limit`` messages. The
        newest message seen becomes the cursor either way, so a reconnect walks
        what it missed instead of re-downloading the same attachments.
        """
        try:
            channel = await self.get_text_channel(channel_id)
            if not channel:
                logger.error(f"❌ Channel {channel_id} not found")
                return

            after = discord.Object(id=after_message_id) if after_message_id is not None else None
            logger.info(f"🔍 Processing up to {limit} messages in channel {channel_id} after {after_message_id}")

            processed = 0
            newest: int | None = None
            async for message in channel.history(limit=limit, after=after):
                newest = max(newest or 0, message.id)
                if message.attachments:
                    await self.process_message(message, tournament_id)
                    processed += 1

            if newest is not None:
                await self._registry.advance(channel_id, newest)
            logger.success(f"✅ Processed {processed} messages with attachments")

        except discord.Forbidden:
            logger.error(f"❌ No permission to read channel {channel_id}")
        except Exception as e:
            logger.error(f"❌ Error processing channel history: {e}")
