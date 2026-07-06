"""``AnalyticsJob`` CRUD + status transitions.

State machine::

    pending → running → succeeded | failed

A partial unique index on ``workspace_id WHERE status IN ('pending',
'running')`` enforces "one active job per workspace" at the DB level —
:func:`create_job` translates the constraint violation into an
:class:`ActiveJobConflict`, which the HTTP layer maps to 409.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

__all__ = (
    "JOB_KIND_COMPUTE",
    "JOB_KIND_TRAIN_ML",
    "JOB_KINDS",
    "JOB_STATUS_PENDING",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCEEDED",
    "JOB_STATUS_FAILED",
    "ActiveJobConflict",
    "create_job",
    "get_active_job",
    "get_job",
    "list_jobs",
    "mark_job_running",
    "mark_job_succeeded",
    "mark_job_failed",
    "update_progress",
)


JOB_KIND_COMPUTE = "compute"
JOB_KIND_TRAIN_ML = "train_ml"
JOB_KINDS = (JOB_KIND_COMPUTE, JOB_KIND_TRAIN_ML)

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"


class ActiveJobConflict(RuntimeError):
    """Raised when a job is already pending/running for the workspace."""

    def __init__(self, existing_job_id: int) -> None:
        super().__init__(
            f"An analytics job (id={existing_job_id}) is already pending or "
            f"running for this workspace; wait for it to finish or cancel it."
        )
        self.existing_job_id = existing_job_id


def _progress_has_failed_stage(progress: dict[str, typing.Any] | None) -> bool:
    if not isinstance(progress, dict):
        return False
    return any(isinstance(stage, dict) and stage.get("state") == JOB_STATUS_FAILED for stage in progress.values())


async def _reconcile_failed_active_jobs(
    session: AsyncSession,
    workspace_id: int | None,
) -> None:
    """Repair old stuck jobs whose progress says failed but status stayed active."""
    query = sa.select(models.AnalyticsJob).where(
        models.AnalyticsJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_RUNNING])
    )
    if workspace_id is None:
        query = query.where(models.AnalyticsJob.workspace_id.is_(None))
    else:
        query = query.where(models.AnalyticsJob.workspace_id == workspace_id)
    result = await session.scalars(query)
    repaired = False
    for job in result.all():
        if not _progress_has_failed_stage(job.progress):
            continue
        job.status = JOB_STATUS_FAILED
        job.error = job.error or "Analytics job had failed progress but active status; reconciled automatically."
        job.finished_at = datetime.now(UTC)
        repaired = True
    if repaired:
        await session.flush()
        await session.commit()


async def get_active_job(session: AsyncSession, workspace_id: int | None) -> models.AnalyticsJob | None:
    """Return any ``pending``/``running`` job for ``workspace_id`` (or None)."""
    await _reconcile_failed_active_jobs(session, workspace_id)
    query = sa.select(models.AnalyticsJob).where(
        models.AnalyticsJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_RUNNING])
    )
    if workspace_id is None:
        query = query.where(models.AnalyticsJob.workspace_id.is_(None))
    else:
        query = query.where(models.AnalyticsJob.workspace_id == workspace_id)
    query = query.order_by(models.AnalyticsJob.id.desc()).limit(1)
    return await session.scalar(query)


async def create_job(
    session: AsyncSession,
    *,
    workspace_id: int | None,
    tournament_id: int,
    kind: str,
    algorithms: list[str] | None,
    training_workspace_ids: list[int] | None = None,
    requested_by_user_id: int | None,
) -> models.AnalyticsJob:
    """Insert a new ``pending`` job; raise :class:`ActiveJobConflict` on race."""
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")

    await _reconcile_failed_active_jobs(session, workspace_id)

    job = models.AnalyticsJob(
        workspace_id=workspace_id,
        tournament_id=tournament_id,
        requested_by_user_id=requested_by_user_id,
        kind=kind,
        status=JOB_STATUS_PENDING,
        algorithms=list(algorithms) if algorithms else None,
        training_workspace_ids=(
            sorted({int(workspace_id) for workspace_id in training_workspace_ids})
            if training_workspace_ids is not None
            else None
        ),
        progress={},
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await get_active_job(session, workspace_id)
        raise ActiveJobConflict(existing.id if existing else -1)

    await session.commit()
    return job


async def get_job(session: AsyncSession, job_id: int) -> models.AnalyticsJob | None:
    return await session.scalar(sa.select(models.AnalyticsJob).where(models.AnalyticsJob.id == job_id))


async def list_jobs(
    session: AsyncSession,
    *,
    workspace_id: int | None,
    limit: int = 20,
    active_only: bool = False,
) -> typing.Sequence[models.AnalyticsJob]:
    query = sa.select(models.AnalyticsJob)
    if workspace_id is None:
        query = query.where(models.AnalyticsJob.workspace_id.is_(None))
    else:
        query = query.where(models.AnalyticsJob.workspace_id == workspace_id)
    if active_only:
        query = query.where(models.AnalyticsJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_RUNNING]))
    query = query.order_by(models.AnalyticsJob.id.desc()).limit(int(limit))
    result = await session.scalars(query)
    return result.all()


async def mark_job_running(session: AsyncSession, job_id: int) -> models.AnalyticsJob | None:
    """Flip ``pending → running`` and stamp ``started_at``."""
    job = await get_job(session, job_id)
    if job is None or job.status != JOB_STATUS_PENDING:
        return job
    job.status = JOB_STATUS_RUNNING
    job.started_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    return job


async def mark_job_succeeded(session: AsyncSession, job_id: int) -> models.AnalyticsJob | None:
    job = await get_job(session, job_id)
    if job is None:
        return None
    job.status = JOB_STATUS_SUCCEEDED
    job.finished_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    return job


async def mark_job_failed(session: AsyncSession, job_id: int, *, error: str) -> models.AnalyticsJob | None:
    job = await get_job(session, job_id)
    if job is None:
        return None
    job.status = JOB_STATUS_FAILED
    job.error = error[:4000]  # keep error column manageable
    job.finished_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    return job


async def update_progress(
    session: AsyncSession,
    job_id: int,
    *,
    stage: str,
    state: str,
    detail: dict[str, typing.Any] | None = None,
) -> models.AnalyticsJob | None:
    """Set ``progress[stage] = {"state": state, "detail": ...}`` atomically."""
    job = await get_job(session, job_id)
    if job is None:
        return None
    progress = dict(job.progress or {})
    progress[stage] = {"state": state, "detail": detail or {}}
    job.progress = progress
    await session.flush()
    await session.commit()
    return job
