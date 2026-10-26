"""The tournament consumer of ``tournament.encounter.challonge_push_requested`` (confirmed result -> Challonge).

Every path that leaves a Challonge-linked encounter confirmed stages the request in the transaction that wrote the
result (``settle.enqueue_challonge_push``); this handler makes the external call, so a failure gets the queue's
retry rather than being swallowed inside the result write. A request whose ``result_version`` is not the
encounter's current one was superseded (a reopen or a re-confirmation, which queued its own) and is acked without a
call, as is one for an encounter not linked to a Challonge match. A transient failure -- Challonge unreachable,
timing out, rate-limiting or failing (all the client's 503), a retryable database error -- is requeued; anything
else (a missing participant mapping, Challonge refusing the request) propagates and lands in
``tournament_challonge_push.dlq``. Every failed attempt is also journaled in the Challonge sync log by
``auto_push_on_confirm``. No transaction is open during the HTTP call: ``push_single_result`` commits its reads
first and journals the outcome in a new one.

``ponytail:`` the requeue waits a fixed few seconds in the handler; add a delayed retry queue if Challonge outages
outlast it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import sqlalchemy as sa
from faststream.rabbit import Channel, RabbitRouter
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger
from sqlalchemy.exc import DBAPIError

from shared.core.errors import BaseAPIException
from shared.messaging.config import TOURNAMENT_CHALLONGE_PUSH_QUEUE, TOURNAMENT_EVENTS_EXCHANGE
from shared.models.encounter.encounter import Encounter
from shared.observability import observe_message_processing
from shared.schemas.events import ChallongePushRequestedEvent
from shared.services.challonge_refs import resolve_encounter_challonge
from src.core import db
from src.services.challonge.sync import sync_service
from src.services.encounter.log_evidence_events import is_transient

__all__ = ("PUSHED", "STALE", "UNLINKED", "process_challonge_push", "task_router")

task_router = RabbitRouter()

# Isolated channel, one delivery at a time: a slow or rate-limited Challonge must not occupy the RPC default-channel
# QoS slots, nor be hit by this process with several pushes at once.
_PUSH_CHANNEL = Channel(prefetch_count=1)

#: Seconds a transiently failed delivery is held before its requeue, so a rate-limited Challonge is not hammered.
_REQUEUE_DELAY_SECONDS = 5

PUSHED = "pushed"
STALE = "stale"
UNLINKED = "unlinked"


async def process_challonge_push(data: dict[str, Any]) -> str | None:
    """Push one requested result version; ``None`` when the failure is worth another delivery."""
    event = ChallongePushRequestedEvent.model_validate(data)
    try:
        async with db.async_session_maker() as session:
            version = await session.scalar(
                sa.select(Encounter.result_version).where(Encounter.id == event.encounter_id)
            )
            if version != event.result_version:
                return STALE
            if (await resolve_encounter_challonge(session, [event.encounter_id])).get(event.encounter_id) is None:
                return UNLINKED
            await sync_service.auto_push_on_confirm(session, event.encounter_id)
            return PUSHED
    except (DBAPIError, BaseAPIException) as exc:
        if isinstance(exc, DBAPIError) and not is_transient(exc):
            raise
        # 503 is the client's "Challonge unreachable, rate-limited or failing"; any other refusal is this request's own.
        if isinstance(exc, BaseAPIException) and exc.status_code != 503:
            raise
        logger.warning(f"Challonge push {event.event_id}: {type(exc).__name__}, requeueing")
        return None


@task_router.subscriber(TOURNAMENT_CHALLONGE_PUSH_QUEUE, exchange=TOURNAMENT_EVENTS_EXCHANGE, channel=_PUSH_CHANNEL)
async def consume_challonge_push(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_CHALLONGE_PUSH_QUEUE,
        handler="consume_challonge_push",
        message=msg,
        logger=logger,
    ) as context:
        outcome = await process_challonge_push(data)
        if outcome is None:
            await asyncio.sleep(_REQUEUE_DELAY_SECONDS)
            await msg.nack(requeue=True)
            context.set_status("requeued")
            return
        context.logger.bind(outcome=outcome).info("Challonge push handled")
