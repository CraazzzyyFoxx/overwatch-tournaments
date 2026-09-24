from __future__ import annotations

import sqlalchemy as sa
from faststream.exceptions import RejectMessage
from loguru import logger

from shared.messaging.config import ACHIEVEMENT_EVALUATE_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import AchievementEvaluateEvent
from shared.services.scrim_scope import is_scrim_container
from src import models
from src.core import db
from src.services.admin.stage import stage_service as admin_stage_service
from src.services.computation.jobs import failure_message, jobs_service
from src.services.standings.service import standings_service
from src.services.standings.swiss_auto_round import swiss_rounds_service
from src.services.tournament.events import (
    RESULT_RESOURCES,
    STRUCTURE_RESOURCES,
    publish_tournament_invalidation,
)

# Standings are the input to every placement-, streak- and playoff-shaped rule.
# Those rules used to be re-evaluated only by events that fire BEFORE this job
# writes its generation, so they read the previous standings or were skipped by
# the dependency filter entirely (review 2026-09-16 §1.6). The outbox row goes
# out in the same transaction as the standings themselves, so the evaluation can
# never observe an older generation than the one that triggered it.
_STANDINGS_CHANGED_TABLES = ["tournament.standing", "tournament.player", "tournament.team"]


async def _enqueue_achievement_evaluation(session, tournament_id: int) -> None:
    if await is_scrim_container(session, tournament_id):
        return
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        return
    await enqueue_outbox_event(
        session,
        AchievementEvaluateEvent(
            workspace_id=workspace_id,
            tournament_id=tournament_id,
            changed_tables=_STANDINGS_CHANGED_TABLES,
        ),
        # Default exchange: the routing key IS the queue name.
        exchange=None,
        routing_key=ACHIEVEMENT_EVALUATE_QUEUE.name,
    )


async def process_standings_job(job_id: int) -> None:
    async with db.async_session_maker() as session:
        job = await jobs_service.claim_job(session, job_id, kind="standings")
    if job is None:
        return

    try:
        async with db.async_session_maker() as session:
            current = await jobs_service.get_job(session, job_id, for_update=True)
            if current is None or current.status != "running":
                return
            await session.scalar(
                sa.select(models.Tournament.id).where(models.Tournament.id == current.tournament_id).with_for_update()
            )
            generation = int((current.payload_json or {}).get("generation", 0))
            standings = await standings_service.recalculate_for_tournament(
                session,
                current.tournament_id,
                commit=False,
            )
            state = await jobs_service.complete_standings_generation(session, current.tournament_id, generation)
            # The standings that just moved are what a frozen playoff seed was
            # resolved FROM: re-resolve the ones an untouched downstream stage
            # item still holds, in this transaction, before anything publishes.
            await admin_stage_service.requalify_downstream_inputs(session, current.tournament_id)
            generated = await swiss_rounds_service.generate_ready_rounds(session, current.tournament_id)
            # A generated round is a new bracket section, not just new numbers.
            resources = STRUCTURE_RESOURCES if generated else RESULT_RESOURCES
            await publish_tournament_invalidation(session, current.tournament_id, resources)
            await _enqueue_achievement_evaluation(session, current.tournament_id)
            await jobs_service.mark_job_succeeded(
                session,
                current,
                {
                    "generation": generation,
                    "standing_count": len(standings),
                },
            )
            await session.flush()
            if state.requested_generation > state.completed_generation:
                await jobs_service.request_followup_standings_job(session, current.tournament_id)
            await session.commit()
    except Exception as exc:
        logger.exception("Standings computation job failed", job_id=job_id)
        async with db.async_session_maker() as session:
            disposition = await jobs_service.mark_job_failed(session, job_id, failure_message(exc))
        if disposition == "failed":
            raise RejectMessage() from exc
