"""The single realtime publication path.

Everything a service wants to announce goes through :func:`emit`. It replaced
six mechanisms that each carried their own guarantees, picked by hand at the
call site: ``register_tournament_realtime_update`` (session hook, bracket only),
``register_realtime_update`` (generic factory), ``publish_event`` /
``publish_patch`` (durable, published BEFORE the caller's commit),
``publish_envelope_to_redis`` (non-durable, no row), ``emit_balancer_data_event``
(its own session, fire-and-forget task) and ``enqueue_tournament_changed``
(outbox to RabbitMQ). Two production bugs came directly out of that choice
being manual — see docs/plans/2026-09-09-unified-event-delivery.md §1.

Invariants this module owns, so no caller has to remember them:

1. **Publication happens after the caller's commit, never before.** Rows are
   staged on the session and persisted in its ``before_flush``; the publish
   fires from ``after_commit``. A rolled-back transaction publishes nothing.
2. **Invalidation is a set.** Every ``invalidates`` list registered in one
   transaction for one scope is UNIONed into a single event. Union is
   commutative and idempotent, which is precisely why invalidation needs no
   ordering guarantees — unlike the domain patches, whose order matters and
   which are therefore never merged.
3. **Ordering after commit: local cache first, then clients.** The service's
   own cache is dropped before anything is published, so a client that reacts
   instantly cannot repopulate a gateway entry from a cache we were about to
   clear. (The cross-service half of that race is bounded by the outbox drain;
   the row itself is written inside the caller's transaction, so it is already
   durable by the time anything is published.)
4. **A resource may only be published under its own scope kind.** The manifest
   decides; a ``workspace.*`` resource on a tournament topic would be delivered
   to a different audience than the one allowed to see it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import event
from sqlalchemy.orm import Session

from shared.messaging.config import CACHE_INVALIDATION_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.platform.realtime import WorkspaceEvent
from shared.schemas.events import CacheInvalidatedEvent
from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services.realtime.resources import Resource, scope_kind_of
from shared.services.realtime.scope import Scope
from shared.services.realtime_publisher import event_to_envelope, publish_event_to_redis_url

__all__ = ("DomainEvent", "configure_realtime", "emit")

INVALIDATION_EVENT_TYPE = "cache.invalidated"

_STAGED_KEY = "realtime_staged"
_PENDING_KEY = "realtime_pending"

# asyncio keeps only a weak reference to a running task, so a fire-and-forget
# publish whose handle nobody holds can be collected mid-flight.
_background_tasks: set[asyncio.Task[Any]] = set()

CacheInvalidator = Callable[[Scope, frozenset[Resource], Mapping[str, Sequence[int]]], Awaitable[None]]

_redis_url: str | None = None
_cache_invalidator: CacheInvalidator | None = None


def configure_realtime(*, redis_url: str, cache_invalidator: CacheInvalidator | None = None) -> None:
    """Wire the process into the realtime rail. One call per entrypoint.

    Same shape and same reason as ``configure_cache()``: this module is shared
    across services and has no ``src.core.config`` of its own. ``main`` and
    ``serve`` are separate processes and each configures independently.

    ``cache_invalidator`` is how a service declares "I own caches that these
    resources describe". It runs BEFORE the publish (invariant 3). A service
    with no server-side cache passes nothing.
    """
    global _redis_url, _cache_invalidator
    _redis_url = redis_url
    _cache_invalidator = cache_invalidator


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Actual data for the UI: a patch, presence, job progress.

    ``domain`` is the topic suffix (``draft``, ``balancer``, ``map-veto``,
    ``pick-ban:hero``, ``streams``, ``notifications``, ...).

    ``resource`` is the client-cache resource a PATCH folds into (mirrors the
    frontend ``registerRealtimeResource`` key) — it is not an invalidation
    vocabulary entry and has nothing to do with ``invalidates``.

    ``durable=False`` publishes without persisting a row: no replay cursor, for
    signals a reconnecting client re-derives from its own snapshot anyway
    (presence, job progress).
    """

    domain: str
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    resource: str | None = None
    durable: bool = True
    schema_version: int = 1


@dataclass(slots=True)
class _Staged:
    invalidations: dict[Scope, tuple[set[Resource], dict[str, list[int]]]] = field(default_factory=dict)
    domain: list[tuple[Scope, DomainEvent, int | None]] = field(default_factory=list)


async def emit(
    session: Any,
    *,
    scope: Scope,
    invalidates: Sequence[Resource] = (),
    entity_ids: Mapping[str, Sequence[int]] | None = None,
    data: DomainEvent | None = None,
    actor_user_id: int | None = None,
) -> None:
    """Stage an invalidation and/or a domain event for this transaction.

    Async purely for call-site symmetry with the rest of the service layer (and
    so a future implementation may do IO here); it stages synchronously and
    performs no IO of its own.

    ``entity_ids`` narrows an invalidation for consumers that can use it
    (``{"registration_ids": [77]}``). Every consumer is free to ignore it and
    drop the whole resource — it exists so that adding precision later is not a
    format change across every publisher.
    """
    if not invalidates and data is None:
        raise ValueError("emit() needs invalidates, data, or both")

    for resource in invalidates:
        expected = scope_kind_of(resource)
        if expected is not scope.kind:
            raise ValueError(f"resource {resource} belongs to scope {expected}, got {scope.kind}")

    staged = _staged(session)
    if staged is None:
        # No session.info (a plain object in a unit test): nothing to hang the
        # transaction hooks on. Silently doing nothing here is what the old
        # factory did too, and it keeps callers free of session-shape checks.
        return

    if invalidates:
        resources, ids = staged.invalidations.setdefault(scope, (set(), {}))
        resources.update(invalidates)
        for key, values in (entity_ids or {}).items():
            ids.setdefault(key, []).extend(int(v) for v in values)

    if data is not None:
        staged.domain.append((scope, data, actor_user_id))


