"""Swiss helpers retained by parser-stage compatibility paths.

Tournament-service exclusively owns automatic Swiss round scheduling.
"""

from __future__ import annotations

from loguru import logger

from src import models

DEFAULT_STAGE_MAX_ROUNDS = 5


async def enqueue_swiss_next_rounds(session, tournament_id: int) -> list:
    """Compatibility no-op: parser-service never schedules bracket work."""
    del session, tournament_id
    logger.info("Swiss scheduling delegated to tournament-service")
    return []


def stage_max_rounds(stage: models.Stage) -> int:
    raw_value = getattr(stage, "max_rounds", DEFAULT_STAGE_MAX_ROUNDS)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_STAGE_MAX_ROUNDS
    return max(1, value)


def stage_allows_next_round(stage: models.Stage, next_round: int | None) -> bool:
    return next_round is not None and next_round <= stage_max_rounds(stage)
