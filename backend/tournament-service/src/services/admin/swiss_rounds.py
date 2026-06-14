"""Auto-generation of the next Swiss round for a bracket computation job."""

from __future__ import annotations

import sqlalchemy as sa
from loguru import logger
from shared.services.bracket.swiss_settings import swiss_scope_stopped
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.services.admin import stage as stage_service
from src.services.standings import swiss_auto_round


async def generate_next_swiss_round(
    session: AsyncSession,
    *,
    tournament_id: int,
    stage_id: int,
    stage_item_id: int | None,
    expected_next_round: int | None,
) -> list[models.Encounter]:
    """Generate one Swiss round without committing or recalculating standings."""
    stage = await stage_service.get_stage(session, stage_id)

    if not stage.is_active:
        logger.warning(
            "Swiss auto-round: stage is not active, skipping",
            stage_id=stage_id,
        )
        return []
    if swiss_scope_stopped(stage, stage_item_id):
        logger.info(
            "Swiss auto-round: stopped scope skipped",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
        )
        return []

    item: models.StageItem | None = None
    team_ids: list[int] = []

    if stage_item_id is not None:
        item = next((i for i in stage.items if i.id == stage_item_id), None)
        if item is None:
            logger.error(
                "Swiss auto-round: stage item not found",
                stage_item_id=stage_item_id,
            )
            return []
        team_ids = stage_service._collect_item_team_ids(item)
    else:
        for i in stage.items:
            team_ids.extend(stage_service._collect_item_team_ids(i))

    if len(team_ids) < 2:
        logger.warning(
            "Swiss auto-round: not enough teams",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
        )
        return []

    current_encounters = await _get_stage_item_encounters(
        session,
        stage_id,
        stage_item_id,
    )
    actual_next_round = swiss_auto_round.next_round_number(current_encounters)
    if expected_next_round is not None:
        if actual_next_round != expected_next_round:
            logger.info(
                "Swiss auto-round: stale event skipped",
                stage_id=stage_id,
                stage_item_id=stage_item_id,
                event_next_round=expected_next_round,
                expected_next_round=actual_next_round,
            )
            return []

    if not swiss_auto_round.stage_allows_next_round(stage, actual_next_round):
        logger.info(
            "Swiss auto-round: stage max rounds reached, skipping",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            next_round=actual_next_round,
            max_rounds=swiss_auto_round.stage_max_rounds(stage),
        )
        return []

    if not swiss_auto_round.stage_item_ready_for_next_round(current_encounters):
        logger.info(
            "Swiss auto-round: current round is not closed, skipping",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
        )
        return []

    skeleton = await stage_service._generate_stage_skeleton(session, stage, team_ids, stage_item_id)
    if not skeleton.pairings:
        await session.flush()
        logger.info(
            "Swiss auto-round: scope completed because no non-rematch pairing exists",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
        )
        return []

    team_names_by_id = await stage_service._load_team_names(session, team_ids)
    encounters = await stage_service._create_encounters_from_skeleton(
        session,
        stage,
        skeleton,
        stage_item_id,
        team_names_by_id=team_names_by_id,
    )
    await session.flush()

    logger.info(
        "Swiss auto-round: generated %d encounters for round %d",
        len(encounters),
        skeleton.pairings[0].round_number if skeleton.pairings else "?",
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        tournament_id=tournament_id,
    )

    return encounters


async def _get_stage_item_encounters(
    session: AsyncSession,
    stage_id: int,
    stage_item_id: int | None,
) -> list[models.Encounter]:
    query = sa.select(models.Encounter).where(models.Encounter.stage_id == stage_id)
    if stage_item_id is None:
        query = query.where(models.Encounter.stage_item_id.is_(None))
    else:
        query = query.where(models.Encounter.stage_item_id == stage_item_id)

    result = await session.execute(query)
    return list(result.scalars().all())
