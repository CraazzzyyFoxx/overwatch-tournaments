"""Unified job runner — single entry from the worker.

Dispatches ``AnalyticsJob`` rows by ``kind``:

- ``compute``  → v1 ``recalculate_analytics`` (for shift-producing algorithms)
  + v2 ``run_for_tournament`` (Performance/Shift/Standings/MatchQuality
  inference). Both stages are emit progress events to realtime.
- ``train_ml`` → v2 ``train_all_models`` only. Reserved for superusers because
  this is the heavy stage (gradient-booster fitting).
"""

from __future__ import annotations

import logging
import traceback
import typing

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.analytics import flows as v1_flows
from src.services.ml.inference.runner import run_for_tournament
from src.services.ml.training.orchestrator import train_all_models

from .realtime import publish_job_event
from .service import (
    JOB_KIND_COMPUTE,
    JOB_KIND_TRAIN_ML,
    get_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    update_progress,
)

logger = logging.getLogger(__name__)

__all__ = ("run_job",)


async def _rollback_after_failure(session: AsyncSession) -> None:
    """Reset the SQLAlchemy session so failure status can be persisted.

    DB exceptions leave the async session in a failed transaction state. If we
    try to write ``job.status = failed`` before rollback, the failure handler
    can fail too, leaving the job stuck as active.
    """
    try:
        await session.rollback()
    except Exception:
        logger.exception("Failed to rollback analytics job session after exception")


async def _emit(
    session: AsyncSession,
    redis: Redis | None,
    job,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Persist + broadcast the latest progress snapshot."""
    try:
        await publish_job_event(
            session,
            redis,
            job_id=int(job.id),
            workspace_id=job.workspace_id,
            tournament_id=int(job.tournament_id),
            kind=job.kind,
            status=status,
            progress=dict(job.progress or {}),
            error=error,
            actor_user_id=job.requested_by_user_id,
        )
    except Exception:
        logger.exception("Failed to publish analytics_job realtime event")


async def _run_compute(
    session: AsyncSession,
    redis: Redis | None,
    job,
) -> dict[str, typing.Any]:
    """v1 recalc + v2 inference for ``compute`` jobs."""
    summary: dict[str, typing.Any] = {}
    job_id = int(job.id)
    workspace_id = job.workspace_id
    tournament_id = int(job.tournament_id)

    # --- v1 recalculate (shift-producing algorithms) ---
    await update_progress(session, job_id, stage="v1_recalc", state="running")
    job = await get_job(session, job_id)
    await _emit(session, redis, job, status="running")
    try:
        algos: typing.Iterable[str] | None = (
            list(job.algorithms) if job.algorithms else None
        )
        algorithms = await v1_flows.recalculate_analytics(
            session,
            tournament_id,
            algos,
            workspace_id=workspace_id,
        )
        summary["v1"] = algorithms
        await update_progress(
            session, job_id, stage="v1_recalc", state="done",
            detail={"algorithms": algorithms},
        )
    except Exception as exc:
        logger.exception("v1 recalculate failed")
        await _rollback_after_failure(session)
        await update_progress(
            session, job_id, stage="v1_recalc", state="failed",
            detail={"error": str(exc)},
        )
        raise

    # --- v2 inference (performance + player anomalies + shift + standings + match_quality) ---
    await update_progress(session, job_id, stage="v2_inference", state="running")
    job = await get_job(session, job_id)
    await _emit(session, redis, job, status="running")
    try:
        v2 = await run_for_tournament(
            session,
            tournament_id,
            workspace_id=workspace_id,
        )
        summary["v2"] = v2
        await update_progress(
            session, job_id, stage="v2_inference", state="done", detail=v2
        )
    except Exception as exc:
        logger.exception("v2 inference failed")
        await _rollback_after_failure(session)
        await update_progress(
            session, job_id, stage="v2_inference", state="failed",
            detail={"error": str(exc)},
        )
        raise

    return summary


async def _run_train_ml(
    session: AsyncSession,
    redis: Redis | None,
    job,
) -> dict[str, typing.Any]:
    """v2 ``train_all_models`` only — superuser-only."""
    job_id = int(job.id)
    tournament_id = int(job.tournament_id)
    training_workspace_ids = getattr(job, "training_workspace_ids", None)

    await update_progress(session, job_id, stage="train", state="running")
    job = await get_job(session, job_id)
    await _emit(session, redis, job, status="running")
    model_kinds = list(job.algorithms) if job.algorithms else None
    try:
        summary = await train_all_models(
            session,
            cutoff_tournament_id=tournament_id,
            model_kinds=model_kinds,
            workspace_id=None,
            workspace_ids=training_workspace_ids,
        )
    except Exception as exc:
        logger.exception("ML training failed")
        await _rollback_after_failure(session)
        await update_progress(
            session, job_id, stage="train", state="failed",
            detail={"error": str(exc)},
        )
        raise
    await update_progress(
        session,
        job_id,
        stage="train",
        state="done",
        detail={
            **summary,
            "workspace_scope": training_workspace_ids or "all",
        },
    )
    return {"train": summary}


async def run_job(
    session: AsyncSession,
    redis: Redis | None,
    job_id: int,
) -> None:
    """Single entry point — flips status, dispatches by kind, emits events.

    Any unhandled exception is captured into ``job.error`` and the job is
    flipped to ``failed`` so the UI sees the outcome.
    """
    job = await get_job(session, job_id)
    if job is None:
        logger.warning("Analytics job not found: %d", job_id)
        return
    job_id = int(job.id)

    await mark_job_running(session, job_id)
    job = await get_job(session, job_id)
    await _emit(session, redis, job, status="running")

    try:
        if job.kind == JOB_KIND_TRAIN_ML:
            await _run_train_ml(session, redis, job)
        elif job.kind == JOB_KIND_COMPUTE:
            await _run_compute(session, redis, job)
        else:
            raise RuntimeError(f"unknown job kind: {job.kind!r}")
    except Exception as exc:
        tb = traceback.format_exc(limit=10)
        await _rollback_after_failure(session)
        await mark_job_failed(session, job_id, error=f"{exc}\n{tb}")
        job = await get_job(session, job_id)
        await _emit(session, redis, job, status="failed", error=str(exc))
        return

    await mark_job_succeeded(session, job_id)
    job = await get_job(session, job_id)
    await _emit(session, redis, job, status="succeeded")
