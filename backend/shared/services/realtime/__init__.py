"""The realtime rail: one publication primitive, one invalidation vocabulary.

Design: docs/plans/2026-09-09-unified-event-delivery.md
"""

from shared.services.realtime.emit import (
    INVALIDATION_EVENT_TYPE,
    DomainEvent,
    configure_realtime,
    emit,
    enqueue_invalidation_outbox,
)
from shared.services.realtime.resources import (
    MANIFEST_PATH,
    Resource,
    load_manifest,
    route_refresh_resources,
    scope_kind_of,
)
from shared.services.realtime.scope import Scope, ScopeKind

__all__ = (
    "INVALIDATION_EVENT_TYPE",
    "MANIFEST_PATH",
    "DomainEvent",
    "Resource",
    "Scope",
    "ScopeKind",
    "configure_realtime",
    "emit",
    "enqueue_invalidation_outbox",
    "load_manifest",
    "route_refresh_resources",
    "scope_kind_of",
)
