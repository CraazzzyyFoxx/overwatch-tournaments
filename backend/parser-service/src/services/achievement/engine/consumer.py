"""RabbitMQ consumer for AchievementEvaluateEvent.

This module provides the subscriber handler that should be registered
on the parser-service worker's broker.
"""

from __future__ import annotations

import uuid

from loguru import logger
from shared.models.achievement import EvaluationRunTrigger
from shared.observability.correlation import correlation_id_ctx
from shared.schemas.events import AchievementEvaluateEvent

from src.core import db

from .runner import run_evaluation


async def handle_achievement_evaluate(data: dict) -> None:
    """Process an AchievementEvaluateEvent from the queue."""
    correlation_id_ctx.set(str(uuid.uuid4()))
    event = AchievementEvaluateEvent.model_validate(data)
    logger.bind(
        workspace_id=event.workspace_id,
        tournament_id=event.tournament_id,
    ).info("Processing achievement evaluation from queue")

    try:
        async with db.async_session_maker() as session:
            await run_evaluation(
                session=session,
                workspace_id=event.workspace_id,
                trigger=EvaluationRunTrigger.parse_complete,
                tournament_id=event.tournament_id,
                changed_tables=event.changed_tables,
            )
    except Exception:
        logger.exception(
            f"Failed to evaluate achievements for "
            f"workspace_id={event.workspace_id} tournament_id={event.tournament_id}"
        )
        raise
