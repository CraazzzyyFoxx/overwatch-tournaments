from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from shared.messaging.config import TOURNAMENT_COMPUTE_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.tournament.computation import TournamentComputationJob
from shared.repository import TournamentComputationJobRepository

JobKind = Literal["bracket", "standings"]
BracketOperation = Literal["generate_stage", "activate_and_generate", "generate_next_swiss_round"]

ACTIVE_STATUSES = ("pending", "running")

_jobs = TournamentComputationJobRepository()


def _routing_key(kind: JobKind) -> str:
    return f"tournament.compute.{kind}"


async def _active_job(
    session: AsyncSession,
    idempotency_key: str,
) -> TournamentComputationJob | None:
    return await _jobs.get_active_by_idempotency(session, idempotency_key, ACTIVE_STATUSES)


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
    await _jobs.lock_idempotency(session, idempotency_key)
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
    job = await _jobs.create(session, job)
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
