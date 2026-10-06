"""The signup card as a projection of ``PickupMixChangedEvent``.

No mutation knows about Discord: a mix write emits the fact
(``emit_pickup_mix_changed``), the outbox hands it to ``pickup_mix_changed``,
and this consumer re-renders whatever live signup card the fact affects from
the database as it stands NOW. A redelivered, late or duplicated event is
therefore harmless -- it renders the same state twice.

Ordering is the row lock, not the queue. ``get_for_update`` on the
``discord_message`` row serializes everyone projecting that card, so the
render that reads the roster last is the one that writes ``card_json`` last and
queues its edit last. The bot coalesces edits by ``message_ref`` and shows the
row's card at flush, so a burst of Join clicks converges on the newest roster
whatever order RabbitMQ delivered them in.

An event naming one mix touches that mix's newest live card (an older live row
is only ever on its way out); an event with no mix -- a renamed player, a
corrected rank -- touches the newest live card of every mix in the workspace,
because every one of them shows that name.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import Channel, RabbitMessage

from shared.messaging.config import PICKUP_MIX_CHANGED_QUEUE
from shared.observability import observe_message_processing
from shared.repository.discord_message import LIVE_STATUSES
from shared.schemas.events import PickupMixChangedEvent
from shared.services import discord_messages
from src.core import db
from src.core.config import config
from src.services.custom_game import SIGNUP_SLOT, custom_game_service, mix_subject

__all__ = ("project", "register")

_SUBJECT_PREFIX = "mix:"

# Its own channel, like the jobs consumer's: a workspace-wide event re-renders
# one card per mix, which must not eat the RPC channel's QoS window.
_PROJECTION_CHANNEL = Channel(prefetch_count=4)


def _mix_id(subject: str) -> int | None:
    """``mix:42`` -> ``42``; ``None`` for anything else filed under the slot."""
    if not subject.startswith(_SUBJECT_PREFIX):
        return None
    try:
        return int(subject[len(_SUBJECT_PREFIX) :])
    except ValueError:
        return None


async def _targets(session: Any, event: PickupMixChangedEvent) -> list[Any]:
    """The live signup rows this event re-renders: newest per mix."""
    if event.custom_game_id is not None:
        rows = await discord_messages.repository.for_subject(
            session, mix_subject(event.custom_game_id), slot=SIGNUP_SLOT, statuses=LIVE_STATUSES
        )
        return rows[-1:]
    rows = await discord_messages.repository.live_for_workspace(
        session, event.workspace_id, subject_prefix=_SUBJECT_PREFIX, slot=SIGNUP_SLOT
    )
    # Oldest first, so the last row of each subject is that mix's current card.
    return list({row.subject: row for row in rows}.values())


async def project(session: Any, event: PickupMixChangedEvent) -> int:
    """Re-render every signup card this event affects; returns how many.

    Commits once at the end: the whole projection -- the ``card_json`` writes
    and the edit commands that tell the bot to re-read them -- is one
    transaction, so a failure queues nothing and the message is retried whole.
    """
    rendered = 0
    for row in await _targets(session, event):
        locked = await discord_messages.repository.get_for_update(session, row.id)
        # Deleted or failed between the read and the lock: it is not a card any
        # more, and editing it would resurrect nothing.
        if locked is None or locked.status not in LIVE_STATUSES:
            continue
        custom_game_id = _mix_id(locked.subject)
        if custom_game_id is None:
            continue
        game = await custom_game_service.games.get(session, custom_game_id)
        # Hard-deleted mix: its rows are on their way out with it.
        if game is None:
            continue
        card = await custom_game_service.signup_card_for(session, game, board_url_base=config.public_site_url)
        command = await discord_messages.edit_command(session, locked, card)
        if command is not None:
            await discord_messages.enqueue(session, [command])
            rendered += 1
    await session.commit()
    return rendered


def register(broker: Any, logger: Any) -> None:
    # `msg` MUST be annotated RabbitMessage -- with a looser annotation
    # FastStream treats it as another payload field and every message fails
    # validation straight into the DLQ.
    @broker.subscriber(PICKUP_MIX_CHANGED_QUEUE, channel=_PROJECTION_CHANNEL)
    async def project_signup_cards(data: dict[str, Any], msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=PICKUP_MIX_CHANGED_QUEUE,
            handler="project_signup_cards",
            message=msg,
            logger=logger,
        ):
            event = PickupMixChangedEvent.model_validate(data)
            async with db.async_session_maker() as session:
                await project(session, event)
