"""Shared helpers for the live-balancer realtime topic.

Both ``tournament-service`` (registration edits) and ``balancer-service``
(balance/config/teams edits + job lifecycle) publish to the single
tournament-scoped topic ``tournament:{id}:balancer``. The frontend subscribes
once and branches on ``event_type``:

* ``balancer.*_changed`` — a lightweight "data changed, refetch" signal; the
  client invalidates the matching React Query keys.
* ``balancer_job.*`` — job-status lifecycle (queued/running/progress/
  succeeded/failed), broadcast to everyone with the page open.
* ``balancer.presence`` — ephemeral presence, routed by realtime-service from
  live WebSocket connections (never persisted; not published through here).

Keeping the event-type strings in one place avoids drift between the two
publishing services (the frontend mirrors these literals in TypeScript).
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services import realtime_topics
from shared.services.realtime_publisher import publish_event
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = (
    "BALANCER_BALANCE_SAVED",
    "BALANCER_CONFIG_CHANGED",
    "BALANCER_DRAG",
    "BALANCER_JOB_FAILED",
    "BALANCER_JOB_PROGRESS",
    "BALANCER_JOB_QUEUED",
    "BALANCER_JOB_RUNNING",
    "BALANCER_JOB_SUCCEEDED",
    "BALANCER_PRESENCE",
    "BALANCER_REGISTRATIONS_CHANGED",
    "BALANCER_TEAMS_CHANGED",
    "publish_balancer_event",
)

# Data-edit signals (persisted; clients invalidate queries).
BALANCER_REGISTRATIONS_CHANGED = "balancer.registrations_changed"
BALANCER_BALANCE_SAVED = "balancer.balance_saved"
BALANCER_TEAMS_CHANGED = "balancer.teams_changed"
BALANCER_CONFIG_CHANGED = "balancer.config_changed"

# Job lifecycle (persisted; broadcast to all viewers).
BALANCER_JOB_QUEUED = "balancer_job.queued"
BALANCER_JOB_RUNNING = "balancer_job.running"
BALANCER_JOB_PROGRESS = "balancer_job.progress"
BALANCER_JOB_SUCCEEDED = "balancer_job.succeeded"
BALANCER_JOB_FAILED = "balancer_job.failed"

# Ephemeral presence (NOT published via publish_balancer_event; emitted by
# realtime-service directly). Declared here so the literal has one home.
BALANCER_PRESENCE = "balancer.presence"

# Ephemeral live-drag overlay. Client-originated (published over the WebSocket
# via the `publish` op) and fanned out to co-subscribers by realtime-service;
# never persisted and never published through publish_balancer_event. This is
# the single event type the realtime-service allows clients to publish on the
# balancer topic — see the publish allowlist in realtime-service ws routes.
BALANCER_DRAG = "balancer.drag"


async def publish_balancer_event(
    session: AsyncSession,
    redis: Redis | None,
    *,
    tournament_id: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
    workspace_id: int | None = None,
    actor_user_id: int | None = None,
) -> WorkspaceEventEnvelope:
    """Persist + publish a single balancer event to ``tournament:{id}:balancer``.

    ``tournament_id`` is always folded into the payload so a client that
    subscribes to several topics (or filters by tournament) can route locally.
    """
    body: dict[str, Any] = {"tournament_id": int(tournament_id)}
    if payload:
        body.update(payload)
    return await publish_event(
        session,
        redis,
        topic=realtime_topics.balancer(tournament_id),
        event_type=event_type,
        tournament_id=int(tournament_id),
        workspace_id=int(workspace_id) if workspace_id is not None else None,
        payload=body,
        actor_user_id=actor_user_id,
    )
