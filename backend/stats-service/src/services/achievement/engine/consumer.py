"""RabbitMQ consumers for AchievementEvaluateEvent."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.models.achievements.achievement import AchievementEvalMode, EvaluationRunTrigger
from shared.observability.correlation import correlation_id_ctx
from shared.schemas.events import AchievementEvaluateEvent, AchievementEvaluateReason
from src.core import db

from .runner import resume_queued_run, run_evaluation


def plan_evaluation(
    mode: AchievementEvalMode,
    reason: AchievementEvaluateReason,
    changed_tables: list[str],
    tournament_finished: bool,
) -> tuple[bool, list[str] | None]:
    """Whether an automatic event runs under the workspace's mode, and the tables it narrows the rules to (None: all)."""
    if mode == AchievementEvalMode.manual:
        return False, None
    if mode == AchievementEvalMode.live:
        # Every change already ran as it came; a stage completion brings no data of its own.
        return reason != "stage_completed", changed_tables
    if reason != "data_changed":
        # A whole stage of changes piled up unrun: every rule over the tournament.
        return True, None
    # After the finish nothing waits for a completion any more: a late log or a correction runs at once.
    return tournament_finished, changed_tables


async def _workspace_mode(session: AsyncSession, workspace_id: int) -> AchievementEvalMode:
    mode = await session.scalar(
        sa.select(models.Workspace.achievement_eval_mode).where(models.Workspace.id == workspace_id)
    )
    # A missing workspace keeps today's path: the runner reports it.
    return AchievementEvalMode(mode or AchievementEvalMode.live)


async def _tournament_finished(session: AsyncSession, tournament_id: int | None) -> bool:
    if tournament_id is None:
        return False
    return bool(
        await session.scalar(sa.select(models.Tournament.is_finished).where(models.Tournament.id == tournament_id))
    )


async def handle_achievement_evaluate(data: dict) -> None:
    """Process an AchievementEvaluateEvent from the queue, as the workspace's ``achievement_eval_mode`` allows."""
    correlation_id_ctx.set(str(uuid.uuid4()))
    event = AchievementEvaluateEvent.model_validate(data)
    log = logger.bind(workspace_id=event.workspace_id, tournament_id=event.tournament_id, reason=event.reason)

    # Don't log failures here: run_evaluation already logs the traceback with the
    # run id before re-raising, and FastStream logs it again through its logger
    # proxy. The exception propagates untouched and FastStream rejects the message
    # (AckPolicy.REJECT_ON_ERROR, requeue=False) straight into achievement_evaluate.dlq.
    async with db.async_session_maker() as session:
        mode = await _workspace_mode(session, event.workspace_id)
        finished = mode == AchievementEvalMode.stage_end and await _tournament_finished(session, event.tournament_id)
        run, changed_tables = plan_evaluation(mode, event.reason, event.changed_tables, finished)
        if not run:
            log.info(f"Achievement evaluation skipped: workspace mode is {mode.value}")
            return
        log.info("Processing achievement evaluation from queue")
        await run_evaluation(
            session=session,
            workspace_id=event.workspace_id,
            trigger=EvaluationRunTrigger.parse_complete,
            tournament_id=event.tournament_id,
            changed_tables=changed_tables,
        )


async def handle_achievement_evaluate_deferred(data: dict) -> None:
    """Run an evaluation that the tier gate parked on the deferred queue.

    Resumes the ``queued`` run row the caller was already handed instead of
    calling ``run_evaluation`` again — that would re-check the tier and re-queue
    the same workspace forever.
    """
    correlation_id_ctx.set(str(uuid.uuid4()))
    event = AchievementEvaluateEvent.model_validate(data)
    logger.bind(
        workspace_id=event.workspace_id,
        run_id=event.run_id,
    ).info("Processing deferred achievement evaluation from queue")

    async with db.async_session_maker() as session:
        await resume_queued_run(session, event)
