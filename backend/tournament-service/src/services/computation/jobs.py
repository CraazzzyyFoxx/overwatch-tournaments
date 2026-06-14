from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import sqlalchemy as sa
from shared.services.tournament_computation import (
    ACTIVE_STATUSES,
    create_job,
    dispatch_job,
)
from shared.services.tournament_computation import (
    request_bracket_job as shared_request_bracket_job,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

JobKind = Literal["bracket", "standings"]
JobStatus = Literal["pending", "running", "succeeded", "failed", "superseded"]
FailureDisposition = Literal["retry", "failed", "ignored"]

TERMINAL_STATUSES = ("succeeded", "failed", "superseded")
MAX_ATTEMPTS = 3
request_bracket_job = shared_request_bracket_job


async def get_job(
    session: AsyncSession,
    job_id: int,
    *,
    for_update: bool = False,
) -> models.TournamentComputationJob | None:
    query = sa.select(models.TournamentComputationJob).where(models.TournamentComputationJob.id == job_id)
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)


async def list_jobs(
    session: AsyncSession,
    *,
    tournament_id: int | None = None,
    stage_id: int | None = None,
    active_only: bool = False,
    limit: int = 50,
) -> list[models.TournamentComputationJob]:
    query = sa.select(models.TournamentComputationJob)
    if tournament_id is not None:
        query = query.where(models.TournamentComputationJob.tournament_id == tournament_id)
    if stage_id is not None:
        query = query.where(models.TournamentComputationJob.stage_id == stage_id)
    if active_only:
        query = query.where(models.TournamentComputationJob.status.in_(ACTIVE_STATUSES))
    result = await session.scalars(query.order_by(models.TournamentComputationJob.id.desc()).limit(limit))
    return list(result.all())


async def _ensure_recalculation_state(
    session: AsyncSession,
    tournament_id: int,
    *,
    increment: bool,
) -> models.TournamentRecalculationState:
    values = {
        "tournament_id": tournament_id,
        "requested_generation": 1 if increment else 0,
        "completed_generation": 0,
    }
    stmt = pg_insert(models.TournamentRecalculationState).values(**values)
    if increment:
        stmt = stmt.on_conflict_do_update(
            index_elements=[models.TournamentRecalculationState.tournament_id],
            set_={
                "requested_generation": models.TournamentRecalculationState.requested_generation + 1,
                "updated_at": sa.func.now(),
            },
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=[models.TournamentRecalculationState.tournament_id])
    await session.execute(stmt)
    state = await session.scalar(
        sa.select(models.TournamentRecalculationState)
        .where(models.TournamentRecalculationState.tournament_id == tournament_id)
        .with_for_update()
    )
    if state is None:
        raise RuntimeError(f"Failed to create recalculation state for tournament {tournament_id}")
    return state


async def _create_standings_job_for_state(
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
    session: AsyncSession,
    tournament_id: int,
    *,
    requested_by_user_id: int | None = None,
) -> models.TournamentComputationJob:
    state = await _ensure_recalculation_state(session, tournament_id, increment=True)
    job = await _create_standings_job_for_state(
        session,
        state,
        requested_by_user_id=requested_by_user_id,
    )
    if job is None:
        raise RuntimeError(f"Failed to schedule standings recalculation for tournament {tournament_id}")
    return job


async def request_followup_standings_job(
    session: AsyncSession,
    tournament_id: int,
) -> models.TournamentComputationJob | None:
    state = await _ensure_recalculation_state(session, tournament_id, increment=False)
    return await _create_standings_job_for_state(session, state)


async def claim_job(
    session: AsyncSession,
    job_id: int,
    *,
    kind: JobKind,
) -> models.TournamentComputationJob | None:
    job = await get_job(session, job_id, for_update=True)
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
    session: AsyncSession,
    job: models.TournamentComputationJob,
    result: dict[str, Any],
) -> None:
    job.status = "succeeded"
    job.result_json = result
    job.error = None
    job.finished_at = datetime.now(UTC)


async def mark_job_failed(
    session: AsyncSession,
    job_id: int,
    error: str,
) -> FailureDisposition:
    job = await get_job(session, job_id, for_update=True)
    if job is None or job.status in TERMINAL_STATUSES:
        return "ignored"
    terminal = job.attempts >= MAX_ATTEMPTS
    job.status = "failed" if terminal else "pending"
    job.error = error[:4000]
    job.finished_at = datetime.now(UTC) if terminal else None
    if not terminal:
        await dispatch_job(session, job)
    await session.commit()
    return "failed" if terminal else "retry"


async def complete_standings_generation(
    session: AsyncSession,
    tournament_id: int,
    generation: int,
) -> models.TournamentRecalculationState:
    state = await _ensure_recalculation_state(session, tournament_id, increment=False)
    state.completed_generation = max(int(state.completed_generation), int(generation))
    return state
