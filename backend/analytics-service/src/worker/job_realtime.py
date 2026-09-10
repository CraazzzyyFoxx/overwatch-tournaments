"""Stage analytics-job lifecycle events on the job's own transaction."""

from __future__ import annotations

import typing

from sqlalchemy.ext.asyncio import AsyncSession

from shared.jobs import Status
from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = ("emit_job_event",)

#: Statuses after which the job list is a different list. A progress tick is not
#: one of them: the row's ``progress`` moves, but every reader that cares is
#: already watching the live event, and invalidating per stage would drop the
#: whole workspace's job cache several times per job.
_TERMINAL = frozenset({Status.SUCCEEDED, Status.FAILED})


async def emit_job_event(
    session: AsyncSession,
    *,
    job_id: int,
    workspace_id: int | None,
    tournament_id: int,
    kind: str,
    status: str,
    progress: dict[str, typing.Any] | None = None,
    error: str | None = None,
    actor_user_id: int | None = None,
) -> None:
    if workspace_id is None:
        return
    terminal = status in _TERMINAL
    await emit(
        session,
        scope=Scope.workspace(int(workspace_id)),
        invalidates=[Resource.WORKSPACE_ANALYTICS_JOBS] if terminal else (),
        data=DomainEvent(
            domain="analytics_jobs",
            event_type=f"analytics_job.{status}",
            payload={
                "job_id": int(job_id),
                "tournament_id": int(tournament_id),
                "workspace_id": int(workspace_id),
                "kind": kind,
                "status": status,
                "progress": progress or {},
                "error": error,
            },
            # A progress tick is a live readout: a client that reconnects reads
            # the job row and sees where it got to, so a replay cursor for the
            # ticks it missed would only replay a stale percentage.
            durable=terminal,
        ),
        actor_user_id=actor_user_id,
    )
