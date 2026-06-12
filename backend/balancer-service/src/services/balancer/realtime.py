"""Realtime fan-out for balancer-service edits and job lifecycle.

Publishes to the tournament-scoped ``tournament:{id}:balancer`` topic shared
with tournament-service (registration edits). Two kinds of events originate
here:

* data-edit signals (``balancer.balance_saved`` / ``balancer.teams_changed`` /
  ``balancer.config_changed``) — clients invalidate the matching queries;
* job lifecycle (``balancer_job.*``) — broadcast job progress to everyone with
  the page open.

Each emitter runs in its own short-lived session + Redis client so it never
entangles with the request/worker transaction that already committed. Failures
are swallowed — the frontend self-heals via reconnect refetch (data) or the
REST job-status snapshot (jobs).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services import realtime_topics
from shared.services.balancer_realtime import BALANCER_JOB_PROGRESS, publish_balancer_event
from shared.services.realtime_publisher import publish_envelope_to_redis

from src.core import db
from src.core.config import config

__all__ = (
    "emit_balancer_data_event",
    "emit_balancer_job_event",
    "emit_balancer_job_progress",
)


async def _emit(
    tournament_id: int,
    event_type: str,
    *,
    workspace_id: int | None,
    payload: dict[str, Any] | None,
    actor_user_id: int | None,
) -> None:
    redis = Redis.from_url(config.redis_url, decode_responses=True)
    try:
        async with db.async_session_maker() as session:
            async with session.begin():
                await publish_balancer_event(
                    session,
                    redis,
                    tournament_id=tournament_id,
                    workspace_id=workspace_id,
                    event_type=event_type,
                    payload=payload,
                    actor_user_id=actor_user_id,
                )
    except Exception:
        logger.exception(
            "Failed to publish balancer event",
            tournament_id=tournament_id,
            event_type=event_type,
        )
    finally:
        await redis.aclose()


async def emit_balancer_data_event(
    tournament_id: int,
    event_type: str,
    *,
    workspace_id: int | None = None,
    payload: dict[str, Any] | None = None,
    actor_user_id: int | None = None,
) -> None:
    """Persist + broadcast a ``balancer.*_changed`` data-edit signal."""
    await _emit(
        tournament_id,
        event_type,
        workspace_id=workspace_id,
        payload=payload,
        actor_user_id=actor_user_id,
    )


async def emit_balancer_job_event(
    tournament_id: int,
    event_type: str,
    *,
    job_id: str,
    status: str,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
    workspace_id: int | None = None,
    actor_user_id: int | None = None,
) -> None:
    """Persist + broadcast a ``balancer_job.*`` lifecycle event to all viewers.

    Used for the durable transitions (queued/running/succeeded/failed) so a
    late joiner catches up via cursor replay. Continuous progress ticks go
    through :func:`emit_balancer_job_progress` (ephemeral) instead.
    """
    await _emit(
        tournament_id,
        event_type,
        workspace_id=workspace_id,
        payload={
            "job_id": job_id,
            "status": status,
            "progress": progress or {},
            "error": error,
        },
        actor_user_id=actor_user_id,
    )


async def emit_balancer_job_progress(
    tournament_id: int,
    *,
    job_id: str,
    status: str,
    progress: dict[str, Any] | None,
    redis: Redis | None = None,
) -> None:
    """Broadcast an ephemeral ``balancer_job.progress`` tick (Redis only).

    Progress is high-frequency and transient, so it is NOT persisted to the
    event log (``event_id=0`` keeps the frontend replay cursor untouched).
    Late joiners still see the last durable lifecycle state plus the next tick.
    Pass an existing ``redis`` client to reuse the connection across ticks.
    """
    envelope = WorkspaceEventEnvelope(
        event_id=0,
        event_type=BALANCER_JOB_PROGRESS,
        schema_version=1,
        occurred_at=datetime.now(UTC),
        actor_user_id=None,
        data={
            "tournament_id": int(tournament_id),
            "job_id": job_id,
            "status": status,
            "progress": progress or {},
        },
    )
    owns_client = redis is None
    client = redis or Redis.from_url(config.redis_url, decode_responses=True)
    try:
        await publish_envelope_to_redis(
            client,
            topic=realtime_topics.balancer(tournament_id),
            envelope=envelope,
        )
    except Exception:
        logger.exception("Failed to publish balancer job progress", tournament_id=tournament_id)
    finally:
        if owns_client:
            await client.aclose()
