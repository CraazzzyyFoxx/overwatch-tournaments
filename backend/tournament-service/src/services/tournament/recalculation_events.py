from __future__ import annotations

from typing import Any

from faststream.rabbit import Channel, RabbitRouter
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger

from shared.messaging.config import (
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_STANDINGS_INVALIDATED_QUEUE,
)
from shared.observability import observe_message_processing
from shared.schemas.events import TournamentStandingsInvalidatedEvent
from src.core import db
from src.services.computation.jobs import jobs_service

task_router = RabbitRouter()

# Isolated channel: recalculation fan-in must not compete with RPC QoS slots.
_EVENTS_CHANNEL = Channel(prefetch_count=4)


@task_router.subscriber(
    TOURNAMENT_STANDINGS_INVALIDATED_QUEUE, exchange=TOURNAMENT_EVENTS_EXCHANGE, channel=_EVENTS_CHANNEL
)
async def process_standings_invalidated(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_STANDINGS_INVALIDATED_QUEUE,
        handler="process_standings_invalidated",
        message=msg,
        logger=logger,
    ):
        event = TournamentStandingsInvalidatedEvent.model_validate(data)
        async with db.async_session_maker() as session:
            await jobs_service.request_standings_recalculation(session, event.tournament_id)
            await session.commit()
