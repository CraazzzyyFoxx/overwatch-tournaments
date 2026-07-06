"""Auto-generate next Swiss round when all encounters in a stage item finish.

Called from recalculation.py after standings are rebuilt. A Swiss stage can be
temporarily marked completed when the current round is closed but the next
round has not been generated yet, so stage completion is not used as a
candidate filter here.
"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.services.bracket.swiss_settings import swiss_scope_stopped
from shared.services.tournament_utils import (
    completed_encounters_in_finished_rounds,
    has_incomplete_playable_rounds,
)
from src import models
from src.services.computation import jobs as computation_jobs

DEFAULT_STAGE_MAX_ROUNDS = 5


async def enqueue_swiss_next_rounds(
    session: AsyncSession,
    tournament_id: int,
) -> list[models.TournamentComputationJob]:
    """Create bracket jobs for Swiss scopes whose current round is closed."""
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

    requests: list[tuple[int, int | None, int]] = []
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
                    requests.append((stage.id, item.id, next_round))
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
                requests.append((stage.id, None, next_round))

    if not requests:
        return []

    jobs: list[models.TournamentComputationJob] = []
    for stage_id, stage_item_id, next_round in requests:
        job = await computation_jobs.request_bracket_job(
            session,
            tournament_id=tournament_id,
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            operation="generate_next_swiss_round",
            payload={"next_round": next_round},
        )
        jobs.append(job)
        logger.info(
            "Enqueued Swiss next round bracket job",
            job_id=job.id,
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            tournament_id=tournament_id,
            next_round=next_round,
        )
    return jobs


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
