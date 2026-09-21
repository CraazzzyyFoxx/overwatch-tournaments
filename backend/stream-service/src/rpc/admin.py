"""Admin subscribers (``rpc.stream.repoll``, ``rpc.stream.health``).

``repoll`` serves ``POST /api/streams/tournament/{tournament_id}/repoll`` — the
operator escape hatch when a live badge looks wrong and waiting out the interval
is not acceptable.

The handler does NOT run a poll tick. A tick walks every active tournament and
talks to Helix over the proxy; the gateway puts a deadline on every RPC call
(``DeadlineDropMiddleware``), so doing that work inline would time out the request
and leave the caller unable to tell a slow poll from a failed one. Instead it
clears the poll cursor (``stream:poll:last_run``), which makes the next scheduler
heartbeat — at most ``SCHEDULER_TICK_SECONDS`` away — consider a tick due. That is
precisely what 202 Accepted describes, and why the route declares it.

``health`` serves ``GET /api/streams/health`` and is the reason the tick records
its outcome at all: every Helix failure is swallowed so an outage cannot kill the
scheduler, which means a misconfigured poller is indistinguishable from a working
one from the outside. It reads Redis only — no Postgres — and requires a GLOBAL
``stream.read``, because there is one poller for the whole platform and a
workspace-scoped grant must not be able to read platform-wide state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared import quota
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import TournamentRepository
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_audit
from shared.services.settings_provider import settings_provider
from src.core import db
from src.core.config import settings
from src.schemas.stream import StreamPollHealthRead, StreamRepollRead
from src.services.state import StreamStateStore

from . import _common as c
from ._clients import realtime_redis

__all__ = ("health", "register", "repoll")

_tournaments = TournamentRepository()


async def health(session: AsyncSession, data: dict[str, Any]) -> StreamPollHealthRead:
    """Report the last tick's outcome next to the config that produced it."""
    user = c.actor(data)
    c.require_active(user)
    # Deliberately NOT ensure_workspace_permission: the poller is platform-wide,
    # so a workspace-scoped grant would read numbers that are not about its
    # workspace. Only a global holder (or a superuser) sees this.
    if not user.has_permission("stream", "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: stream.read required")

    cfg = await settings_provider.get_stream_collection_config(session)

    recorded = await StreamStateStore(realtime_redis).read_poll_status() or {}
    ran_at = recorded.get("ran_at")
    return StreamPollHealthRead(
        enabled=cfg.enabled,
        interval_seconds=cfg.interval_seconds,
        batch_size=cfg.batch_size,
        status=recorded.get("status"),
        last_run_at=datetime.fromtimestamp(float(ran_at), tz=UTC) if ran_at is not None else None,
        tournaments_active=recorded.get("tournaments_active"),
        tournaments_updated=recorded.get("tournaments_updated"),
        channels_polled=recorded.get("channels_polled"),
        live_channels=recorded.get("live_channels"),
        ratelimit_remaining=recorded.get("ratelimit_remaining"),
        credentials_configured=bool(settings.twitch_client_id and settings.twitch_client_secret),
    )


async def repoll(session: AsyncSession, data: dict[str, Any]) -> StreamRepollRead:
    """Authorize, journal, then make the next heartbeat due."""
    tournament_id = c.require_path_int(data, "tournament_id")
    workspace_id = c.require_query_int(data, "workspace_id")
    user = c.actor(data)
    c.require_active(user)
    ensure_workspace_permission(user, workspace_id, "stream", "update")

    # The permission above proves the caller may re-poll `workspace_id`; it says
    # nothing about which workspace owns THIS tournament. Without this check an
    # admin of their own workspace could trigger polling for someone else's
    # tournament by passing a foreign tournament_id.
    owner_workspace_id = await _tournaments.get_workspace_id(session, tournament_id)
    if owner_workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    if int(owner_workspace_id) != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tournament does not belong to this workspace",
        )

    # Metered before anything durable happens. A re-poll clears a GLOBAL cursor,
    # so each call costs one extra Helix round of ≤5 requests per ACTIVE
    # tournament (see the cursor note below) — against the 800 points/min app
    # bucket that is SHARED with identity-service's OAuth sign-ins. Draining it
    # from here does not just stall stream badges, it breaks logins, which is why
    # this is rate-limited rather than left to the tick's own
    # `ratelimit_remaining` gate. After the authorization and ownership checks: a
    # rejected call must not spend quota.
    await quota.charge(user, "stream.repoll", workspace_id=workspace_id)

    await record_audit(
        session,
        action="stream.repoll",
        source="admin",
        actor=user,
        # Snapshotted so the row stays readable once the account is gone: there is
        # no FK on actor_auth_user_id, so a reader's join resolves nothing then.
        actor_label=user.username,
        # The very value ensure_workspace_permission was checked against, reused
        # rather than re-derived from the tournament: if the two could disagree the
        # row would claim an action was authorized in a workspace where it was not.
        workspace_id=workspace_id,
        entity_type="tournament",
        entity_id=tournament_id,
        # Put on the envelope's top level by the gateway, not inside `payload`.
        ip_address=data.get("ip_address"),
        user_agent=data.get("user_agent"),
    )
    # record_audit never commits, so the row lands in THIS transaction. Committing
    # after it is part of the contract (``shared/services/audit.py``): the other
    # order puts the row in a separate transaction and loses atomicity silently.
    await session.commit()

    # Redis last, after the durable part is safe: a cleared cursor costs one early
    # tick, whereas a committed audit row for a re-poll that never happened would
    # be a lie in the journal.
    #
    # ponytail: the cursor is global, so this re-polls EVERY active tournament, not
    # just this one. Ceiling: one extra Helix round of ≤5 requests per active
    # tournament, against an 800 points/min bucket — invisible at the documented
    # scale, and the tick's own `ratelimit_remaining` gate stops it if it is not.
    # Upgrade path if operators start hammering this: a `stream:poll:due` SET of
    # tournament ids that `run_poll_tick` drains ahead of the interval check.
    await StreamStateStore(realtime_redis).clear_last_run()
    return StreamRepollRead(tournament_id=tournament_id)


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    @broker.subscriber("rpc.stream.repoll")
    async def _repoll(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await repoll(session, data)

        return await c.envelope(logger, "repoll", op, session_factory=sf)

    @broker.subscriber("rpc.stream.health")
    async def _health(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await health(session, data)

        return await c.envelope(logger, "health", op, session_factory=sf)
