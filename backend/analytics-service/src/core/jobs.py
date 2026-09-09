"""Analytics wiring for ``shared.jobs.JobService``.

Kind check, failed-stage reconcile, and stage-progress JSON stay here.
Lifecycle create/get/list/mark lives on ``job_runtime``.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from shared.jobs import JobConflict, JobService, JobSpec, OneActive, OrmJobStore, Status
from shared.repository import AnalyticsJobRepository
from src import models
from src.worker.job_realtime import emit_job_event

__all__ = (
    "JOB_KIND_COMPUTE",
    "JOB_KIND_TRAIN_ML",
    "JOB_KINDS",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_PENDING",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCEEDED",
    "create_analytics_job",
    "get_active_job",
    "job_runtime",
    "reconcile_failed_active_jobs",
    "update_progress",
)

JOB_KIND_COMPUTE = "compute"
JOB_KIND_TRAIN_ML = "train_ml"
JOB_KINDS = (JOB_KIND_COMPUTE, JOB_KIND_TRAIN_ML)

JOB_STATUS_PENDING = Status.PENDING
JOB_STATUS_RUNNING = Status.RUNNING
JOB_STATUS_SUCCEEDED = Status.SUCCEEDED
JOB_STATUS_FAILED = Status.FAILED

_ACTIVE = (Status.PENDING, Status.RUNNING)

_repo = AnalyticsJobRepository()
job_runtime: JobService = JobService(
    store=OrmJobStore(
        repo=_repo,
        model=models.AnalyticsJob,
        created_status=Status.PENDING,
        active_statuses=_ACTIVE,
    ),
    concurrency=OneActive(),
)


def _progress_has_failed_stage(progress: dict[str, typing.Any] | None) -> bool:
    if not isinstance(progress, dict):
        return False
    return any(isinstance(stage, dict) and stage.get("state") == JOB_STATUS_FAILED for stage in progress.values())


async def reconcile_failed_active_jobs(session: AsyncSession, workspace_id: int | None) -> None:
    active = await _repo.list_active(session, workspace_id, _ACTIVE)
    repaired = False
    for job in active:
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
    await reconcile_failed_active_jobs(session, workspace_id)
    return await job_runtime.get_active(session, workspace_id)


async def create_analytics_job(
    session: AsyncSession,
    *,
    workspace_id: int | None,
    tournament_id: int,
    kind: str,
    algorithms: list[str] | None,
    training_workspace_ids: list[int] | None = None,
    requested_by_user_id: int | None,
) -> models.AnalyticsJob:
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")
    await reconcile_failed_active_jobs(session, workspace_id)
    spec = JobSpec(
        kind=kind,
        workspace_id=workspace_id,
        extra={
            "tournament_id": tournament_id,
            "requested_by_user_id": requested_by_user_id,
            "algorithms": list(algorithms) if algorithms else None,
            "training_workspace_ids": (
                sorted({int(wid) for wid in training_workspace_ids}) if training_workspace_ids is not None else None
            ),
            "progress": {},
        },
    )
    try:
        job = await job_runtime.create(session, spec)
    except JobConflict as exc:
        await session.rollback()
        existing = await job_runtime.get_active(session, workspace_id)
        raise JobConflict(int(existing.id) if existing is not None else exc.existing_id) from exc
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
    job = await job_runtime.get(session, job_id)
    if job is None:
        return None
    progress = dict(job.progress or {})
    progress[stage] = {"state": state, "detail": detail or {}}
    await _repo.update_fields(session, job, {"progress": progress})
    # Staged before the commit that carries it: this IS the write the tick
    # reports, so the runner no longer re-reads the row to announce it.
    await emit_job_event(
        session,
        job_id=job_id,
        workspace_id=job.workspace_id,
        tournament_id=int(job.tournament_id),
        kind=job.kind,
        status=job.status,
        progress=progress,
        actor_user_id=job.requested_by_user_id,
    )
    await session.commit()
    return job
