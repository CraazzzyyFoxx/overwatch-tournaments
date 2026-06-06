from __future__ import annotations

from typing import Any

from cashews import cache
from faststream.rabbit.fastapi import RabbitMessage, RabbitRouter
from loguru import logger
from shared.messaging.config import TOURNAMENT_CHANGED_QUEUE, TOURNAMENT_RECALC_EXCHANGE
from shared.observability import observe_message_processing
from shared.schemas.events import TournamentChangedEvent

from src.core import config
from src.services.tournament.realtime_pubsub import publish_tournament_update

task_router = RabbitRouter(config.settings.rabbitmq_url, logger=logger)


async def invalidate_tournament_standings_cache(tournament_id: int) -> None:
    patterns = (
        f"fastapi:*tournaments/{tournament_id}*",
        f"backend:*tournaments/{tournament_id}*",
        f"*tournaments/{tournament_id}*",
        f"fastapi:*tournaments/{tournament_id}/standings*",
        f"backend:*tournaments/{tournament_id}/standings*",
        f"*tournaments/{tournament_id}/standings*",
        f"fastapi:*teams*:{tournament_id}*",
        f"fastapi:*encounters*:{tournament_id}*",
    )
    for pattern in patterns:
        await cache.delete_match(pattern)


async def handle_tournament_changed_event(data: dict[str, Any]) -> None:
    event = TournamentChangedEvent.model_validate(data)
    await invalidate_tournament_standings_cache(event.tournament_id)
    await publish_tournament_update(event.tournament_id, event.reason)


@task_router.subscriber(TOURNAMENT_CHANGED_QUEUE, exchange=TOURNAMENT_RECALC_EXCHANGE)
async def process_tournament_changed(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_CHANGED_QUEUE,
        handler="process_tournament_changed",
        message=msg,
        logger=logger,
    ):
        await handle_tournament_changed_event(data)
