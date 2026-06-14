from __future__ import annotations

from typing import Any

from faststream.rabbit.fastapi import RabbitRouter
from loguru import logger
from shared.messaging.config import (
    TOURNAMENT_CHANGED_EXCHANGE,
    TOURNAMENT_CHANGED_QUEUE,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_STANDINGS_INVALIDATED_QUEUE,
)
from shared.observability import publish_message
from shared.schemas.events import (
    TournamentChangedEvent,
    TournamentChangedReason,
    TournamentStandingsInvalidatedEvent,
)

from src.core import config

task_router = RabbitRouter(config.settings.rabbitmq_url, logger=logger)


async def close_redis() -> None:
    """Compatibility no-op: recalculation locks are now durable in tournament-service."""


async def enqueue_tournament_recalculation(
    tournament_id: int,
    *,
    broker: Any | None = None,
    redis: Any | None = None,
) -> bool:
    del redis
    event = TournamentStandingsInvalidatedEvent(
        tournament_id=tournament_id,
        source_service="parser-service",
    )
    await publish_message(
        broker or task_router.broker,
        event.model_dump(),
        TOURNAMENT_STANDINGS_INVALIDATED_QUEUE,
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.standings.invalidated",
        logger=logger.bind(tournament_id=tournament_id),
    )
    return True


async def publish_tournament_changed(
    tournament_id: int,
    reason: TournamentChangedReason,
    *,
    broker: Any | None = None,
) -> None:
    event = TournamentChangedEvent(
        tournament_id=tournament_id,
        reason=reason,
        source_service="parser-service",
    )
    await publish_message(
        broker or task_router.broker,
        event.model_dump(),
        TOURNAMENT_CHANGED_QUEUE,
        exchange=TOURNAMENT_CHANGED_EXCHANGE,
        routing_key=f"tournament.changed.{tournament_id}",
        logger=logger.bind(tournament_id=tournament_id, reason=reason),
    )
