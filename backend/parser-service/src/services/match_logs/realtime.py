"""Thin realtime signal for the admin match-log monitor.

Publishes a non-durable ``logs.updated`` event to the workspace-scoped
``workspace:{id}:logs`` topic when a match-log record changes state. The gateway
relays it to WS subscribers (the admin log monitor), which then refetch
``/admin/logs/history``. The signal carries no record data, so workspace
membership (the existing ``workspace:*:*`` topic ACL) is sufficient — the actual
log data is still gated by ``log.read`` on the refetch.

Unlike the durable encounter map-veto path, this is a fire-and-forget Redis
publish (no WorkspaceEvent row, no replay cursor): the monitor always does an
initial fetch on subscribe, so missed signals self-heal.
"""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from redis.asyncio import Redis

from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services import realtime_topics
from shared.services.realtime_publisher import publish_envelope_to_redis

_EVENT_TYPE = "logs.updated"


async def publish_logs_updated(redis: Redis | None, workspace_id: int | None, *, reason: str = "log_changed") -> None:
    """Best-effort publish of a thin ``logs.updated`` signal for a workspace."""
    if redis is None or not workspace_id:
        return
    topic = realtime_topics.logs(int(workspace_id))
    envelope = WorkspaceEventEnvelope(
        event_id=0,  # non-durable signal: no replay cursor (clients refetch on subscribe)
        event_type=_EVENT_TYPE,
        schema_version=1,
        occurred_at=datetime.now(UTC),
        actor_user_id=None,
        data={"workspace_id": int(workspace_id), "reason": reason},
    )
    try:
        await publish_envelope_to_redis(redis, topic=topic, envelope=envelope)
    except Exception:  # pragma: no cover - best-effort signal
        logger.exception(f"Failed to publish logs.updated realtime signal for workspace {workspace_id}")
