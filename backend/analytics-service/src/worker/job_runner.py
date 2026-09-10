"""Worker entry: consume ``analytics_job`` and run compute/train."""

from __future__ import annotations

import logging
import traceback
import typing

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.jobs import JOB_KIND_COMPUTE, JOB_KIND_TRAIN_ML, job_runtime, update_progress
from src.services.analytics.flows import flows_service
from src.services.ml.inference.runner import run_for_tournament
from src.services.ml.training.orchestrator import train_all_models
from src.worker.job_realtime import emit_job_event

logger = logging.getLogger(__name__)

__all__ = ("AnalyticsJobRunner", "runner_service")


class AnalyticsJobRunner:
    def __init__(self, *, runtime: typing.Any = job_runtime) -> None:
        self.runtime = runtime

    async def _rollback_after_failure(self, session: AsyncSession) -> None:
        try:
            await session.rollback()
        except Exception:
            logger.exception("Failed to rollback analytics job session after exception")

    async def _emit(
        self,
        session: AsyncSession,
        job,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        try:
            await emit_job_event(
                session,
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
            logger.exception("Failed to stage analytics_job realtime event")

    async def _run_compute(
        self,
        session: AsyncSession,
        job,
    ) -> dict[str, typing.Any]:
        summary: dict[str, typing.Any] = {}
        job_id = int(job.id)
        workspace_id = job.workspace_id
        tournament_id = int(job.tournament_id)

        # update_progress stages its own tick; the runner only announces the
        # job's own status transitions.
        await update_progress(session, job_id, stage="ratings_recalc", state="running")
        try:
            algos: typing.Iterable[str] | None = list(job.algorithms) if job.algorithms else None
            algorithms = await flows_service.recalculate_analytics(
                session,
                tournament_id,
                algos,
                workspace_id=workspace_id,
            )
            await update_progress(
                session,
                job_id,
                stage="ratings_recalc",
                state="done",
                detail={"algorithms": algorithms},
            )
        except Exception as exc:
            logger.exception("ratings recalculate failed")
            await self._rollback_after_failure(session)
            await update_progress(
                session,
                job_id,
                stage="ratings_recalc",
                state="failed",
                detail={"error": str(exc)},
            )
            raise

        await update_progress(session, job_id, stage="ml_inference", state="running")
        try:
            ml = await run_for_tournament(
                session,
                tournament_id,
                workspace_id=workspace_id,
            )
            summary["ml"] = ml
            await update_progress(session, job_id, stage="ml_inference", state="done", detail=ml)
        except Exception as exc:
            logger.exception("ML inference failed")
            await self._rollback_after_failure(session)
            await update_progress(
                session,
                job_id,
                stage="ml_inference",
                state="failed",
                detail={"error": str(exc)},
            )
            raise

        return summary

    async def _run_train_ml(
        self,
        session: AsyncSession,
        job,
    ) -> dict[str, typing.Any]:
        job_id = int(job.id)
        tournament_id = int(job.tournament_id)
        training_workspace_ids = getattr(job, "training_workspace_ids", None)

        await update_progress(session, job_id, stage="train", state="running")
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
            await self._rollback_after_failure(session)
            await update_progress(
                session,
                job_id,
                stage="train",
                state="failed",
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
        self,
        session: AsyncSession,
        job_id: int,
    ) -> None:
        job = await self.runtime.get(session, job_id)
        if job is None:
            logger.warning("Analytics job not found: %d", job_id)
            return
        job_id = int(job.id)

        # Every _emit is staged on the transaction its status change belongs to,
        # so a mark_* that fails to commit announces nothing.
        await self.runtime.mark_running(session, job_id)
        await self._emit(session, job, status="running")
        await session.commit()

        try:
            if job.kind == JOB_KIND_TRAIN_ML:
                await self._run_train_ml(session, job)
            elif job.kind == JOB_KIND_COMPUTE:
                await self._run_compute(session, job)
            else:
                raise RuntimeError(f"unknown job kind: {job.kind!r}")
        except Exception as exc:
            tb = traceback.format_exc(limit=10)
            await self._rollback_after_failure(session)
            await self.runtime.mark_failed(session, job_id, error=f"{exc}\n{tb}")
            await self._emit(session, job, status="failed", error=str(exc))
            await session.commit()
            return

        await self.runtime.mark_succeeded(session, job_id)
        await self._emit(session, job, status="succeeded")
        await session.commit()


runner_service = AnalyticsJobRunner()
