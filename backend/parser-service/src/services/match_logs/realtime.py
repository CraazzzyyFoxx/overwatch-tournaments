"""Thin realtime signal for the admin match-log monitor.

Stages a ``workspace.logs`` invalidation plus a non-durable ``logs.updated``
data event on the workspace-scoped topic whenever a match-log record reaches a
terminal state. The gateway relays the data event to WS subscribers (the admin
log monitor), which refetch ``/admin/logs/history``. Neither carries record
data, so workspace membership (the existing ``workspace:*:*`` topic ACL) is
sufficient — the actual log data is still gated by ``log.read`` on the refetch.

Unlike the durable encounter map-veto path the data event persists no row and
has no replay cursor: the monitor always does an initial fetch on subscribe, so
missed signals self-heal.
"""

from __future__ import annotations

from typing import Any

from shared.services.realtime import DomainEvent, Resource, Scope, emit

LOGS_UPDATED = "logs.updated"


async def emit_logs_updated(session: Any, workspace_id: int | None, *, change: str = "log_changed") -> None:
    """Stage the signal on the transaction that moved the record.

    ``change`` (``done``/``failed``/``requeued``) is diagnostic only -- every
    consumer refetches the same history query regardless of which one fired.

    Must run before the caller's ``commit()``: ``emit`` publishes from the
    session's ``after_commit``, so a record whose state change rolls back
    announces nothing.
    """
    if not workspace_id:
        return
    await emit(
        session,
        scope=Scope.workspace(int(workspace_id)),
        invalidates=[Resource.WORKSPACE_LOGS],
        data=DomainEvent(
            domain="logs",
            event_type=LOGS_UPDATED,
            payload={"workspace_id": int(workspace_id), "change": change},
            durable=False,
        ),
    )
