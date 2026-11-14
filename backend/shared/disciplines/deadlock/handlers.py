"""The Deadlock rank collector's RPC handlers (``DisciplineSpec.collection_handlers``) — the same set as LoL's.

Reads are public; a Deadlock series is one per Steam account (no role, platform or queue; no LP or W/L). The admin
handlers gate on ``rank.read`` / ``rank.update``; ``workspace_id`` is both the authorization scope and the row filter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from shared.disciplines.deadlock import collector
from shared.models.identity.auth_user import AuthUser
from shared.models.ranks.rank import UserRankSnapshot
from shared.repository.ranks import RankAccountStateRepository, RankFetchLogRepository
from shared.rpc import common as c
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission
from shared.schemas import rank_collection as schemas

#: The window a history read covers when the caller names none.
DEFAULT_HISTORY = timedelta(days=365)


def authorize(user: AuthUser | None, data: dict, action: str) -> int | None:
    """Gate on ``rank.<action>`` and return the workspace scope (``None`` = every workspace, global grants only).

    Overwatch's rule (``overwatch/collector/handlers.py``), duplicated on purpose: modules never import each other.
    """
    if user is None:
        raise MissingIdentityError("no identity payload")
    c.require_active(user)
    workspace_id: int | None = c.q1(data, "workspace_id", int)
    if workspace_id is not None:
        ensure_workspace_permission(user, workspace_id, "rank", action)
        return workspace_id
    if not user.has_permission("rank", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: rank.{action} required")
    return None


def _dt(data: dict, key: str) -> datetime | None:
    raw = c.q1(data, key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid datetime for {key}") from exc


def _point(snap: UserRankSnapshot) -> schemas.RankHistoryPoint:
    return schemas.RankHistoryPoint(
        captured_at=snap.captured_at,
        rank_value=snap.rank_value,
        division=snap.division,
        tier=snap.tier,
        is_ranked=snap.is_ranked,
        season=snap.season,
    )


async def _series(session: AsyncSession, data: dict, **scope: int) -> list[schemas.RankSeries]:
    """Per account: the changes inside the window plus the row each series entered it with (no bucketing)."""
    snap = UserRankSnapshot
    date_to = _dt(data, "date_to") or datetime.now(UTC)
    date_from = _dt(data, "date_from") or date_to - DEFAULT_HISTORY
    where = [snap.discipline == collector.DISCIPLINE, *(getattr(snap, key) == value for key, value in scope.items())]
    window = await session.scalars(
        sa.select(snap).where(*where, snap.captured_at >= date_from, snap.captured_at <= date_to)
    )
    opening = await session.scalars(
        sa.select(snap)
        .where(*where, snap.captured_at < date_from)
        .ext(distinct_on(snap.social_account_id))
        .order_by(snap.social_account_id, snap.captured_at.desc())
    )
    grouped: dict[int, list[UserRankSnapshot]] = {}
    for row in [*opening.all(), *window.all()]:
        grouped.setdefault(row.social_account_id, []).append(row)
    out = []
    for account_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row.captured_at)
        last = rows[-1]
        out.append(
            schemas.RankSeries(
                social_account_id=account_id,
                handle=last.handle,
                role=None,
                platform=None,
                queue=None,
                points=[_point(row) for row in rows],
                current=_point(last),
                peak_rank_value=max((row.rank_value for row in rows if row.rank_value is not None), default=None),
                latest_captured_at=last.captured_at,
            )
        )
    return out


async def user_history(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    user_id = c.require_id(data)
    return schemas.RankHistoryResponse(
        user_id=user_id, series=await _series(session, data, user_id=user_id), generated_at=datetime.now(UTC)
    )


async def game_account_history(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    series = await _series(session, data, social_account_id=c.require_id(data))
    return schemas.RankHistoryResponse(user_id=None, series=series, generated_at=datetime.now(UTC))


async def user_current(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    user_id = c.require_id(data)
    snap = UserRankSnapshot
    rows = (
        await session.scalars(
            sa.select(snap)
            .where(snap.discipline == collector.DISCIPLINE, snap.user_id == user_id)
            .ext(distinct_on(snap.social_account_id))
            .order_by(snap.social_account_id, snap.captured_at.desc(), snap.id.desc())
        )
    ).all()
    ranks = [
        schemas.CurrentRank(
            social_account_id=s.social_account_id,
            handle=s.handle,
            role=None,
            platform=None,
            queue=None,
            rank_value=s.rank_value,
            division=s.division,
            tier=s.tier,
            is_ranked=s.is_ranked,
            season=s.season,
            captured_at=s.captured_at,
        )
        for s in rows
    ]
    return schemas.CurrentRanksResponse(user_id=user_id, ranks=ranks, generated_at=datetime.now(UTC))


async def fetch_log(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    workspace_id = authorize(user, data, "read")
    rows = await RankFetchLogRepository().list_recent(
        session,
        discipline=collector.DISCIPLINE,
        provider=SocialProvider.STEAM,
        workspace_id=workspace_id,
        status=c.q1(data, "status"),
        source=c.q1(data, "source"),
        before_id=c.q1(data, "before_id", int),
        limit=c.q1(data, "limit", int, 50),
    )
    return [schemas.FetchLogRead.model_validate(row) for row in rows]


async def stats(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    workspace_id = authorize(user, data, "read")
    raw = await RankAccountStateRepository().collection_stats(
        session,
        discipline=collector.DISCIPLINE,
        provider=SocialProvider.STEAM,
        workspace_id=workspace_id,
        invalid_error=collector.INVALID_ACCOUNT_ID_ERROR,
    )
    config = await collector.collection_config(session)
    fetch = raw["fetch_24h"]
    fetch_total = sum(fetch.values())
    errors = fetch.get("error", 0) + fetch.get("rate_limited", 0)
    tiers = raw["by_tier"]
    return schemas.RankCollectionStats(
        total=raw["total"],
        never_checked=raw["never_checked"],
        by_status=raw["by_status"],
        tier0=tiers.get(0, 0),
        tier1=tiers.get(1, 0),
        tier2=tiers.get(2, 0),
        coverage_24h=raw["coverage_24h"],
        coverage_7d=raw["coverage_7d"],
        last_success_at=raw["last_success_at"],
        fetch_24h=fetch,
        fetch_24h_total=fetch_total,
        error_rate_24h=round(errors / fetch_total, 4) if fetch_total else 0.0,
        enabled=config.enabled,
        scope=config.scope,
        interval_seconds=config.interval_seconds,
        rate_limit_per_minute=config.rate_limit_per_minute,
        # The worker's own client: an open circuit refuses every fetch before it leaves the process.
        upstream_base_url=collector.rank_client.base_url,
        upstream_circuit_state=collector.rank_client.circuit_breaker.state.value,
        invalid_handles_24h=raw["invalid_handles_24h"],
    )


async def user_collection(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    workspace_id = authorize(user, data, "read")
    rows = await RankAccountStateRepository().user_collection(
        session, c.require_id(data), provider=SocialProvider.STEAM, workspace_id=workspace_id
    )
    return [schemas.CollectionStatusRead(**row) for row in rows]


async def collect(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    workspace_id = authorize(user, data, "update")
    body = schemas.CollectTriggerRequest.model_validate(c.payload(data))
    enqueued = await collector.trigger_collection(
        session, user_id=body.user_id, social_account_ids=body.social_account_ids, workspace_id=workspace_id
    )
    return schemas.CollectTriggerResponse(enqueued=enqueued)


async def reenable_disabled(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    workspace_id = authorize(user, data, "update")
    body = schemas.ReenableDisabledRequest.model_validate(c.payload(data))
    config = await collector.collection_config(session)
    count = await RankAccountStateRepository().reenable_disabled(
        session,
        discipline=collector.DISCIPLINE,
        provider=SocialProvider.STEAM,
        interval_seconds=config.interval_seconds,
        only_previously_succeeded=body.only_previously_succeeded,
        workspace_id=workspace_id,
    )
    await session.commit()
    return schemas.ReenableDisabledResponse(reenabled=count)


HANDLERS = {
    "rank.user_history": user_history,
    "rank.game_account_history": game_account_history,
    "rank.user_current": user_current,
    "rank.fetch_log": fetch_log,
    "rank.stats": stats,
    "rank.user_collection": user_collection,
    "rank.collect": collect,
    "rank.reenable_disabled": reenable_disabled,
}
