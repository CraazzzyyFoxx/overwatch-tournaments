from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.clients.s3 import S3Client
from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.config import TOURNAMENT_COMPUTE_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.observability import observe_scheduled_job
from shared.repository import DivisionGridImportJobRepository, WorkspaceRepository
from src import schemas
from src.core import config, db
from src.services.division_grid.marketplace import MarketplaceService, marketplace_service

__all__ = (
    "ImportJobsService",
    "import_jobs_service",
    "process_import_job",
    "recover_stale_import_jobs",
    "to_read",
)

_ROUTING_KEY = "tournament.compute.division-grid-import"
# One grid version per job, its S3 copies bounded: a job still "running" after this long lost its worker (a restart).
_STALE_RUNNING_AFTER = timedelta(minutes=15)
_ACTIVE_STATUSES = ("pending", "running")


def _idempotency_key(
    *,
    workspace_id: int,
    source_workspace_id: int,
    source_grid_id: int,
    source_version_id: int,
    include_icons: bool,
    include_native_rank_mappings: bool,
    source_fingerprint: str,
) -> str:
    raw = ":".join(
        (
            str(workspace_id),
            str(source_workspace_id),
            str(source_grid_id),
            str(source_version_id),
            str(include_icons),
            str(include_native_rank_mappings),
            source_fingerprint,
        )
    )
    return f"division-grid-import:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def to_read(job: models.DivisionGridImportJob) -> schemas.DivisionGridImportJobRead:
    result = (
        schemas.DivisionGridMarketplaceImportResult.model_validate(job.result_json)
        if job.result_json is not None
        else None
    )
    return schemas.DivisionGridImportJobRead(
        id=job.id,
        workspace_id=job.workspace_id,
        source_workspace_id=job.source_workspace_id,
        requested_by_user_id=job.requested_by_user_id,
        status=job.status,
        progress=job.progress,
        result=result,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _new_s3_client() -> S3Client:
    return S3Client.from_settings(config.settings)


class ImportJobsService:
    """Queue, poll and execute marketplace division-grid import jobs."""

    def __init__(
        self,
        *,
        job_repo: DivisionGridImportJobRepository = DivisionGridImportJobRepository(),
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
        marketplace: MarketplaceService = marketplace_service,
    ) -> None:
        self.job_repo = job_repo
        self.workspace_repo = workspace_repo
        self.marketplace = marketplace

    async def dispatch_import_job(self, session: AsyncSession, job: models.DivisionGridImportJob) -> None:
        await enqueue_outbox_event(
            session,
            {"job_id": int(job.id)},
            exchange=TOURNAMENT_COMPUTE_EXCHANGE,
            routing_key=_ROUTING_KEY,
            event_id=uuid4().hex,
            event_type="division_grid_import_job",
        )

    async def create_import_job(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        source_workspace_id: int,
        requested_by_user_id: int | None,
        source_grid_id: int,
        source_version_id: int,
        include_icons: bool,
        include_native_rank_mappings: bool,
        source_fingerprint: str,
    ) -> models.DivisionGridImportJob:
        idempotency_key = _idempotency_key(
            workspace_id=workspace_id,
            source_workspace_id=source_workspace_id,
            source_grid_id=source_grid_id,
            source_version_id=source_version_id,
            include_icons=include_icons,
            include_native_rank_mappings=include_native_rank_mappings,
            source_fingerprint=source_fingerprint,
        )
        existing = await self.job_repo.get_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            if getattr(existing, "status", None) == "failed":
                await self.job_repo.update_fields(
                    session,
                    existing,
                    {
                        "status": "pending",
                        "progress": 0,
                        "result_json": None,
                        "error": None,
                        "started_at": None,
                        "finished_at": None,
                    },
                )
                await self.dispatch_import_job(session, existing)
            return existing

        job = await self.job_repo.create(
            session,
            models.DivisionGridImportJob(
                workspace_id=workspace_id,
                source_workspace_id=source_workspace_id,
                requested_by_user_id=requested_by_user_id,
                status="pending",
                progress=0,
                request_json={
                    "source_grid_id": source_grid_id,
                    "source_version_id": source_version_id,
                    "include_icons": include_icons,
                    "include_native_rank_mappings": include_native_rank_mappings,
                    "source_fingerprint": source_fingerprint,
                },
                idempotency_key=idempotency_key,
            ),
        )
        await self.dispatch_import_job(session, job)
        return job

    async def get_import_job(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        job_id: int,
    ) -> models.DivisionGridImportJob | None:
        return await self.job_repo.get_for_workspace(session, job_id=job_id, workspace_id=workspace_id)

    async def list_import_jobs(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        active_only: bool = False,
        limit: int = 20,
    ) -> list[models.DivisionGridImportJob]:
        jobs = await self.job_repo.list_for_workspace(
            session,
            workspace_id,
            statuses=_ACTIVE_STATUSES if active_only else None,
            limit=max(1, min(limit, 100)),
        )
        return list(jobs)

    async def recover_stale(self, session: AsyncSession, *, cutoff: datetime) -> int:
        """Requeue every import abandoned by a worker before ``cutoff``."""
        stale_jobs = list(await self.job_repo.list_stalled(session, cutoff=cutoff))
        for job in stale_jobs:
            await self.job_repo.update_fields(
                session,
                job,
                {
                    "status": "pending",
                    "progress": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error": "Previous worker stopped before the import completed; retrying",
                },
            )
            await self.dispatch_import_job(session, job)
        if stale_jobs:
            await session.commit()
        return len(stale_jobs)

    async def process(self, session: AsyncSession, job_id: int) -> None:
        """Claim one queued job and run its import to completion or failure."""
        # Conditional claim: only the poller whose UPDATE matched proceeds, and the
        # per-attempt resets ride the same statement so a job never reads as
        # claimed while still carrying the previous attempt's error.
        claimed = await self.job_repo.claim_queued(
            session,
            job_id,
            from_status="pending",
            to_status="running",
            started_at=datetime.now(UTC),
            extra_values={"progress": 10, "error": None, "finished_at": None},
        )
        if not claimed:
            return
        await session.commit()

        job = await self.job_repo.get(session, job_id)
        if job is None:
            return
        payload: dict[str, Any] = dict(job.request_json)
        s3 = _new_s3_client()
        try:
            await s3.start()
            target_workspace = await self.workspace_repo.get(session, job.workspace_id)
            source_workspace = await self.workspace_repo.get(session, job.source_workspace_id)
            if target_workspace is None or source_workspace is None:
                raise HTTPException(status_code=404, detail="Source or target workspace no longer exists")

            source_grids = await self.marketplace.get_marketplace_grids_by_ids(
                session,
                source_workspace_id=source_workspace.id,
                source_grid_ids=[payload["source_grid_id"]],
            )
            await self.job_repo.update_fields(session, job, {"progress": 35})
            result = await self.marketplace.import_division_grids(
                session,
                s3,
                target_workspace=target_workspace,
                source_workspace=source_workspace,
                source_grids=source_grids,
                mode="copy",
                expected_source_fingerprint=payload["source_fingerprint"],
                source_version_id=payload["source_version_id"],
                include_icons=payload["include_icons"],
                include_native_rank_mappings=payload["include_native_rank_mappings"],
            )
            await self.job_repo.update_fields(
                session,
                job,
                {
                    "status": "completed",
                    "progress": 100,
                    "result_json": result.model_dump(mode="json"),
                    "finished_at": datetime.now(UTC),
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            failed_job = await self.job_repo.get(session, job_id)
            if failed_job is not None:
                await self.job_repo.update_fields(
                    session,
                    failed_job,
                    {
                        "status": "failed",
                        "error": str(exc)[:2000],
                        "finished_at": datetime.now(UTC),
                    },
                )
                await session.commit()
            raise
        finally:
            await s3.close()


import_jobs_service = ImportJobsService()


# Worker/scheduler entrypoints: they own their session, so they stay
# module-level and `serve.py` imports them by name.
async def recover_stale_import_jobs() -> int:
    """Requeue imports abandoned by a worker after its lease window."""
    cutoff = datetime.now(UTC) - _STALE_RUNNING_AFTER
    async with observe_scheduled_job("division_grid_import_recovery"), db.async_session_maker() as session:
        return await import_jobs_service.recover_stale(session, cutoff=cutoff)


async def process_import_job(job_id: int) -> None:
    async with db.async_session_maker() as session:
        await import_jobs_service.process(session, job_id)
