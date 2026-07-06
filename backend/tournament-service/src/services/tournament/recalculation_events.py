from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitRouter
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger

from shared.messaging.config import (
    TOURNAMENT_CHANGED_EXCHANGE,
    TOURNAMENT_CHANGED_TOURNAMENT_QUEUE,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_STANDINGS_INVALIDATED_QUEUE,
)
from shared.observability import observe_message_processing
from shared.schemas.events import TournamentChangedEvent, TournamentStandingsInvalidatedEvent
from src.core import db
from src.services.computation.jobs import request_standings_recalculation
from src.services.tournament.cache_invalidation import invalidate_tournament_cache
from src.services.tournament.realtime_pubsub import publish_tournament_update

task_router = RabbitRouter()


async def handle_tournament_changed_event(data: dict[str, Any]) -> None:
    event = TournamentChangedEvent.model_validate(data)
    await invalidate_tournament_cache(event.tournament_id, event.reason)
    await publish_tournament_update(event.tournament_id, event.reason)


@task_router.subscriber(TOURNAMENT_CHANGED_TOURNAMENT_QUEUE, exchange=TOURNAMENT_CHANGED_EXCHANGE)
async def process_tournament_changed(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_CHANGED_TOURNAMENT_QUEUE,
        handler="process_tournament_changed",
        message=msg,
        logger=logger,
    ):
        await handle_tournament_changed_event(data)


@task_router.subscriber(TOURNAMENT_STANDINGS_INVALIDATED_QUEUE, exchange=TOURNAMENT_EVENTS_EXCHANGE)
async def process_standings_invalidated(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_STANDINGS_INVALIDATED_QUEUE,
        handler="process_standings_invalidated",
        message=msg,
        logger=logger,
    ):
        event = TournamentStandingsInvalidatedEvent.model_validate(data)
        async with db.async_session_maker() as session:
            await request_standings_recalculation(session, event.tournament_id)
            await session.commit()
