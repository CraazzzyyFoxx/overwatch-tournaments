from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException
from shared.jobs import JobService, Retry, Status, Unlimited
from shared.repository import (
    TournamentComputationJobRepository,
    TournamentRecalculationStateRepository,
)
from shared.rpc.common import http_error
from shared.services.tournament.computation import (
    ACTIVE_STATUSES,
    create_job,
    dispatch_job,
)
from src import models

JobKind = Literal["bracket", "standings"]
JobStatus = Literal["pending", "running", "succeeded", "failed", "superseded"]
FailureDisposition = Literal["retry", "failed", "ignored"]

TERMINAL_STATUSES = ("succeeded", "failed", "superseded")
MAX_ATTEMPTS = 3


def failure_message(exc: Exception) -> str:
    """``job.error`` text; the admin UI shows it verbatim as the failure toast.

    A domain refusal is a sentence meant for the admin; anything else is a bug,
    named by type. The traceback stays in the log (``logger.exception``).
    """
    if not isinstance(exc, BaseAPIException):
        return f"{type(exc).__name__}: {exc}"
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("code") and detail.get("message"):
        # The admin client branches on this code substring (upstream_stages_not_completed).
        return f"{detail['code']}: {detail['message']}"
    message, _ = http_error(exc)
    return message


class _ComputationJobStore:
    def __init__(self, svc: ComputationJobsService) -> None:
        self._svc = svc

    def status_of(self, job: Any) -> str:
        return str(job.status)

    def attempts_of(self, job: Any) -> int:
        return int(job.attempts)

    async def get(self, session: Any, job_id: Any) -> Any:
        return await self._svc.get_job(session, int(job_id), for_update=True)

    async def set_fields(self, session: Any, job: Any, fields: dict[str, Any]) -> Any:
        del session
        for key, value in fields.items():
            setattr(job, key, value)
        return job


class ComputationJobsService:
    def __init__(
        self,
        *,
        job_repo: TournamentComputationJobRepository = TournamentComputationJobRepository(),
        state_repo: TournamentRecalculationStateRepository = TournamentRecalculationStateRepository(),
    ) -> None:
        self.job_repo = job_repo
        self.state_repo = state_repo
        self.runtime = JobService(
            store=_ComputationJobStore(self),
            concurrency=Unlimited(),
            retry=Retry(max_attempts=MAX_ATTEMPTS, extra_terminal=frozenset({"superseded"})),
        )

    async def get_job(
        self,
        session: AsyncSession,
        job_id: int,
        *,
        for_update: bool = False,
    ) -> models.TournamentComputationJob | None:
        return await self.job_repo.get_job(session, job_id, for_update=for_update)

    async def list_jobs(
        self,
        session: AsyncSession,
        *,
        tournament_id: int | None = None,
        stage_id: int | None = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[models.TournamentComputationJob]:
        return list(
            await self.job_repo.list_jobs(
                session,
                tournament_id=tournament_id,
                stage_id=stage_id,
                statuses=ACTIVE_STATUSES if active_only else None,
                limit=limit,
            )
        )

    async def _ensure_recalculation_state(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        increment: bool,
    ) -> models.TournamentRecalculationState:
        state = await self.state_repo.ensure_locked(session, tournament_id, increment=increment)
        if state is None:
            raise RuntimeError(f"Failed to create recalculation state for tournament {tournament_id}")
        return state

    async def _create_standings_job_for_state(
        self,
        session: AsyncSession,
        state: models.TournamentRecalculationState,
        *,
        requested_by_user_id: int | None = None,
    ) -> models.TournamentComputationJob | None:
        if state.completed_generation >= state.requested_generation:
            return None
        return await create_job(
            session,
            kind="standings",
            operation="recalculate",
            tournament_id=state.tournament_id,
            stage_id=None,
            stage_item_id=None,
            payload={"generation": int(state.requested_generation)},
            requested_by_user_id=requested_by_user_id,
            idempotency_key=f"standings:{state.tournament_id}",
        )

    async def request_standings_recalculation(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        requested_by_user_id: int | None = None,
    ) -> models.TournamentComputationJob:
        state = await self._ensure_recalculation_state(session, tournament_id, increment=True)
        job = await self._create_standings_job_for_state(
            session,
            state,
            requested_by_user_id=requested_by_user_id,
        )
        if job is None:
            raise RuntimeError(f"Failed to schedule standings recalculation for tournament {tournament_id}")
        return job

    async def request_followup_standings_job(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.TournamentComputationJob | None:
        state = await self._ensure_recalculation_state(session, tournament_id, increment=False)
        return await self._create_standings_job_for_state(session, state)

    async def claim_job(
        self,
        session: AsyncSession,
        job_id: int,
        *,
        kind: JobKind,
    ) -> models.TournamentComputationJob | None:
        job = await self.get_job(session, job_id, for_update=True)
        if job is None or job.kind != kind or job.status in TERMINAL_STATUSES:
            return None
        # A redelivered message can legitimately find a running job after the
        # previous worker crashed. The execution transaction locks the job row, so
        # reclaiming here remains single-flight while making crash recovery prompt.
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.finished_at = None
        job.error = None
        job.attempts += 1
        await session.commit()
        return job

    async def mark_job_succeeded(
        self,
        session: AsyncSession,
        job: models.TournamentComputationJob,
        result: dict[str, Any],
    ) -> None:
        job.status = "succeeded"
        job.result_json = result
        job.error = None
        job.finished_at = datetime.now(UTC)

    async def mark_job_failed(
        self,
        session: AsyncSession,
        job_id: int,
        error: str,
    ) -> FailureDisposition:
        job = await self.runtime.mark_failed(session, job_id, error=error[:4000])
        if job is None or job.status in ("succeeded", "superseded"):
            return "ignored"
        if job.status == Status.FAILED:
            await session.commit()
            return "failed"
        await dispatch_job(session, job)
        await session.commit()
        return "retry"

    async def complete_standings_generation(
        self,
        session: AsyncSession,
        tournament_id: int,
        generation: int,
    ) -> models.TournamentRecalculationState:
        state = await self._ensure_recalculation_state(session, tournament_id, increment=False)
        state.completed_generation = max(int(state.completed_generation), int(generation))
        return state


jobs_service = ComputationJobsService()
