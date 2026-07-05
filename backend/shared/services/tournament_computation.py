from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.messaging.config import TOURNAMENT_COMPUTE_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.tournament.computation import TournamentComputationJob

JobKind = Literal["bracket", "standings"]
BracketOperation = Literal["generate_stage", "activate_and_generate", "generate_next_swiss_round"]

ACTIVE_STATUSES = ("pending", "running")


def _routing_key(kind: JobKind) -> str:
    return f"tournament.compute.{kind}"


async def _active_job(
    session: AsyncSession,
    idempotency_key: str,
) -> TournamentComputationJob | None:
    return await session.scalar(
        sa.select(TournamentComputationJob)
        .where(
            TournamentComputationJob.idempotency_key == idempotency_key,
            TournamentComputationJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(TournamentComputationJob.id.desc())
        .limit(1)
    )


async def dispatch_job(
    session: AsyncSession,
    job: TournamentComputationJob,
) -> None:
    await enqueue_outbox_event(
        session,
        {"job_id": int(job.id)},
        exchange=TOURNAMENT_COMPUTE_EXCHANGE,
        routing_key=_routing_key(job.kind),
        event_id=uuid4().hex,
        event_type="tournament_computation_job",
    )


async def create_job(
    session: AsyncSession,
    *,
    kind: JobKind,
    operation: str,
    tournament_id: int,
    stage_id: int | None,
    stage_item_id: int | None,
    payload: dict[str, Any],
    requested_by_user_id: int | None,
    idempotency_key: str,
) -> TournamentComputationJob:
    # Serialize concurrent requests for the same logical job before checking
    # the partial unique index. The lock is released with the transaction.
    await session.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(idempotency_key))))
    active = await _active_job(session, idempotency_key)
    if active is not None:
        return active

    job = TournamentComputationJob(
        kind=kind,
        operation=operation,
        tournament_id=tournament_id,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        payload_json=payload,
        requested_by_user_id=requested_by_user_id,
        idempotency_key=idempotency_key,
        status="pending",
    )
    session.add(job)
    await session.flush()
    await dispatch_job(session, job)
    return job


async def request_bracket_job(
    session: AsyncSession,
    *,
    tournament_id: int,
    stage_id: int,
    operation: BracketOperation,
    stage_item_id: int | None = None,
    payload: dict[str, Any] | None = None,
    requested_by_user_id: int | None = None,
) -> TournamentComputationJob:
    scope = stage_item_id if stage_item_id is not None else "all"
    return await create_job(
        session,
        kind="bracket",
        operation=operation,
        tournament_id=tournament_id,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        payload=dict(payload or {}),
        requested_by_user_id=requested_by_user_id,
        idempotency_key=f"bracket:{stage_id}:{scope}",
    )
