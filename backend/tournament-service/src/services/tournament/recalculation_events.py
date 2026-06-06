from __future__ import annotations

from typing import Any

from faststream.rabbit.fastapi import RabbitMessage, RabbitRouter
from loguru import logger
from shared.messaging.config import (
    TOURNAMENT_CHANGED_TOURNAMENT_QUEUE,
    TOURNAMENT_RECALC_EXCHANGE,
)
from shared.observability import observe_message_processing
from shared.schemas.events import TournamentChangedEvent

from src.core import config
from src.services.tournament.cache_invalidation import invalidate_tournament_cache
from src.services.tournament.realtime_pubsub import publish_tournament_update

task_router = RabbitRouter(config.settings.rabbitmq_url, logger=logger)


async def handle_tournament_changed_event(data: dict[str, Any]) -> None:
    event = TournamentChangedEvent.model_validate(data)
    await invalidate_tournament_cache(event.tournament_id, event.reason)
    await publish_tournament_update(event.tournament_id, event.reason)


@task_router.subscriber(TOURNAMENT_CHANGED_TOURNAMENT_QUEUE, exchange=TOURNAMENT_RECALC_EXCHANGE)
async def process_tournament_changed(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_CHANGED_TOURNAMENT_QUEUE,
        handler="process_tournament_changed",
        message=msg,
        logger=logger,
    ):
        await handle_tournament_changed_event(data)
