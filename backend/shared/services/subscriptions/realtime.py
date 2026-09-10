"""Realtime signal for subscription-entitlement changes.

A thin ``subscription.updated`` on ``workspace:{id}:subscriptions``, plus the
``workspace.subscriptions`` invalidation that says WHAT went stale. The data
event carries no verdict and no user id -- only "something in this workspace
changed" -- for two reasons:

- **One publish per resolve pass, not per patron.** A sweep of 200 registrants
  that flips 40 verdicts must not fan out 40 frames to every open admin page. The
  resolver folds the whole pass into a single signal (see
  ``SubscriptionResolver.resolve``), so the cost is bounded by passes, not people.
- **Nothing to leak and nothing to replay.** The topic is workspace-member gated,
  but a signal that carries no state cannot leak who is subscribed even so, and
  the authoritative read is still permission-gated on the refetch. Non-durable
  (``event_id=0``, no ``realtime.workspace_event`` row) for the same reason as
  ``logs.updated``: a client that reconnects refetches anyway, so persisting a row
  per changed patron would buy nothing.

Both writers of entitlements reach it through the resolver -- tournament-service
(registration / check-in gates, code redemption) and parser-service (the
scheduled collector and the admin re-check) -- which is why this lives in
``shared`` rather than beside either one.
"""

from __future__ import annotations

from typing import Any

from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = (
    "SUBSCRIPTION_UPDATED",
    "SessionSubscriptionEventSink",
    "emit_subscriptions_updated",
)

SUBSCRIPTION_UPDATED = "subscription.updated"


async def emit_subscriptions_updated(
    session: Any,
    workspace_id: int | None,
    *,
    trigger: str = "checked",
) -> None:
    """Stage the signal on the transaction that wrote the entitlement.

    ``trigger`` is the collection trigger (``scheduled``/``registration``/
    ``check_in``/``manual``/``redeem``) so an operator watching the page can tell a
    background sweep from their own re-check. It is diagnostic only -- no consumer
    branches on it.

    Must run before the caller's ``commit()``: ``emit`` publishes from the
    session's ``after_commit``, which is also what retired the old "published
    microseconds before the commit, consumers debounce around it" caveat.
    """
    if not workspace_id:
        return
    await emit(
        session,
        scope=Scope.workspace(int(workspace_id)),
        invalidates=[Resource.WORKSPACE_SUBSCRIPTIONS],
        data=DomainEvent(
            domain="subscriptions",
            event_type=SUBSCRIPTION_UPDATED,
            payload={"workspace_id": int(workspace_id), "trigger": trigger},
            durable=False,
        ),
    )


class SessionSubscriptionEventSink:
    """``SubscriptionEventSink`` bound to the resolver's own session.

    A class rather than a bare callable so ``build_resolver`` can hand the
    resolver something that satisfies the protocol without the decision table
    knowing anything about how the signal travels.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def subscriptions_updated(self, *, workspace_id: int, trigger: str) -> None:
        await emit_subscriptions_updated(self._session, workspace_id, trigger=trigger)
