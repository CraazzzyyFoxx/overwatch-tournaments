from __future__ import annotations

from typing import Any

from cashews import cache
from faststream.rabbit.fastapi import RabbitMessage, RabbitRouter
from loguru import logger
from shared.messaging.config import TOURNAMENT_CHANGED_APP_QUEUE, TOURNAMENT_CHANGED_EXCHANGE
from shared.observability import observe_message_processing
from shared.schemas.events import TournamentChangedEvent

from src.core import config

task_router = RabbitRouter(config.settings.rabbitmq_url, logger=logger)


async def invalidate_tournament_standings_cache(tournament_id: int) -> None:
    patterns = (
        f"fastapi:*tournaments/{tournament_id}*",
        f"backend:*tournaments/{tournament_id}*",
        f"*tournaments/{tournament_id}*",
        f"fastapi:*tournaments/{tournament_id}/standings*",
        f"backend:*tournaments/{tournament_id}/standings*",
        f"*tournaments/{tournament_id}/standings*",
        # User-scoped flow caches aggregate across tournaments — we don't know
        # which users touched this tournament, so invalidate them broadly.
        # TTL is short (users_cache_ttl=60s) so the steady-state cost is low.
        "backend:user_profile:*",
        "backend:user_tournaments:*",
    )
    for pattern in patterns:
        await cache.delete_match(pattern)


async def handle_tournament_changed_event(data: dict[str, Any]) -> None:
    event = TournamentChangedEvent.model_validate(data)
    if event.reason == "bracket_changed":
        return
    await invalidate_tournament_standings_cache(event.tournament_id)


@task_router.subscriber(TOURNAMENT_CHANGED_APP_QUEUE, exchange=TOURNAMENT_CHANGED_EXCHANGE)
async def process_tournament_changed(data: dict[str, Any], msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_CHANGED_APP_QUEUE,
        handler="process_tournament_changed",
        message=msg,
        logger=logger,
    ):
        await handle_tournament_changed_event(data)
