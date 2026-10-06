"""How a service sends, edits and deletes Discord messages: through ``discord_message``.

Every message the platform sends is claimed here first, in the publisher's own
transaction, and the command handed back names the row (``message_ref``). The
caller publishes it the way it already publishes -- the outbox in the same
transaction (app-service), or right after its commit (balancer-service) -- and
discord-service records what Discord answered on the same row. Edits and
deletes go through the row too, so "delete every Discord message of mix 42" is
:func:`delete_commands` over :meth:`DiscordMessageRepository.for_subject`.

Messages the bot sends from inside Discord (button replies, match-log feedback)
never come through here: nobody outside Discord addresses them again.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from shared import models
from shared.messaging.config import DISCORD_COMMANDS_QUEUE
from shared.repository.discord_message import DiscordMessageRepository
from shared.schemas.events import DiscordCard, DiscordCommandEvent
from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = (
    "delete_commands",
    "edit_command",
    "effective_status",
    "emit_changed",
    "jump_url",
    "repository",
    "send_command",
)

repository = DiscordMessageRepository()

#: A ``pending`` row older than the command's own TTL on ``discord_commands``
#: will never be sent: RabbitMQ dropped the command. Reported as ``lost``
#: rather than "posting..." forever.
_PENDING_TTL = timedelta(milliseconds=int(DISCORD_COMMANDS_QUEUE.arguments["x-message-ttl"]))

#: How the page that shows a subject's messages hears that one changed, by
#: subject prefix (``mix:42`` -> ``mix``): the resource it invalidates and the
#: domain signal it already listens to -- for a mix, exactly what
#: balancer-service's ``emit_pickup_mix_updated`` sends. A subject not listed
#: here has no page that shows its messages.
_SUBJECT_SIGNALS: dict[str, tuple[Resource, str, str]] = {
    "mix": (Resource.WORKSPACE_PICKUP_MIX, "pickup_mix", "pickup_mix.updated"),
}


async def send_command(
    session: Any,
    *,
    subject: str,
    slot: str,
    kind: str,
    card: DiscordCard,
    workspace_id: int | None,
    channel_id: int | None = None,
    discord_user_id: int | None = None,
    dedupe_key: str | None = None,
    notification_id: int | None = None,
    image_b64: str | None = None,
    image_filename: str = "lineup.png",
    allow_mentions: bool = False,
) -> DiscordCommandEvent | None:
    """Claim a new message and the command that sends it; ``None`` when ``dedupe_key`` was taken.

    Exactly one of ``channel_id`` (a channel post) and ``discord_user_id`` (a
    DM) names the destination. The row is ``pending`` until the bot answers.
    """
    if (channel_id is None) == (discord_user_id is None):
        raise ValueError("exactly one of channel_id and discord_user_id")
    dm = discord_user_id is not None
    row_id = await repository.claim(
        session,
        channel="discord_dm" if dm else "discord_channel",
        target=str(discord_user_id if dm else channel_id),
        subject=subject,
        slot=slot,
        kind=kind,
        dedupe_key=dedupe_key,
        notification_id=notification_id,
        workspace_id=workspace_id,
    )
    if row_id is None:
        return None
    return DiscordCommandEvent(
        action="send_dm" if dm else "post_message",
        channel_id=channel_id,
        discord_user_id=discord_user_id,
        message_ref=row_id,
        card=card,
        image_b64=image_b64,
        image_filename=image_filename,
        allow_mentions=allow_mentions,
    )


def edit_command(row: models.DiscordMessage, card: DiscordCard) -> DiscordCommandEvent | None:
    """Replace the card of a live message; ``None`` for one that is gone or never was."""
    if row.status not in ("pending", "posted"):
        return None
    return DiscordCommandEvent(action="edit_message", message_ref=row.id, card=card)


async def delete_commands(session: Any, rows: Sequence[models.DiscordMessage]) -> list[DiscordCommandEvent]:
    """Mark these messages for deletion and return the commands that delete them.

    A message Discord refused never existed, so it is closed here without a
    command; one already deleting or deleted is left alone, which makes a
    second click harmless. A ``pending`` one is deleted too: the bot works
    ``discord_commands`` in order, so its post lands before the delete does.
    """
    commands: list[DiscordCommandEvent] = []
    for row in rows:
        if row.status == "failed":
            await repository.mark_deleted(session, row.id)
        elif row.status in ("pending", "posted"):
            await repository.mark_deleting(session, row.id)
            commands.append(DiscordCommandEvent(action="delete_message", message_ref=row.id))
    return commands


def effective_status(row: models.DiscordMessage, *, now: datetime | None = None) -> str:
    """``row.status``, except a ``pending`` the broker has certainly dropped reads ``lost``."""
    if row.status != "pending":
        return row.status
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    return "lost" if (now or datetime.now(UTC)) - created > _PENDING_TTL else "pending"


def jump_url(row: models.DiscordMessage, *, guild_id: str | int | None) -> str | None:
    """A link that opens the message in Discord, once it exists.

    A channel post needs its guild; a DM lives under ``@me``.
    """
    if row.status != "posted" or row.discord_channel_id is None or row.message_id is None:
        return None
    if row.channel == "discord_dm":
        return f"https://discord.com/channels/@me/{row.discord_channel_id}/{row.message_id}"
    if not guild_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{row.discord_channel_id}/{row.message_id}"


async def emit_changed(session: Any, row: models.DiscordMessage) -> None:
    """Tell the page that shows this subject's messages to refetch.

    Staged on ``session`` like every realtime signal: it goes out when the
    caller commits the status change, and never for a rolled-back one.
    """
    signal = _SUBJECT_SIGNALS.get(row.subject.split(":", 1)[0])
    if signal is None or row.workspace_id is None:
        return
    resource, domain, event_type = signal
    await emit(
        session,
        scope=Scope.workspace(int(row.workspace_id)),
        invalidates=[resource],
        data=DomainEvent(
            domain=domain,
            event_type=event_type,
            payload={"workspace_id": int(row.workspace_id), "change": "discord"},
            durable=False,
        ),
    )
