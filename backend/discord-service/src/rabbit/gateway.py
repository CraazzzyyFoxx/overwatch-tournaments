"""Wires the bot onto RabbitMQ: the platform's ``discord_message`` commands, the
mix projector, match-log verdicts, tournament changes that move the
watched-channel set, the guild/member/voice lookups other services call and
the ``rpc.discord.*`` API (:mod:`src.rpc_api`).

A command is ``send`` or ``delete`` and names a ``discord_message`` row
(``message_ref``) -- nothing else. The row says where the message goes and
what it is about; the bot renders the card from it (:mod:`src.render`), and
being the only process that hears Discord answer, writes back what happened.
The row -- not the command -- is what makes a redelivery harmless and what a
later delete is resolved from.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord
import sqlalchemy as sa
from faststream.rabbit import Channel, RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.messaging.config import (
    CACHE_INVALIDATION_DISCORD_VOICE_DLQ,
    DISCORD_COMMANDS_DLQ,
    DISCORD_COMMANDS_QUEUE,
    DISCORD_GUILD_CHANNELS_DLQ,
    DISCORD_GUILD_CHANNELS_QUEUE,
    DISCORD_GUILD_INFO_DLQ,
    DISCORD_GUILD_INFO_QUEUE,
    DISCORD_GUILD_ROLES_DLQ,
    DISCORD_GUILD_ROLES_QUEUE,
    DISCORD_MEMBER_ROLES_DLQ,
    DISCORD_MEMBER_ROLES_QUEUE,
    DISCORD_VOICE_MOVE_DLQ,
    DISCORD_VOICE_MOVE_QUEUE,
    DISCORD_VOICE_SYNC_DLQ,
    FLOW_NODE_STATE_CHANGED_ROUTING_KEY,
    MATCH_LOG_RESULT_DLQ,
    MATCH_LOG_RESULT_QUEUE,
    PICKUP_MIX_CHANGED_DLQ,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_STATE_CHANGED_ROUTING_KEY,
)
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import make_rabbit_broker, observe_message_processing
from shared.repository.discord_message import LIVE_STATUSES, DiscordMessageRepository
from shared.schemas.events import DiscordCommandEvent, FlowNodeStateChangedEvent, MatchLogProcessedEvent
from shared.schemas.rpc import rpc_error, rpc_ok
from shared.services.discord_messages import emit_changed
from src import rpc_api
from src.core.broker import set_worker_broker
from src.core.config import Settings
from src.interactions.cards import card_view
from src.render import Rendered, lineup_key, render
from src.services.attachment_processor import AttachmentProcessor
from src.services.channel_registry import ChannelRegistry
from src.services.directory import DirectoryOutcome, DiscordDirectoryService
from src.services.mix_projector import MixProjector
from src.services.voice import VoiceMover
from src.services.voice_sync import VoiceSync

_DIRECTORY_CODES = {
    "guild_not_found": "not_found",
    "invalid": "bad_request",
    "error": "internal",
}

# Dead-letter queues of every durable queue this bot consumes. Each one dead-letters to
# ``dlx`` under ``<name>.dlq``, and RabbitMQ creates nothing for that key: undeclared, an
# expired or rejected message vanishes instead of landing where an operator can see it.
_OWNED_DLQS = (
    DISCORD_COMMANDS_DLQ,
    DISCORD_MEMBER_ROLES_DLQ,
    DISCORD_GUILD_ROLES_DLQ,
    DISCORD_GUILD_CHANNELS_DLQ,
    DISCORD_GUILD_INFO_DLQ,
    DISCORD_VOICE_MOVE_DLQ,
    DISCORD_VOICE_SYNC_DLQ,
    CACHE_INVALIDATION_DISCORD_VOICE_DLQ,
    MATCH_LOG_RESULT_DLQ,
    PICKUP_MIX_CHANGED_DLQ,
)


def _directory_reply(outcome: DirectoryOutcome) -> dict[str, Any]:
    if outcome.status == "success":
        return rpc_ok(outcome.payload)
    code = _DIRECTORY_CODES.get(outcome.status, "internal")
    message = str(outcome.payload.get("error") or outcome.status)
    return rpc_error(code, message)


def _discord_error(exc: discord.HTTPException) -> str:
    return f"HTTP {exc.status} (code {exc.code}): {exc.text}"


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
        voice_sync: VoiceSync,
        bot: discord.Client,
        session_maker: async_sessionmaker[AsyncSession],
        projector: MixProjector,
        messages: DiscordMessageRepository = DiscordMessageRepository(),
        renderer: Callable[..., Any] = render,
    ) -> None:
        self._settings = settings
        self._processor = processor
        self._registry = registry
        self._directory = directory
        self._voice = voice
        self._voice_sync = voice_sync
        self._bot = bot
        self._session_maker = session_maker
        self._projector = projector
        self._messages = messages
        self._render = renderer
        self._broker: RabbitBroker | None = None

    async def start(self) -> None:
        if not self._settings.broker_url:
            logger.info("ℹ️ RABBITMQ_URL not set; RabbitMQ listener disabled")
            return

        broker = make_rabbit_broker(self._settings.broker_url, logger=logger)
        # Held before any consumer starts: a send renders through it (the mix view RPC).
        self._broker = broker
        self._register(broker)
        # The DLQs exist before the first consumer can reject into them.
        await broker.connect()
        for dlq in _OWNED_DLQS:
            await declare_dead_letter_queue(broker, dlq)
        await broker.start()
        # Publish to the global only once the broker is actually started: gateway
        # member events fire as soon as discord.py connects and publish through it
        # (MembershipEventsCog). A half-initialised global there means a publish
        # against a broker with no connection.
        set_worker_broker(broker)
        logger.success(f"✅ RabbitMQ listener started (queue='{DISCORD_COMMANDS_QUEUE}')")

    async def close(self) -> None:
        self._projector.close()
        if self._broker is None:
            return
        try:
            await self._broker.close()
        finally:
            self._broker = None
            set_worker_broker(None)

    # --- discord_message state -----------------------------------------------

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

    async def _fail(self, session: AsyncSession, row: models.DiscordMessage, reason: str) -> None:
        """This message will never be sent; whoever asked for it reads why."""
        await self._settle(session, row, self._messages.mark_failed(session, row.id, error=reason))

    async def _row_to_send(
        self, session: AsyncSession, ref: int, msg: RabbitMessage, observation: Any
    ) -> models.DiscordMessage | None:
        """The row this send still has to produce, or ``None`` when it is settled here.

        The row, not the command, decides whether Discord is touched at all.
        Nothing upstream de-duplicates ``discord_commands``, so a redelivery is
        caught here: a row past ``pending`` has already been sent (or refused)
        and the repeat is acked without a second message. A row a delete got to
        first is closed without ever being sent -- that delete acked on the
        promise that this handler would finish its job.
        """
        row = await self._messages.get(session, ref)
        if row is None:
            observation.set_status("not_found")
            logger.error(f"❌ discord_message {ref} is gone; dropping its send")
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
            logger.warning(f"⚠️ discord_message {row.id} is {row.status}; dropping a repeated send")
            await msg.ack()
            return None

        return row

    async def _rendered(
        self, session: AsyncSession, row: models.DiscordMessage, msg: RabbitMessage, observation: Any
    ) -> Rendered | None:
        """The card to send, or ``None`` with the row failed: there is nothing left to show."""
        rendered = await self._render(session, row, broker=self._broker)
        if isinstance(rendered, Rendered):
            return rendered
        observation.set_status("nothing_to_render")
        logger.warning(f"⚠️ discord_message {row.id} ({row.kind} {row.subject}) has nothing to show; not sending it")
        await self._fail(session, row, "nothing to render")
        await msg.ack()
        return None

    async def _workspace_guild_id(self, session: AsyncSession, workspace_id: int | None) -> str | None:
        if workspace_id is None:
            return None
        return await session.scalar(
            sa.select(models.Workspace.discord_guild_id).where(models.Workspace.id == workspace_id)
        )

    async def _record_posted(
        self, session: AsyncSession, row: models.DiscordMessage, sent: discord.Message, rendered: Rendered
    ) -> None:
        """The row learns where the message landed and what it shows -- or the message is taken back.

        ``mark_posted`` applies only while the row is still ``pending``, and it
        is not when a delete arrived mid-``send``: that delete found no message
        id, left the row ``deleting`` and removed nothing, trusting this
        handler. The bot is the only process holding the message it has just
        created, so it removes it here rather than leaving a card everyone
        believes is gone. ``None`` back from :meth:`_settle` is a database
        failure, not a refusal -- nothing is undone for it.
        """

        async def posted() -> bool:
            await self._messages.set_card(session, row.id, rendered.card.model_dump(mode="json"))
            return await self._messages.mark_posted(
                session, row.id, discord_channel_id=sent.channel.id, discord_message_id=sent.id
            )

        applied = await self._settle(session, row, posted())
        if applied is None:
            return
        if applied:
            if row.kind == "mix.lineup":
                await self._retire_voice_buttons(session, row)
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

    async def _retire_voice_buttons(self, session: AsyncSession, row: models.DiscordMessage) -> None:
        """A new lineup took the lobby's voice buttons: its older live cards re-render without them."""
        lobby = lineup_key(row.slot)
        for other in await self._messages.for_subject(session, row.subject, statuses=LIVE_STATUSES):
            other_key = lineup_key(other.slot)
            if other.id != row.id and lobby is not None and other_key is not None and other_key[0] == lobby[0]:
                self._projector.schedule(other.id)

    # --- discord_commands ----------------------------------------------------

    async def _send(self, ref: int, msg: RabbitMessage, observation: Any) -> None:
        """Render the row and send it where it says: a guild channel, or a user's DMs."""
        async with self._session_maker() as session:
            row = await self._row_to_send(session, ref, msg, observation)
            if row is None:
                return
            logger.info(f"📩 send discord_message {row.id} ({row.kind}) to {row.channel} {row.target}")
            if row.channel == "discord_dm":
                await self._send_dm(session, row, msg, observation)
            else:
                await self._post(session, row, msg, observation)

    async def _post(
        self, session: AsyncSession, row: models.DiscordMessage, msg: RabbitMessage, observation: Any
    ) -> None:
        channel = await self._processor.get_text_channel(int(row.target))
        if channel is None:
            observation.set_status("not_found")
            logger.error(f"❌ Channel {row.target} not found for discord_message {row.id}")
            await self._fail(session, row, "the channel does not exist or the bot cannot see it")
            await msg.reject()
            return

        # A workspace posts into its own guild only: the channel id came from
        # an admin form, and the bot sits in every workspace's guild.
        guild = getattr(channel, "guild", None)
        guild_id = await self._workspace_guild_id(session, row.workspace_id)
        if guild is None or guild_id is None or str(guild.id) != guild_id:
            observation.set_status("wrong_guild")
            logger.error(
                f"❌ Channel {row.target} is not in the Discord guild of workspace {row.workspace_id}; "
                f"refusing discord_message {row.id}"
            )
            await self._fail(session, row, "channel is not in the workspace's Discord guild")
            await msg.reject()
            return

        rendered = await self._rendered(session, row, msg, observation)
        if rendered is None:
            return

        try:
            # The row id as nonce: Discord answers a repeat within its window
            # with the message it already created, so a crash between this
            # send and ``mark_posted`` does not post the card twice.
            sent = await channel.send(
                view=card_view(rendered.card),
                file=rendered.file,
                allowed_mentions=rendered.allowed_mentions,
                nonce=row.id,
            )
        except discord.Forbidden:
            observation.set_status("forbidden")
            logger.error(f"❌ No permission to post in channel {row.target}")
            await self._fail(session, row, "no permission to post in the channel")
            await msg.reject()
            return
        except discord.HTTPException as exc:
            # discord.py already retried 429s and 5xx; what is left (a 400 on
            # the payload, an outage outlasting its retries) fails the same way
            # on every requeue.
            observation.set_status("discord_error")
            logger.error(f"❌ Discord refused post to channel {row.target}: {_discord_error(exc)}")
            await self._fail(session, row, f"Discord refused the post: {_discord_error(exc)}")
            await msg.reject()
            return

        await self._record_posted(session, row, sent, rendered)
        await msg.ack()

    async def _send_dm(
        self, session: AsyncSession, row: models.DiscordMessage, msg: RabbitMessage, observation: Any
    ) -> None:
        rendered = await self._rendered(session, row, msg, observation)
        if rendered is None:
            return

        user_id = int(row.target)
        try:
            user = self._bot.get_user(user_id) or await self._bot.fetch_user(user_id)
            sent = await user.send(
                view=card_view(rendered.card),
                file=rendered.file,
                allowed_mentions=rendered.allowed_mentions,
                nonce=row.id,
            )
        except discord.Forbidden:
            # DMs closed or no mutual guild: a retry cannot fix either, and the
            # notification is already in the in-app inbox.
            observation.set_status("dm_closed")
            logger.warning(f"⚠️ Cannot DM user {user_id}: DMs closed")
            await self._fail(session, row, "the user does not accept DMs from the bot")
            await msg.ack()
            return
        except discord.NotFound:
            observation.set_status("not_found")
            logger.warning(f"⚠️ Discord user {user_id} not found for discord_message {row.id}")
            await self._fail(session, row, "the Discord user no longer exists")
            await msg.ack()
            return
        except discord.HTTPException as exc:
            observation.set_status("discord_error")
            logger.error(f"❌ Discord refused DM to user {user_id}: {_discord_error(exc)}")
            await self._fail(session, row, f"Discord refused the DM: {_discord_error(exc)}")
            await msg.reject()
            return

        await self._record_posted(session, row, sent, rendered)
        await msg.ack()

    async def _delete(self, ref: int, msg: RabbitMessage, observation: Any) -> None:
        async with self._session_maker() as session:
            row = await self._messages.get(session, ref)
            if row is None:
                observation.set_status("not_found")
                logger.error(f"❌ discord_message {ref} is gone; cannot delete it")
                await msg.reject()
                return

            if row.message_id is None:
                # Its own send is still queued (``delete_commands`` already set
                # the row to ``deleting``). Left alone: that status is exactly
                # what the send handler reads before it sends anything, so the
                # message is deleted by never being sent.
                observation.set_status("not_posted")
                logger.info(f"⏳ discord_message {row.id} is not posted yet; its send will close it")
                await msg.ack()
                return

            if row.status not in ("deleting", "posted"):
                observation.set_status("already_settled")
                logger.info(f"ℹ️ discord_message {row.id} is {row.status}; nothing to delete")
                await msg.ack()
                return

            try:
                # No fetch: the ids are enough, and a DM channel answers a
                # delete exactly like a guild one.
                await (
                    self._bot.get_partial_messageable(row.discord_channel_id)
                    .get_partial_message(row.message_id)
                    .delete()
                )
            except discord.NotFound:
                logger.info(f"ℹ️ Message {row.message_id} was already gone; closing its row")
            except discord.HTTPException as exc:
                # Left ``deleting`` on purpose: a requeue would hammer the same
                # refusal, and the page shows the message as still on its way
                # out, which is the truth until someone fixes the permission.
                observation.set_status("discord_error")
                logger.error(f"❌ Could not delete message {row.message_id}: {_discord_error(exc)}")
                await msg.ack()
                return

            await self._settle(session, row, self._messages.mark_deleted(session, row.id))
        await msg.ack()

    async def _on_flow_node_state_changed(self, body: dict[str, Any]) -> None:
        """A node moved: reload the channel map; a stage going live or completing re-plans that tournament's voice."""
        event = FlowNodeStateChangedEvent.model_validate(body)
        await self._registry.reload()
        if event.kind == "stage" and event.new_status in {"live", "completed"}:
            self._voice_sync.request(event.tournament_id)

    # --- subscribers -----------------------------------------------------------

    def _register(self, broker: RabbitBroker) -> None:
        # Its own channel and QoS window: each send renders a card (an RPC, a
        # picture drawn) before Discord answers, and a burst must queue at the
        # broker rather than start one task per delivery.
        @broker.subscriber(DISCORD_COMMANDS_QUEUE, channel=Channel(prefetch_count=4))
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
                    if event.action == "send":
                        await self._send(event.message_ref, msg, observation)
                    else:
                        await self._delete(event.message_ref, msg, observation)
                except Exception as e:
                    logger.error(f"❌ Error handling discord command: {e}")
                    await msg.nack()  # Requeue for retry
                    raise

        self._projector.register(broker)
        self._voice_sync.register(broker)

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

        @broker.subscriber(MATCH_LOG_RESULT_QUEUE)
        async def handle_match_log_result(body: dict[str, Any], msg: RabbitMessage) -> None:
            """Stats's verdict for one uploaded file, put on the message it came from.

            One durable work queue: the event names its message, so any replica can
            answer it. A message that is gone from Discord is not worth a retry.
            """
            await self._bot.wait_until_ready()
            async with observe_message_processing(
                queue=MATCH_LOG_RESULT_QUEUE,
                handler="handle_match_log_result",
                message=msg,
                logger=logger,
            ) as observation:
                try:
                    event = MatchLogProcessedEvent.model_validate(body)
                except ValidationError as e:
                    observation.set_status("invalid")
                    logger.error(f"❌ Invalid match_log_processed payload: {e}")
                    await msg.reject()  # Send to DLQ
                    return

                if event.channel_id is None or event.message_id is None:
                    observation.set_status("no_message")
                    logger.info(f"ℹ️ Verdict for {event.filename} names no Discord message; nothing to react on")
                    return

                channel = await self._processor.get_text_channel(event.channel_id)
                try:
                    message = await channel.fetch_message(event.message_id) if channel is not None else None
                except discord.NotFound, discord.Forbidden:
                    message = None
                if message is None:
                    observation.set_status("not_found")
                    logger.warning(
                        f"⚠️ Message {event.message_id} in channel {event.channel_id} is gone or hidden; "
                        f"dropping the verdict for {event.filename}"
                    )
                    return

                await self._processor.apply_result(message, event)

        # Each replica keeps its own watched-channel set, so each one needs every
        # change: a server-named, exclusive, auto-deleted queue per replica. A
        # binding changed through ``rpc.discord.channel.*`` reloads in-process.
        @broker.subscriber(
            RabbitQueue("", exclusive=True, auto_delete=True, routing_key=TOURNAMENT_STATE_CHANGED_ROUTING_KEY),
            TOURNAMENT_EVENTS_EXCHANGE,
        )
        async def handle_channel_registry_change(body: dict[str, Any], msg: RabbitMessage) -> None:
            async with observe_message_processing(
                queue="channel_registry",
                handler="handle_channel_registry_change",
                message=msg,
                logger=logger,
            ):
                await self._registry.reload()
                # A finished tournament loses its channels; a started one gets its team voices.
                if isinstance(tournament_id := body.get("tournament_id"), int):
                    self._voice_sync.request(tournament_id)

        @broker.subscriber(
            RabbitQueue("", exclusive=True, auto_delete=True, routing_key=FLOW_NODE_STATE_CHANGED_ROUTING_KEY),
            TOURNAMENT_EVENTS_EXCHANGE,
        )
        async def handle_flow_node_state_changed(body: dict[str, Any], msg: RabbitMessage) -> None:
            async with observe_message_processing(
                queue="flow_node_state",
                handler="handle_flow_node_state_changed",
                message=msg,
                logger=logger,
            ):
                await self._on_flow_node_state_changed(body)

        rpc_api.register(
            broker,
            bot=self._bot,
            registry=self._registry,
            directory=self._directory,
            session_maker=self._session_maker,
            logger=logger,
        )
