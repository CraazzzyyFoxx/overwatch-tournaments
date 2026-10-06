"""Pickup-mix changes: one realtime signal plus one durable fact.

``emit_pickup_mix_changed`` is what EVERY mix mutation calls, in its own
transaction, and it does two things:

- A ``workspace.pickup_mix`` invalidation plus a ``pickup_mix.updated``
  broadcast on ``workspace:{id}:pickup_mix``, for the open web clients. The
  data event carries no row data -- only "something in this workspace's mixes
  changed" -- for the same reason ``subscription.updated`` does (see
  ``shared.services.subscriptions.realtime``):

  - A roster edit, a bench toggle, a rank correction and a newly-seeded host
    rank all collapse into the same two refetches on the consumer side (the
    add-players dialog's roster/rank queries, the mix panels' custom-game
    query), so there is nothing worth threading through that the client's own
    authoritative reload does not already answer.
  - Non-durable (``event_id=0``, no persisted row): a client that reconnects
    refetches anyway, so persisting one row per edit would buy nothing.

- A ``PickupMixChangedEvent`` outbox row on ``pickup_mix_changed``, for the
  Discord side. Durable because the signup card in a channel has no client to
  refetch on reconnect: the card is only as fresh as the last event that
  reached :mod:`src.services.mix_signup_projector`. It carries no state either
  -- the projector re-renders from the database.

Only balancer-service ever writes either signal (custom-game roster/lineup
edits, workspace rank writes), so it lives here rather than in ``shared``.
"""

from __future__ import annotations

from typing import Any

from shared.messaging.config import PICKUP_MIX_CHANGED_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import PickupMixChangedEvent
from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = ("PICKUP_MIX_UPDATED", "emit_pickup_mix_changed")

PICKUP_MIX_UPDATED = "pickup_mix.updated"


async def emit_pickup_mix_changed(
    session: Any,
    workspace_id: int,
    *,
    custom_game_id: int | None,
    change: str,
    actor_user_id: int | None = None,
) -> None:
    """Stage both signals on the transaction that made the edit.

    ``change`` (``roster``/``rank``/``member``/``balance``/...) names which
    mutation fired and is diagnostic only -- every consumer re-reads the same
    state regardless. ``custom_game_id`` is the mix that changed, or ``None``
    for a workspace-wide change (a renamed player, a corrected rank) that every
    mix of the workspace shows.

    Must run before the caller's ``commit()``: ``emit`` publishes from the
    session's ``after_commit`` and the outbox row is written in this very
    transaction, so a rolled-back edit announces nothing.
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
    await enqueue_outbox_event(
        session,
        PickupMixChangedEvent(
            workspace_id=int(workspace_id),
            custom_game_id=custom_game_id,
            change=change,
        ),
        exchange="",
        routing_key=PICKUP_MIX_CHANGED_QUEUE.name,
    )
