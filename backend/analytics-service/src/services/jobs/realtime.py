"""Helpers to publish analytics-job lifecycle events to the realtime topic.

The worker calls these as each stage transitions; the realtime-service
consumes the Redis channel and fans the envelope out to subscribed
WebSocket clients.
"""

from __future__ import annotations

import typing

from redis.asyncio import Redis
from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services.realtime_publisher import publish_event
from shared.services.realtime_topics import analytics_jobs
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ("publish_job_event",)


async def publish_job_event(
    session: AsyncSession,
    redis: Redis | None,
    *,
    job_id: int,
    workspace_id: int | None,
    tournament_id: int,
    kind: str,
    status: str,
    progress: dict[str, typing.Any] | None = None,
    error: str | None = None,
    actor_user_id: int | None = None,
) -> WorkspaceEventEnvelope | None:
    """Persist + publish a single ``analytics_job.<status>`` event.

    ``workspace_id=None`` (global recompute) is supported but won't reach any
    WS subscriber — they all join workspace-scoped topics. We still write the
    row to the audit log so the activity is recoverable.
    """
    if workspace_id is None:
        return None
    topic = analytics_jobs(workspace_id)
    return await publish_event(
        session,
        redis,
        topic=topic,
        event_type=f"analytics_job.{status}",
        payload={
            "job_id": int(job_id),
            "workspace_id": int(workspace_id),
            "tournament_id": int(tournament_id),
            "kind": kind,
            "status": status,
            "progress": progress or {},
            "error": error,
        },
        workspace_id=int(workspace_id),
        tournament_id=int(tournament_id),
        actor_user_id=actor_user_id,
    )
