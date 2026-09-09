"""Realtime fan-out for admin registration edits.

Every admin mutation of a tournament's registrations announces itself on
``tournament:{id}:balancer`` so that everyone with the balancer page open
refetches the live list. That signal is DATA for the admin tool; the staleness
of the public participants list travels separately, as the
``tournament.registrations`` resource on the invalidation topic — the two used
to be conflated, which is how a balancer export came to invalidate nothing
public at all.

The former shape — a fire-and-forget task publishing from its own short-lived
session after the caller had already committed — is gone with the rest of the
per-call-site transports: it could publish an event for a transaction that
later failed, and its own docstring had to explain the ordering caveat that
riding the caller's transaction now removes.
"""

from __future__ import annotations

from typing import Any

from shared.services.balancer_realtime import BALANCER_REGISTRATIONS_CHANGED
from shared.services.realtime import DomainEvent, Scope, emit

__all__ = ("emit_balancer_registrations_changed",)


async def emit_balancer_registrations_changed(
    session: Any,
    tournament_id: int,
    *,
    actor_user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Stage the admin-tool signal. Call before the commit that owns the write."""
    await emit(
        session,
        scope=Scope.tournament(tournament_id),
        data=DomainEvent(
            domain="balancer",
            event_type=BALANCER_REGISTRATIONS_CHANGED,
            payload=payload or {},
        ),
        actor_user_id=actor_user_id,
    )
