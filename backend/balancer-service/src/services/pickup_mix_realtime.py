"""Thin realtime signal for pickup-mix roster/rank changes.

A ``workspace.pickup_mix`` invalidation plus a ``pickup_mix.updated`` broadcast
on ``workspace:{id}:pickup_mix``. The data event carries no row data -- only
"something in this workspace's mixes changed" -- for the same reason
``subscription.updated`` does (see ``shared.services.subscriptions.realtime``):

- A roster edit, a bench toggle, a rank correction and a newly-seeded host rank
  all collapse into the same two refetches on the consumer side (the
  add-players dialog's roster/rank queries, the mix panels' custom-game query),
  so there is nothing worth threading through that the client's own
  authoritative reload does not already answer.
- Non-durable (``event_id=0``, no persisted row): a client that reconnects
  refetches anyway, so persisting one row per edit would buy nothing.

Only balancer-service ever writes this signal (custom-game roster/lineup
edits, workspace rank writes), so it lives here rather than in ``shared``.
"""

from __future__ import annotations

from typing import Any

from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = ("PICKUP_MIX_UPDATED", "emit_pickup_mix_updated")

PICKUP_MIX_UPDATED = "pickup_mix.updated"


async def emit_pickup_mix_updated(
    session: Any,
    workspace_id: int,
    *,
    change: str,
    actor_user_id: int | None = None,
) -> None:
    """Stage the signal on the transaction that made the edit.

    ``change`` (``roster``/``rank``/``member``/``balance``/...) names which
    mutation fired and is diagnostic only -- every consumer refetches the same
    two query families regardless.

    Must run before the caller's ``commit()``: ``emit`` publishes from the
    session's ``after_commit``, so a rolled-back edit announces nothing.
    """
    await emit(
        session,
        scope=Scope.workspace(int(workspace_id)),
        invalidates=[Resource.WORKSPACE_PICKUP_MIX],
        data=DomainEvent(
            domain="pickup_mix",
            event_type=PICKUP_MIX_UPDATED,
            payload={"workspace_id": int(workspace_id), "change": change},
            durable=False,
        ),
        actor_user_id=actor_user_id,
    )
