"""After-commit realtime publishing for encounter map-veto updates.

Encounter-scoped sibling of ``src/services/tournament/realtime_commit.py``.
Where the tournament module fans bracket/results/structure changes out to the
``tournament:{id}:bracket`` topic, this module emits a thin ``map_veto.updated``
signal on the public ``encounter:{id}:map-veto`` topic. The payload carries no
per-viewer state (``viewer_side`` is presentation-only): subscribers refetch the
map-pool state on receipt.

The flow mirrors the tournament module exactly:
1. A write path calls ``register_map_veto_realtime_update(session, encounter_id)``
   immediately before its commit, stashing the id under a DISTINCT ``session.info``
   key (so it never collides with the tournament module's keys).
2. A ``before_flush`` listener persists a ``WorkspaceEvent`` row for durability.
3. An ``after_commit`` listener publishes the persisted event's envelope to Redis,
   from which the gateway events consumer relays it to WS subscribers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import event
from sqlalchemy.orm import Session

from shared.models.platform.realtime import WorkspaceEvent
from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services import realtime_topics
from shared.services.realtime_publisher import event_to_envelope, publish_event_to_redis_url
from src.core import config

_MAP_VETO_REASON = "veto_changed"
_MAP_VETO_EVENT_TYPE = "map_veto.updated"

# Distinct from the tournament module's keys so the two listeners never clobber
# each other's staged updates on a shared Session.
_SESSION_KEY = "encounter_map_veto_realtime_updates"
_SESSION_EVENTS_KEY = "encounter_map_veto_realtime_event_objects"


def register_map_veto_realtime_update(session: Any, encounter_id: int) -> None:
    """Stage a map-veto realtime signal for the given encounter on this session.

    Call immediately before the commit that mutated the map pool. The staged ids
    are turned into persisted ``WorkspaceEvent`` rows on ``before_flush`` and
    published to Redis on ``after_commit``.
    """
    sync_session = getattr(session, "sync_session", None)
    info = getattr(sync_session or session, "info", None)
    if info is None:
        return

    updates: set[int] = info.setdefault(_SESSION_KEY, set())
    updates.add(int(encounter_id))


def pop_registered_map_veto_realtime_updates(session: Any) -> list[int]:
    sync_session = getattr(session, "sync_session", None)
    info = getattr(sync_session or session, "info", None)
    if info is None:
        return []

    updates: set[int] = info.pop(_SESSION_KEY, set())
    return sorted(updates)


def _build_realtime_event(encounter_id: int) -> WorkspaceEvent:
    return WorkspaceEvent(
        topic=realtime_topics.map_veto(encounter_id),
        event_type=_MAP_VETO_EVENT_TYPE,
        schema_version=1,
        payload={
            "encounter_id": int(encounter_id),
            "reason": _MAP_VETO_REASON,
        },
    )


async def _publish_persisted_event(topic: str, envelope: WorkspaceEventEnvelope) -> None:
    try:
        await publish_event_to_redis_url(str(config.settings.redis_url), topic=topic, envelope=envelope)
    except Exception:
        logger.exception("Failed to publish persisted map-veto realtime event", topic=topic)


@event.listens_for(Session, "before_flush")
def _stage_registered_map_veto_updates_before_flush(session: Session, _flush_context: Any, _instances: Any) -> None:
    updates = pop_registered_map_veto_realtime_updates(session)
    if not updates:
        return

    events = [_build_realtime_event(encounter_id) for encounter_id in updates]
    session.add_all(events)
    session.info.setdefault(_SESSION_EVENTS_KEY, []).extend(events)


@event.listens_for(Session, "after_commit")
def _publish_registered_map_veto_updates_after_commit(session: Session) -> None:
    events: list[WorkspaceEvent] = session.info.pop(_SESSION_EVENTS_KEY, [])
    if not events:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Cannot publish map-veto realtime updates without a running event loop")
        return

    envelopes: list[tuple[str, WorkspaceEventEnvelope]] = []
    for event_obj in events:
        if event_obj.occurred_at is None:
            event_obj.occurred_at = datetime.now(UTC)
        envelopes.append((event_obj.topic, event_to_envelope(event_obj)))

    for topic, envelope in envelopes:
        loop.create_task(_publish_persisted_event(topic, envelope))


@event.listens_for(Session, "after_rollback")
def _clear_registered_map_veto_updates_after_rollback(session: Session) -> None:
    pop_registered_map_veto_realtime_updates(session)
    session.info.pop(_SESSION_EVENTS_KEY, None)
