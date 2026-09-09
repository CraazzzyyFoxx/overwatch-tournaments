"""Realtime fan-out for balancer-service edits and job lifecycle.

Everything here is DATA on the tournament-scoped ``tournament:{id}:balancer``
topic: what the admin tool renders, never what a cache should drop. The
staleness an export causes is announced separately, by the export's own call
site, as a tournament-scoped invalidation.

Two families:

* data-edit signals (``balancer.balance_saved`` / ``balancer.teams_changed`` /
  ``balancer.config_changed``) — durable, so a reconnecting admin replays them;
* job lifecycle (``balancer_job.*``) — durable for the queued/running/
  succeeded/failed transitions, non-durable for the high-frequency progress
  ticks, which a late joiner re-derives from the REST job-status snapshot.

Every call stages on the CALLER's session and is published by ``emit``'s
after-commit hook. The module used to open its own short-lived session per
event and fire the publish off as a detached task — which meant an event could
describe state its own transaction never committed, and could outlive it.
"""

from __future__ import annotations

from typing import Any

from shared.services.balancer_realtime import BALANCER_JOB_PROGRESS
from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = ("EXPORT_RESOURCES", "emit_balancer_data", "emit_job_lifecycle", "emit_job_progress")

# What every path through ``TeamMaterializationService`` stales: it DELETEs and
# re-INSERTs tournament.team / player / standing, so the teams list, the
# standings hanging off them and the set of sections the tournament page has all
# move at once. app-service caches the same three, which is why each of these
# call sites also enqueues the cross-service outbox row.
EXPORT_RESOURCES = (Resource.TOURNAMENT_TEAMS, Resource.TOURNAMENT_STANDINGS, Resource.TOURNAMENT_STRUCTURE)
_DOMAIN = "balancer"


async def emit_balancer_data(
    session: Any,
    tournament_id: int,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    actor_user_id: int | None = None,
) -> None:
    """Stage a ``balancer.*_changed`` data-edit broadcast.

    Call before the commit that owns the edit — including when that commit
    belongs to the service being called (``team_materialization.run`` and the
    admin service both own their boundary), in which case staging happens
    before the call rather than after it.
    """
    await emit(
        session,
        scope=Scope.tournament(tournament_id),
        data=DomainEvent(domain=_DOMAIN, event_type=event_type, payload=payload or {}),
        actor_user_id=actor_user_id,
    )


async def emit_job_lifecycle(
    session: Any,
    tournament_id: int,
    event_type: str,
    *,
    job_id: str,
    status: str,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
    actor_user_id: int | None = None,
) -> None:
    """Stage a durable ``balancer_job.*`` lifecycle transition.

    Durable so a late joiner catches up via cursor replay; the transitions are
    few and strictly ordered, unlike the progress ticks below.
    """
    await emit(
        session,
        scope=Scope.tournament(tournament_id),
        data=DomainEvent(
            domain=_DOMAIN,
            event_type=event_type,
            payload={
                "job_id": job_id,
                "status": status,
                "progress": progress or {},
                "error": error,
            },
        ),
        actor_user_id=actor_user_id,
    )


async def emit_job_progress(
    session: Any,
    tournament_id: int,
    *,
    job_id: str,
    status: str,
    progress: dict[str, Any] | None,
) -> None:
    """Stage an ephemeral ``balancer_job.progress`` tick.

    Not durable: progress is high-frequency and transient, and persisting it
    would fill the replay log with ticks no reconnecting client needs — it sees
    the last durable lifecycle state plus the next tick.
    """
    await emit(
        session,
        scope=Scope.tournament(tournament_id),
        data=DomainEvent(
            domain=_DOMAIN,
            event_type=BALANCER_JOB_PROGRESS,
            payload={
                "tournament_id": int(tournament_id),
                "job_id": job_id,
                "status": status,
                "progress": progress or {},
            },
            durable=False,
        ),
    )
