"""Wires the bot's Discord-facing services onto RabbitMQ: match-log uploads,
Discord-triggered commands, and read-only guild/member RPC lookups consumed by
other services.

Every command that sends, edits or deletes a message the platform owns names a
``discord_message`` row (``message_ref``); the bot is the only process that
hears Discord answer, so it reads that row to decide what to do and writes back
what happened. The row -- not the command -- is what makes a redelivery
harmless and what a later edit or delete is resolved from.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
from collections.abc import Awaitable
from typing import Any

import discord
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.messaging.config import (
    DISCORD_COMMANDS_QUEUE,
    DISCORD_GUILD_CHANNELS_QUEUE,
    DISCORD_GUILD_INFO_QUEUE,
    DISCORD_GUILD_ROLES_QUEUE,
    DISCORD_MEMBER_ROLES_QUEUE,
    DISCORD_VOICE_MOVE_QUEUE,
    MATCH_LOG_RESULT_EXCHANGE,
)
from shared.observability import make_rabbit_broker, observe_message_processing
from shared.repository.discord_message import DiscordMessageRepository
from shared.schemas.events import DiscordCard, DiscordCommandEvent, MatchLogProcessedEvent
from shared.schemas.rpc import rpc_error, rpc_ok
from shared.services.discord_messages import emit_changed
from src.core.broker import set_worker_broker
from src.core.config import Settings
from src.interactions.cards import card_view
from src.result_waiter import ResultWaiter
from src.services.attachment_processor import AttachmentProcessor
from src.services.channel_registry import ChannelRegistry
from src.services.directory import DirectoryOutcome, DiscordDirectoryService
from src.services.voice import VoiceMover

_DIRECTORY_CODES = {
    "guild_not_found": "not_found",
    "invalid": "bad_request",
    "error": "internal",
}

#: How long an edit of one message waits for a newer one to replace it. The
#: live signup post is re-rendered on every join/leave click, so a burst of
#: clicks becomes one Discord call instead of one per click -- and the card
#: that lands is the one its row holds at flush time, never a stale render.
EDIT_COALESCE_SECONDS = 2.0

#: How many of those windows an edit waits out while its message is still
#: ``pending``: the post it edits is a command of its own, and an edit
#: published right behind it can reach the bot first. After that the edit is
#: dropped -- the next change to the object re-renders the whole card anyway.
EDIT_PENDING_ATTEMPTS = 5


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


def _discord_error(exc: discord.HTTPException) -> str:
    return f"HTTP {exc.status} (code {exc.code}): {exc.text}"


def _mentions(event: DiscordCommandEvent) -> discord.AllowedMentions:
    """Who the message may ping.

    ``allow_mentions`` is the publisher saying "the ``<@id>`` mentions in this
    card are mine, let them ring" -- a mix lineup calling its players in. Even
    then ``@everyone`` and roles stay off: card text can quote a user-written
    team name, and no publisher is allowed to ring a whole guild.
    """
    if event.allow_mentions:
        return discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)
    return discord.AllowedMentions.none()


class DiscordRabbitGateway:
    """Owns the broker's lifecycle and every RabbitMQ subscriber this service exposes."""

    def __init__(
        self,
        *,
        settings: Settings,
        processor: AttachmentProcessor,
        registry: ChannelRegistry,
        directory: DiscordDirectoryService,
        voice: VoiceMover,
        result_waiter: ResultWaiter,
        bot: discord.Client,
        session_maker: async_sessionmaker[AsyncSession],
        messages: DiscordMessageRepository = DiscordMessageRepository(),
    ) -> None:
        self._settings = settings
        self._processor = processor
        self._registry = registry
        self._directory = directory
        self._voice = voice
        self._result_waiter = result_waiter
        self._bot = bot
        self._session_maker = session_maker
        self._messages = messages
        self._broker: RabbitBroker | None = None
        # discord_message ids with an edit owed, and the task that will write
        # it. ponytail: process memory, like every other window in this
        # service. A crash between the click and the flush loses that one edit;
        # the next mutation re-renders the whole card, so nothing drifts
        # permanently.
        self._pending_edits: set[int] = set()
        self._edit_tasks: dict[int, asyncio.Task[None]] = {}
        #: The newest PNG an owed edit carries, waiting for its flush.
        self._pending_images: dict[int, discord.File] = {}

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
        for task in list(self._edit_tasks.values()):
            task.cancel()
        self._pending_images.clear()
        if self._broker is None:
            return
        try:
            await self._broker.close()
        finally:
            self._broker = None
            set_worker_broker(None)

    def _partial_message(self, row: models.DiscordMessage) -> discord.PartialMessage:
        """The message this row stands for, without fetching it.

        ``get_partial_messageable`` builds a channel handle out of an id alone,
        and a DM channel answers edits and deletes exactly like a guild one --
        which is why the row stores ``discord_channel_id`` rather than where
        the message was addressed. One path edits and deletes both.
        """
        return self._bot.get_partial_messageable(row.discord_channel_id).get_partial_message(row.message_id)

    async def _settle(self, session: AsyncSession, row: models.DiscordMessage, change: Awaitable[Any]) -> Any:
        """Commit one status change and tell the page that shows this subject.

        A database failure here is logged, never raised: by the time it runs
        Discord has already acted, and nacking the command would send or delete
        the message a second time. The row keeps its old status -- a ``pending``
        that reads ``lost`` once the command's TTL passes, which is visible and
        fixable, unlike a card posted twice.
        """
        try:
            applied = await change
            await emit_changed(session, row)
            await session.commit()
            return applied
        except Exception as exc:
            await session.rollback()
            logger.error(f"❌ Could not record the new state of discord_message {row.id}: {exc}")
            return None

    async def _row_to_send(
        self,
        session: AsyncSession,
        event: DiscordCommandEvent,
        msg: RabbitMessage,
        observation: Any,
    ) -> models.DiscordMessage | None:
        """The row this send still has to produce, or ``None`` when it is settled here.

        The row, not the command, decides whether Discord is touched at all.
        Nothing de-duplicates ``discord_commands`` any more, so a redelivery is
        caught here: a row past ``pending`` has already been sent (or refused)
        and the repeat is acked without a second message. A row a delete got to
        first is closed without ever being sent -- that delete acked on the
        promise that this handler would finish its job.
        """
        row = await self._messages.get(session, event.message_ref)
        if row is None:
            observation.set_status("not_found")
            logger.error(f"❌ discord_message {event.message_ref} is gone; dropping its {event.action}")
            await msg.reject()
            return None

        if row.status == "deleting":
            observation.set_status("deleted")
            logger.info(f"🗑️ discord_message {row.id} was deleted before it was sent; sending nothing")
            await self._settle(session, row, self._messages.mark_deleted(session, row.id))
            await msg.ack()
            return None

        if row.status != "pending":
            observation.set_status("already_sent")
            logger.warning(f"⚠️ discord_message {row.id} is {row.status}; dropping a repeated {event.action}")
            await msg.ack()
            return None

        return row

    async def _record_posted(self, session: AsyncSession, row: models.DiscordMessage, sent: discord.Message) -> None:
        """The row learns where the message landed -- or the message is taken back.

        ``mark_posted`` applies only while the row is still ``pending``, and it
        is not when a delete arrived mid-``send``: that delete found no message
        id, left the row ``deleting`` and removed nothing, trusting this
        handler. The bot is the only process holding the message it has just
        created, so it removes it here rather than leaving a card everyone
        believes is gone. ``None`` back from :meth:`_settle` is a database
        failure, not a refusal -- nothing is undone for it.
        """
        posted = await self._settle(
            session,
            row,
            self._messages.mark_posted(session, row.id, discord_channel_id=sent.channel.id, discord_message_id=sent.id),
        )
        if posted is not False:
            return

        logger.info(f"🗑️ discord_message {row.id} was deleted while it was being sent; taking the message back")
        try:
            await sent.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            # Left ``deleting``, like every other delete Discord refuses.
            logger.error(f"❌ Could not take back message {sent.id}: {_discord_error(exc)}")
            return
        await self._settle(session, row, self._messages.mark_deleted(session, row.id))

    async def _fail(self, session: AsyncSession, row: models.DiscordMessage, reason: str) -> None:
        """Discord refused this message for good; whoever asked for it reads why."""
        await self._settle(session, row, self._messages.mark_failed(session, row.id, error=reason))

    def _schedule_edit(self, ref: int, image: discord.File | None = None) -> None:
        """Note that this message owes an edit; the flush shows the card its row holds by then."""
        if image is not None:
            # The newest PNG wins, like the card: it is the one the row's card
            # at flush time was rendered beside.
            self._pending_images[ref] = image
        self._pending_edits.add(ref)
        if ref not in self._edit_tasks:
            self._edit_tasks[ref] = asyncio.create_task(self._flush_edit(ref))

    async def _flush_edit(self, ref: int) -> None:
        """After the coalescing window, show the card the row holds at flush time.

        The row says where the message is -- and whether it exists yet. An edit
        published right behind the post that creates it can be handled first,
        so a ``pending`` row is waited out for a few more windows instead of
        being dropped. Any other status means the card will never be shown
        again (refused, being deleted, gone), and the edit is discarded.
        """
        try:
            for _attempt in range(EDIT_PENDING_ATTEMPTS):
                await asyncio.sleep(EDIT_COALESCE_SECONDS)
                if ref not in self._pending_edits:
                    return  # a delete dropped it while the window ran
                async with self._session_maker() as session:
                    row = await self._messages.get(session, ref)
                    if row is not None and row.status == "pending":
                        continue
                    self._pending_edits.discard(ref)
                    # Past this point the edit is either written or dropped,
                    # and its PNG goes with it: the next render brings its own.
                    image = self._pending_images.pop(ref, None)
                    if row is None:
                        logger.error(f"❌ discord_message {ref} is gone; dropping its edit")
                        return
                    if row.status != "posted":
                        logger.warning(f"⚠️ discord_message {ref} is {row.status}; dropping its edit")
                        return
                    if row.card_json is None:
                        logger.warning(f"⚠️ discord_message {ref} holds no card; dropping its edit")
                        return
                    try:
                        card = DiscordCard.model_validate(row.card_json)
                    except ValidationError as exc:
                        logger.error(f"❌ discord_message {ref} holds an unusable card; dropping its edit: {exc}")
                        return
                    await self._apply_edit(session, row, card, image)
                    return
            self._pending_edits.discard(ref)
            self._pending_images.pop(ref, None)
            logger.warning(f"⚠️ discord_message {ref} is still not posted; dropping its edit")
        finally:
            self._edit_tasks.pop(ref, None)
            if ref in self._pending_edits:
                # A ping landed while this flush was writing the previous
                # card: nothing else would pick it up, and the live post would
                # stay a seat behind until the next one.
                self._schedule_edit(ref)

    async def _apply_edit(
        self,
        session: AsyncSession,
        row: models.DiscordMessage,
        card: DiscordCard,
        image: discord.File | None = None,
    ) -> None:
        """Replace the card of a posted message; a message that is gone closes its row."""
        extra: dict[str, Any] = {}
        if image is not None and card.attachment_name == image.filename:
            extra["attachments"] = [image]
        elif card.attachment_name is None:
            # A card that became text drops the picture it used to show.
            extra["attachments"] = []
        try:
            # No fetch: the ids are enough to edit, and the card comes from the
            # row anyway.
            await self._partial_message(row).edit(
                view=card_view(card),
                allowed_mentions=discord.AllowedMentions.none(),
                **extra,
            )
        except discord.NotFound:
            logger.warning(f"⚠️ Message {row.message_id} is gone; closing discord_message {row.id}")
            await self._settle(session, row, self._messages.mark_deleted(session, row.id))
        except discord.Forbidden:
            logger.error(f"❌ No permission to edit message {row.message_id} in channel {row.discord_channel_id}")
        except discord.HTTPException as exc:
            logger.error(f"❌ Discord refused edit of message {row.message_id}: {_discord_error(exc)}")

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
                        logger.info(f"📩 RabbitMQ command: post_message channel={event.channel_id}")
                        async with self._session_maker() as session:
                            row = await self._row_to_send(session, event, msg, observation)
                            if row is None:
                                return

                            channel = await self._processor.get_text_channel(event.channel_id)
                            if channel is None:
                                observation.set_status("not_found")
                                logger.error(f"❌ Channel {event.channel_id} not found for post_message")
                                await self._fail(session, row, "the channel does not exist or the bot cannot see it")
                                await msg.reject()
                                return

                            try:
                                attachment = _attachment(event)
                            except ValueError as exc:
                                observation.set_status("invalid")
                                logger.error(f"❌ Undecodable image for channel {event.channel_id}: {exc}")
                                await self._fail(session, row, f"the picture of the post could not be decoded: {exc}")
                                await msg.reject()
                                return

                            try:
                                sent = await channel.send(
                                    view=card_view(event.card),
                                    file=attachment,
                                    allowed_mentions=_mentions(event),
                                )
                            except discord.Forbidden:
                                observation.set_status("forbidden")
                                logger.error(f"❌ No permission to post in channel {event.channel_id}")
                                await self._fail(session, row, "no permission to post in the channel")
                                await msg.reject()
                                return
                            except discord.HTTPException as exc:
                                # discord.py already retried 429s and 5xx; what is left
                                # (a 400 on the payload, an outage outlasting its
                                # retries) fails the same way on every requeue.
                                observation.set_status("discord_error")
                                logger.error(
                                    f"❌ Discord refused post to channel {event.channel_id}: {_discord_error(exc)}"
                                )
                                await self._fail(session, row, f"Discord refused the post: {_discord_error(exc)}")
                                await msg.reject()
                                return

                            await self._record_posted(session, row, sent)

                        await msg.ack()
                        return

                    if event.action == "send_dm":
                        logger.info(f"📩 RabbitMQ command: send_dm user={event.discord_user_id}")
                        async with self._session_maker() as session:
                            row = await self._row_to_send(session, event, msg, observation)
                            if row is None:
                                return

                            try:
                                user = self._bot.get_user(event.discord_user_id) or await self._bot.fetch_user(
                                    event.discord_user_id
                                )
                                sent = await user.send(
                                    view=card_view(event.card),
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )
                            except discord.Forbidden:
                                # DMs closed or no mutual guild: a retry cannot fix either,
                                # and the notification is already in the in-app inbox.
                                observation.set_status("dm_closed")
                                logger.warning(f"⚠️ Cannot DM user {event.discord_user_id}: DMs closed")
                                await self._fail(session, row, "the user does not accept DMs from the bot")
                                await msg.ack()
                                return
                            except discord.NotFound:
                                observation.set_status("not_found")
                                logger.warning(f"⚠️ Discord user {event.discord_user_id} not found for send_dm")
                                await self._fail(session, row, "the Discord user no longer exists")
                                await msg.ack()
                                return
                            except discord.HTTPException as exc:
                                observation.set_status("discord_error")
                                logger.error(
                                    f"❌ Discord refused DM to user {event.discord_user_id}: {_discord_error(exc)}"
                                )
                                await self._fail(session, row, f"Discord refused the DM: {_discord_error(exc)}")
                                await msg.reject()
                                return

                            await self._record_posted(session, row, sent)

                        await msg.ack()
                        return

                    if event.action == "edit_message":
                        logger.info(f"📩 RabbitMQ command: edit_message message_ref={event.message_ref}")
                        # Acked on scheduling, not on delivery: the edit is
                        # deliberately deferred, and a redelivery would only
                        # ask for an edit the pending one already covers.
                        try:
                            image = _attachment(event)
                        except ValueError as exc:
                            logger.error(f"❌ edit_message {event.message_ref} carried a broken PNG: {exc}")
                            image = None
                        self._schedule_edit(event.message_ref, image)
                        await msg.ack()
                        return

                    if event.action == "delete_message":
                        logger.info(f"📩 RabbitMQ command: delete_message message_ref={event.message_ref}")
                        # Nothing is edited on the way out: an edit owed by
                        # this message would otherwise be written to a message
                        # that is about to stop existing.
                        self._pending_edits.discard(event.message_ref)
                        self._pending_images.pop(event.message_ref, None)
                        async with self._session_maker() as session:
                            row = await self._messages.get(session, event.message_ref)
                            if row is None:
                                observation.set_status("not_found")
                                logger.error(f"❌ discord_message {event.message_ref} is gone; cannot delete it")
                                await msg.reject()
                                return

                            if row.message_id is None:
                                # Its own post is still queued (``delete_commands``
                                # already set the row to ``deleting``). Left alone:
                                # that status is exactly what the post handler
                                # reads before it sends anything, so the message is
                                # deleted by never being sent.
                                observation.set_status("not_posted")
                                logger.info(f"⏳ discord_message {row.id} is not posted yet; its post will close it")
                                await msg.ack()
                                return

                            if row.status not in ("deleting", "posted"):
                                observation.set_status("already_settled")
                                logger.info(f"ℹ️ discord_message {row.id} is {row.status}; nothing to delete")
                                await msg.ack()
                                return

                            try:
                                await self._partial_message(row).delete()
                            except discord.NotFound:
                                logger.info(f"ℹ️ Message {row.message_id} was already gone; closing its row")
                            except discord.HTTPException as exc:
                                # Left ``deleting`` on purpose: a requeue would
                                # hammer the same refusal, and the page shows
                                # the message as still on its way out, which is
                                # the truth until someone fixes the permission.
                                observation.set_status("discord_error")
                                logger.error(f"❌ Could not delete message {row.message_id}: {_discord_error(exc)}")
                                await msg.ack()
                                return

                            await self._settle(session, row, self._messages.mark_deleted(session, row.id))

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

        @broker.subscriber(DISCORD_VOICE_MOVE_QUEUE)
        async def handle_voice_move(body: dict[str, Any], msg: RabbitMessage) -> dict[str, Any]:
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=DISCORD_VOICE_MOVE_QUEUE,
                handler="handle_voice_move",
                message=msg,
                logger=logger,
            ) as observation:
                outcome = await self._voice.move(
                    str(body.get("guild_id") or "").strip(),
                    category_id=str(body.get("category_id") or "").strip(),
                    moves=list(body.get("moves") or []),
                    drain=body.get("drain") or None,
                )
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
