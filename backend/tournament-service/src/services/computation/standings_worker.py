from __future__ import annotations

import sqlalchemy as sa
from faststream.exceptions import RejectMessage
from loguru import logger

from shared import models
from shared.messaging.config import ACHIEVEMENT_EVALUATE_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.repository import TournamentRepository
from shared.schemas.events import AchievementEvaluateEvent
from shared.services.scrim_scope import is_scrim_container
from shared.services.tournament.computation import dispatch_job
from src.core import db
from src.services.admin.stage import stage_service as admin_stage_service
from src.services.computation.jobs import failure_message, is_refusal, jobs_service
from src.services.standings.service import standings_service
from src.services.standings.swiss_auto_round import swiss_rounds_service
from src.services.tournament.events import (
    RESULT_RESOURCES,
    STRUCTURE_RESOURCES,
    publish_tournament_invalidation,
)

_tournaments = TournamentRepository()

# Standings are the input to every placement-, streak- and playoff-shaped rule.
# The outbox row goes out in the same transaction as the standings themselves,
# so the evaluation can never observe an older generation than the one that
# triggered it. The same job flips ``Stage.is_completed``, which the
# stage-completion rules read.
_STANDINGS_CHANGED_TABLES = ["tournament.standing", "tournament.player", "tournament.team", "tournament.stage"]


async def _enqueue_achievement_evaluation(session, tournament: models.Tournament) -> None:
    if await is_scrim_container(session, tournament.id):
        return
    await enqueue_outbox_event(
        session,
        AchievementEvaluateEvent(
            workspace_id=tournament.workspace_id,
            tournament_id=tournament.id,
            changed_tables=_STANDINGS_CHANGED_TABLES,
        ),
        # Default exchange: the routing key IS the queue name.
        exchange=None,
        routing_key=ACHIEVEMENT_EVALUATE_QUEUE.name,
    )


async def _isolated(session, what: str, tournament_id: int, step):
    """Run ``step`` in a savepoint; ``None`` when it failed.

    Requalification and Swiss round generation ride on the standings but must not decide them: a refusal there (a
    seat already taken, an unknown role) would otherwise roll the standings back and fail the job, and the next
    result would hit the same refusal -- the table frozen for good. Logged instead, the standings commit.
    """
    try:
        async with session.begin_nested():
            return await step()
    except Exception as exc:
        if is_refusal(exc):
            logger.warning("{} refused: {}", what, failure_message(exc), tournament_id=tournament_id)
        else:
            logger.exception("{} failed", what, tournament_id=tournament_id)
        return None


async def _requeue_contended_job(session, job: models.TournamentComputationJob) -> None:
    """Hand a lock-contended job back to the queue as if it had never run.

    ``claim_job`` already spent an attempt on this delivery; losing the race for
    the tournament row is not a failed attempt, so it is given back — otherwise
    MAX_ATTEMPTS contended deliveries would mark the job failed and the
    standings would never be recomputed.
    """
    job.status = "pending"
    job.started_at = None
    job.error = None
    job.attempts = max(0, int(job.attempts) - 1)
    await dispatch_job(session, job)
    await session.commit()


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
            # SKIP LOCKED, not a plain wait: whoever else is writing this
            # tournament (a bracket job, an admin transition) holds this row for
            # its whole transaction, and waiting burns the full statement_timeout
            # AND one of the three attempts — three contended passes would
            # leave the standings permanently stale. The outbox drains every
            # second, so handing the job back costs a tick.
            locked = await _tournaments.lock_for_computation(session, current.tournament_id, skip_locked=True)
            if locked is None:
                # SKIP LOCKED cannot tell "held by another writer" from "row is
                # gone", and a deleted tournament must not requeue forever; it
                # falls through to the recalculation instead.
                # ponytail: requeues are unbounded, add a backoff if a stuck
                # lock ever spins a job.
                still_exists = await session.scalar(
                    sa.select(models.Tournament.id).where(models.Tournament.id == current.tournament_id)
                )
                if still_exists is not None:
                    await _requeue_contended_job(session, current)
                    return
            tournament_id = current.tournament_id
            # Read before ranking, not taken from the payload: every request counted here committed together with
            # its data, so the ranking below sees all of them -- ten results queued behind one job are one recompute.
            generation = int(
                await session.scalar(
                    sa.select(models.TournamentRecalculationState.requested_generation).where(
                        models.TournamentRecalculationState.tournament_id == tournament_id
                    )
                )
                or 0
            )
            run = await standings_service.recalculate_for_tournament(session, tournament_id, commit=False)
            requalified = generated = None
            if run.tournament is not None:
                stages = run.tournament.stages
                # The standings that just moved are what a frozen playoff seed was
                # resolved FROM: re-resolve the ones an untouched downstream stage
                # item still holds, in this transaction, before anything publishes.
                requalified = await _isolated(
                    session,
                    "Requalification",
                    tournament_id,
                    lambda: admin_stage_service.requalify_downstream_inputs(session, tournament_id, stages=stages),
                )
                # What was loaded for the ranking is reused unless requalification moved seats or rolled back (a
                # rolled-back savepoint expires what it touched): then the Swiss pass reads its own.
                reuse = requalified == 0
                generated = await _isolated(
                    session,
                    "Swiss round generation",
                    tournament_id,
                    lambda: swiss_rounds_service.generate_ready_rounds(
                        session,
                        tournament_id,
                        stages=stages if reuse else None,
                        encounters=run.encounters if reuse else None,
                    ),
                )
            # Nothing moved, nothing to announce: no refetch storm and no achievement run for an identical table.
            if generated:
                # A generated round is a new bracket section, not just new numbers.
                await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
            elif run.changed or requalified:
                await publish_tournament_invalidation(session, tournament_id, RESULT_RESOURCES)
            if run.changed:
                await _enqueue_achievement_evaluation(session, run.tournament)
            await jobs_service.mark_job_succeeded(
                session,
                current,
                {
                    "generation": generation,
                    "standing_count": len(run.standings),
                },
            )
            await session.flush()
            # Last, right before the commit: every result write upserts this row, so locking it any earlier made
            # those writes wait out the requalification, the Swiss round and its notifications.
            state = await jobs_service.complete_standings_generation(session, tournament_id, generation)
            if state.requested_generation > state.completed_generation:
                await jobs_service.request_followup_standings_job(session, tournament_id)
            await session.commit()
    except Exception as exc:
        if is_refusal(exc):
            logger.info("Standings computation job refused: {}", failure_message(exc), job_id=job_id)
        else:
            logger.exception("Standings computation job failed", job_id=job_id)
        async with db.async_session_maker() as session:
            disposition = await jobs_service.mark_job_failed(session, job_id, exc)
        if disposition == "failed":
            raise RejectMessage() from exc
