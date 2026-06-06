"""Auto-generation of next Swiss round triggered by queue event."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from loguru import logger
from shared.schemas.events import SwissNextRoundEvent
from shared.services.bracket.swiss_settings import swiss_scope_stopped
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import db
from src.services.admin import stage as stage_service
from src.services.standings import service as standings_service
from src.services.standings import swiss_auto_round
from src.services.tournament.cache_invalidation import invalidate_tournament_cache
from src.services.tournament.events import enqueue_tournament_changed


async def process_swiss_next_round_event(
    data: dict[str, Any],
    *,
    session_factory: Any = db.async_session_maker,
) -> None:
    """Handle SwissNextRoundEvent for one Swiss stage item.

    The handler re-checks current DB state before generating. If a newer round
    already exists or the current round is still open, the stale event is ignored.
    """
    event = SwissNextRoundEvent.model_validate(data)
    log = logger.bind(
        stage_id=event.stage_id,
        stage_item_id=event.stage_item_id,
        tournament_id=event.tournament_id,
    )
    log.info("Processing swiss next round event")

    try:
        async with session_factory() as session:
            await _generate_next_round(session, event)
    except Exception:
        log.exception("Failed to generate swiss next round")
        raise


async def _generate_next_round(
    session: AsyncSession,
    event: SwissNextRoundEvent,
) -> list[models.Encounter]:
    stage = await stage_service.get_stage(session, event.stage_id)

    if not stage.is_active:
        logger.warning(
            "Swiss auto-round: stage is not active, skipping",
            stage_id=event.stage_id,
        )
        return []
    if swiss_scope_stopped(stage, event.stage_item_id):
        logger.info(
            "Swiss auto-round: stopped scope skipped",
            stage_id=event.stage_id,
            stage_item_id=event.stage_item_id,
        )
        return []

    item: models.StageItem | None = None
    team_ids: list[int] = []

    if event.stage_item_id is not None:
        item = next((i for i in stage.items if i.id == event.stage_item_id), None)
        if item is None:
            logger.error(
                "Swiss auto-round: stage item not found",
                stage_item_id=event.stage_item_id,
            )
            return []
        team_ids = stage_service._collect_item_team_ids(item)
    else:
        for i in stage.items:
            team_ids.extend(stage_service._collect_item_team_ids(i))

    if len(team_ids) < 2:
        logger.warning(
            "Swiss auto-round: not enough teams",
            stage_id=event.stage_id,
            stage_item_id=event.stage_item_id,
        )
        return []

    current_encounters = await _get_stage_item_encounters(
        session,
        event.stage_id,
        event.stage_item_id,
    )
    expected_next_round = swiss_auto_round.next_round_number(current_encounters)
    if event.next_round is not None:
        if expected_next_round != event.next_round:
            logger.info(
                "Swiss auto-round: stale event skipped",
                stage_id=event.stage_id,
                stage_item_id=event.stage_item_id,
                event_next_round=event.next_round,
                expected_next_round=expected_next_round,
            )
            return []

    if not swiss_auto_round.stage_allows_next_round(stage, expected_next_round):
        logger.info(
            "Swiss auto-round: stage max rounds reached, skipping",
            stage_id=event.stage_id,
            stage_item_id=event.stage_item_id,
            next_round=expected_next_round,
            max_rounds=swiss_auto_round.stage_max_rounds(stage),
        )
        return []

    if not swiss_auto_round.stage_item_ready_for_next_round(current_encounters):
        logger.info(
            "Swiss auto-round: current round is not closed, skipping",
            stage_id=event.stage_id,
            stage_item_id=event.stage_item_id,
        )
        return []

    skeleton = await stage_service._generate_stage_skeleton(session, stage, team_ids, event.stage_item_id)
    if not skeleton.pairings:
        await session.commit()
        await standings_service.recalculate_for_tournament(session, event.tournament_id)
        await enqueue_tournament_changed(session, event.tournament_id, "results_changed")
        await session.commit()
        logger.info(
            "Swiss auto-round: scope completed because no non-rematch pairing exists",
            stage_id=event.stage_id,
            stage_item_id=event.stage_item_id,
        )
        return []

    team_names_by_id = await stage_service._load_team_names(session, team_ids)
    encounters = await stage_service._create_encounters_from_skeleton(
        session,
        stage,
        skeleton,
        event.stage_item_id,
        team_names_by_id=team_names_by_id,
    )
    await enqueue_tournament_changed(session, event.tournament_id, "bracket_changed")
    await session.commit()
    try:
        await invalidate_tournament_cache(event.tournament_id, "bracket_changed")
    except Exception:
        logger.exception(
            "Swiss auto-round: failed to invalidate encounter cache",
            tournament_id=event.tournament_id,
        )

    logger.info(
        "Swiss auto-round: generated %d encounters for round %d",
        len(encounters),
        skeleton.pairings[0].round_number if skeleton.pairings else "?",
        stage_id=event.stage_id,
        stage_item_id=event.stage_item_id,
    )

    await standings_service.recalculate_for_tournament(session, event.tournament_id)
    await enqueue_tournament_changed(session, event.tournament_id, "results_changed")
    await session.commit()

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
