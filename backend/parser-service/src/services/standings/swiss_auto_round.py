"""Auto-generate next Swiss round when all encounters in a stage item finish.

Called from recalculation.py after standings are rebuilt. A Swiss stage can be
temporarily marked completed when the current round is closed but the next
round has not been generated yet, so stage completion is not used as a
candidate filter here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from loguru import logger
from shared.core import enums
from shared.messaging.config import SWISS_NEXT_ROUND_QUEUE
from shared.observability import publish_message
from shared.schemas.events import SwissNextRoundEvent
from shared.services.bracket.swiss_settings import swiss_scope_stopped
from shared.services.tournament_utils import (
    completed_encounters_in_finished_rounds,
    has_incomplete_playable_rounds,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models

DEFAULT_STAGE_MAX_ROUNDS = 5


async def enqueue_swiss_next_rounds(
    session: AsyncSession,
    tournament_id: int,
    *,
    broker: Any | None = None,
) -> list[SwissNextRoundEvent]:
    """Queue Swiss next rounds only when the current playable round is closed."""
    result = await session.execute(
        sa.select(models.Stage)
        .where(
            models.Stage.tournament_id == tournament_id,
            models.Stage.stage_type == enums.StageType.SWISS,
            models.Stage.is_active == True,  # noqa: E712
        )
        .options(selectinload(models.Stage.items))
    )
    swiss_stages = result.scalars().all()
    if not swiss_stages:
        return []

    stage_ids = [stage.id for stage in swiss_stages]
    encounters_result = await session.execute(
        sa.select(models.Encounter).where(models.Encounter.stage_id.in_(stage_ids))
    )
    encounters_by_key: dict[tuple[int, int | None], list[models.Encounter]] = defaultdict(list)
    for encounter in encounters_result.scalars().all():
        encounters_by_key[(encounter.stage_id, encounter.stage_item_id)].append(encounter)

    events: list[SwissNextRoundEvent] = []
    for stage in swiss_stages:
        items = stage.items or []
        if items:
            for item in items:
                item_encounters = encounters_by_key.get((stage.id, item.id), [])
                if swiss_scope_stopped(stage, item.id):
                    continue
                if stage_item_ready_for_next_round(item_encounters):
                    next_round = next_round_number(item_encounters)
                    if not stage_allows_next_round(stage, next_round):
                        logger.info(
                            "Swiss auto-round: stage max rounds reached",
                            stage_id=stage.id,
                            stage_item_id=item.id,
                            next_round=next_round,
                            max_rounds=stage_max_rounds(stage),
                        )
                        continue
                    events.append(
                        SwissNextRoundEvent(
                            stage_id=stage.id,
                            stage_item_id=item.id,
                            tournament_id=tournament_id,
                            next_round=next_round,
                        )
                    )
        else:
            stage_encounters = encounters_by_key.get((stage.id, None), [])
            if swiss_scope_stopped(stage, None):
                continue
            if stage_item_ready_for_next_round(stage_encounters):
                next_round = next_round_number(stage_encounters)
                if not stage_allows_next_round(stage, next_round):
                    logger.info(
                        "Swiss auto-round: stage max rounds reached",
                        stage_id=stage.id,
                        stage_item_id=None,
                        next_round=next_round,
                        max_rounds=stage_max_rounds(stage),
                    )
                    continue
                events.append(
                    SwissNextRoundEvent(
                        stage_id=stage.id,
                        stage_item_id=None,
                        tournament_id=tournament_id,
                        next_round=next_round,
                    )
                )

    if not events:
        return []

    if broker is None:
        logger.warning(
            "swiss_auto_round: no broker available, skipping enqueue",
            tournament_id=tournament_id,
        )
        return []

    for event in events:
        try:
            await publish_message(
                broker,
                event.model_dump(),
                SWISS_NEXT_ROUND_QUEUE,
                logger=logger.bind(
                    stage_id=event.stage_id,
                    stage_item_id=event.stage_item_id,
                    tournament_id=tournament_id,
                ),
            )
            logger.info(
                "Enqueued swiss next round",
                stage_id=event.stage_id,
                stage_item_id=event.stage_item_id,
                tournament_id=tournament_id,
            )
        except Exception:
            logger.exception(
                "Failed to enqueue swiss next round",
                stage_id=event.stage_id,
                stage_item_id=event.stage_item_id,
            )

    return events


def stage_item_ready_for_next_round(
    encounters: list[models.Encounter],
) -> bool:
    if not encounters:
        return False
    if has_incomplete_playable_rounds(encounters):
        return False
    return bool(completed_encounters_in_finished_rounds(encounters))


def _stage_item_ready_for_next_round(
    encounters: list[models.Encounter],
) -> bool:
    return stage_item_ready_for_next_round(encounters)


def next_round_number(encounters: list[models.Encounter]) -> int | None:
    rounds = [encounter.round for encounter in encounters if encounter.round is not None]
    if not rounds:
        return None
    return max(rounds) + 1


def stage_max_rounds(stage: models.Stage) -> int:
    raw_value = getattr(stage, "max_rounds", DEFAULT_STAGE_MAX_ROUNDS)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_STAGE_MAX_ROUNDS
    return max(1, value)


def stage_allows_next_round(stage: models.Stage, next_round: int | None) -> bool:
    return next_round is not None and next_round <= stage_max_rounds(stage)