def _staged(session: Any) -> _Staged | None:
    sync_session = getattr(session, "sync_session", None)
    info = getattr(sync_session or session, "info", None)
    if info is None:
        return None
    staged = info.get(_STAGED_KEY)
    if staged is None:
        staged = _Staged()
        info[_STAGED_KEY] = staged
    return staged


def _invalidation_row(scope: Scope, resources: set[Resource], entity_ids: dict[str, list[int]]) -> WorkspaceEvent:
    payload: dict[str, Any] = {"resources": sorted(str(r) for r in resources)}
    if entity_ids:
        payload["entity_ids"] = {key: sorted(set(values)) for key, values in entity_ids.items()}
    return WorkspaceEvent(
        topic=scope.invalidation_topic,
        event_type=INVALIDATION_EVENT_TYPE,
        tournament_id=scope.tournament_id,
        workspace_id=scope.workspace_id,
        schema_version=1,
        payload=payload,
    )


def _domain_row(scope: Scope, data: DomainEvent, actor_user_id: int | None) -> WorkspaceEvent:
    payload = dict(data.payload)
    if data.resource is not None:
        payload["resource"] = data.resource
    return WorkspaceEvent(
        topic=scope.domain_topic(data.domain),
        event_type=data.event_type,
        tournament_id=scope.tournament_id,
        workspace_id=scope.workspace_id,
        actor_user_id=actor_user_id,
        schema_version=data.schema_version,
        payload=payload,
    )


@event.listens_for(Session, "before_flush")
def _persist_staged(session: Session, _flush_context: Any, _instances: Any) -> None:
    staged: _Staged | None = session.info.get(_STAGED_KEY)
    if staged is None:
        return
    session.info.pop(_STAGED_KEY, None)

    rows: list[WorkspaceEvent] = []
    pending: list[tuple[Scope, WorkspaceEvent | None, frozenset[Resource], dict[str, list[int]]]] = []

    for scope, (resources, entity_ids) in staged.invalidations.items():
        row = _invalidation_row(scope, resources, entity_ids)
        rows.append(row)
        pending.append((scope, row, frozenset(resources), entity_ids))

    for scope, data, actor_user_id in staged.domain:
        row = _domain_row(scope, data, actor_user_id)
        if data.durable:
            rows.append(row)
        pending.append((scope, row, frozenset(), {}))

    if rows:
        session.add_all(rows)
    session.info.setdefault(_PENDING_KEY, []).extend(pending)


@event.listens_for(Session, "after_commit")
def _publish_staged(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Cannot publish realtime events without a running event loop")
        return
    task = loop.create_task(_flush(pending))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@event.listens_for(Session, "after_rollback")
def _drop_staged(session: Session) -> None:
    session.info.pop(_STAGED_KEY, None)
    session.info.pop(_PENDING_KEY, None)


async def _flush(
    pending: list[tuple[Scope, WorkspaceEvent | None, frozenset[Resource], dict[str, list[int]]]],
) -> None:
    # Invariant 3: every local cache drop completes before the first publish,
    # so a client reacting to the event cannot re-read what we just staled.
    if _cache_invalidator is not None:
        for scope, _row, resources, entity_ids in pending:
            if not resources:
                continue
            try:
                await _cache_invalidator(scope, resources, entity_ids)
            except Exception:
                logger.exception("Local cache invalidation failed", scope=str(scope), resources=sorted(resources))

    if _redis_url is None:
        logger.warning("Realtime not configured (configure_realtime); dropping publish")
        return

    for _scope, row, _resources, _entity_ids in pending:
        if row is None:
            continue
        if row.occurred_at is None:
            row.occurred_at = datetime.now(UTC)
        envelope = _envelope(row)
        try:
            await publish_event_to_redis_url(_redis_url, topic=row.topic, envelope=envelope)
        except Exception:
            logger.exception("Failed to publish realtime event", topic=row.topic)


def _envelope(row: WorkspaceEvent) -> WorkspaceEventEnvelope:
    if row.id is None:
        # Non-durable domain event: no row was flushed, so there is no id and
        # no replay cursor. event_id=0 is the wire's marker for exactly that.
        return WorkspaceEventEnvelope(
            event_id=0,
            event_type=row.event_type,
            schema_version=row.schema_version,
            occurred_at=row.occurred_at or datetime.now(UTC),
            actor_user_id=row.actor_user_id,
            data=row.payload,
        )
    return event_to_envelope(row)


async def enqueue_invalidation_outbox(
    session: Any,
    *,
    scope: Scope,
    resources: Sequence[Resource],
    entity_ids: Mapping[str, Sequence[int]] | None = None,
) -> None:
    """Cross-service half of an invalidation: one outbox row, retried and DLQ'd.

    Redis pub/sub is at-most-once. For clients that is covered by the gateway's
    TTL and by cursor replay on resubscribe; for another service's cashews
    entries nothing covers it, which is why the cross-service path is the
    transactional outbox and not a second publish. Called by the owning service
    when a resource it stales is cached elsewhere too.
    """
    await enqueue_outbox_event(
        session,
        CacheInvalidatedEvent(
            scope_kind=str(scope.kind),
            scope_id=scope.id,
            resources=[str(r) for r in resources],
            entity_ids={key: [int(v) for v in values] for key, values in (entity_ids or {}).items()},
        ),
        exchange=CACHE_INVALIDATION_EXCHANGE,
        routing_key=f"cache.invalidated.{scope.kind}.{scope.id}",
    )
