"""Collection RPC handlers of the OverFast rank domain, served through ``DisciplineSpec.collection_handlers``.

Mirrors the public rank-history reads and the admin collection operations. Reads are public (no caller).

The admin handlers gate on the RBAC permissions ``rank.read`` / ``rank.update``, not on a role name. ``workspace_id``
doubles as the authorization scope and the data filter: pass it and the caller needs the permission *in that workspace*
(which a workspace owner or admin holds via their wildcard) and sees only the battle tags of that workspace's players;
omit it and the caller needs the same permission globally, which is what buys the cross-workspace view. Rank rows have
no workspace column of their own — the hop is ``social_account -> players.user -> workspace_member`` (see
``service.workspace_account_ids``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from shared.models.identity.auth_user import AuthUser
from shared.repository.ranks import workspace_account_ids
from shared.rpc import common as c
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission
from shared.schemas import rank_collection as schemas

from . import admin, portrait, queries
from .domain import resolve_date_range

#: Players one signals read may ask for: a registration list page.
MAX_SIGNAL_USERS = 200


def _dt(data: dict, key: str) -> datetime | None:
    raw = c.q1(data, key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid datetime for {key}") from exc


def authorize(user: AuthUser | None, data: dict, action: str) -> int | None:
    """Gate on ``rank.<action>`` and return the workspace scope.

    ``None`` means "every workspace", and only a global permission holder ever
    gets it — a workspace-scoped grant cannot widen itself into a cross-tenant
    read by dropping the query param.
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


async def user_history(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /users/{user_id}/rank-history (public).
    user_id = c.require_id(data)
    granularity = c.q1(data, "granularity", str, "daily")
    date_from, date_to = resolve_date_range(granularity, _dt(data, "date_from"), _dt(data, "date_to"))
    series = await queries.get_rank_series(
        session,
        user_id=user_id,
        social_account_id=c.q1(data, "social_account_id", int),
        platform=c.q1(data, "platform"),
        role=c.q1(data, "role"),
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
    )
    return schemas.RankHistoryResponse(user_id=user_id, series=series, generated_at=datetime.now(UTC))


async def game_account_history(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /game-accounts/{id}/rank-history (public; path id = social_account_id).
    social_account_id = c.require_id(data)
    granularity = c.q1(data, "granularity", str, "daily")
    date_from, date_to = resolve_date_range(granularity, _dt(data, "date_from"), _dt(data, "date_to"))
    series = await queries.get_rank_series(
        session,
        social_account_id=social_account_id,
        platform=c.q1(data, "platform"),
        role=c.q1(data, "role"),
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
    )
    return schemas.RankHistoryResponse(user_id=None, series=series, generated_at=datetime.now(UTC))


async def user_current(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /users/{user_id}/current-ranks (public).
    user_id = c.require_id(data)
    ranks = await queries.get_current_ranks(session, user_id=user_id, platform=c.q1(data, "platform"))
    return schemas.CurrentRanksResponse(user_id=user_id, ranks=ranks, generated_at=datetime.now(UTC))


async def fetch_log(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /admin/rank/fetch-log — rank.read, scoped by workspace_id.
    workspace_id = authorize(user, data, "read")
    rows = await admin.list_fetch_log(
        session,
        workspace_id=workspace_id,
        status=c.q1(data, "status"),
        source=c.q1(data, "source"),
        before_id=c.q1(data, "before_id", int),
        limit=c.q1(data, "limit", int, 50),
    )
    return [schemas.FetchLogRead.model_validate(row) for row in rows]


async def stats(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /admin/rank/stats — rank.read, scoped by workspace_id.
    workspace_id = authorize(user, data, "read")
    result = await admin.get_collection_stats(session, workspace_id=workspace_id)
    return schemas.RankCollectionStats.model_validate(result)


async def user_collection(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /admin/rank/users/{user_id}/collection — rank.read, scoped by workspace_id.
    workspace_id = authorize(user, data, "read")
    rows = await admin.get_user_collection_status(session, c.require_id(data), workspace_id=workspace_id)
    return [schemas.CollectionStatusRead(**row) for row in rows]


async def collect(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # POST /admin/rank/collect — rank.update, scoped by workspace_id.
    workspace_id = authorize(user, data, "update")
    body = schemas.CollectTriggerRequest.model_validate(c.payload(data))
    enqueued = await admin.trigger_collection(
        session,
        user_id=body.user_id,
        social_account_ids=body.social_account_ids,
        workspace_id=workspace_id,
    )
    return schemas.CollectTriggerResponse(enqueued=enqueued)


async def reenable_disabled(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # POST /admin/rank/reenable-disabled — rank.update, scoped by workspace_id.
    workspace_id = authorize(user, data, "update")
    body = schemas.ReenableDisabledRequest.model_validate(c.payload(data))
    count = await admin.reenable_disabled(
        session,
        only_previously_succeeded=body.only_previously_succeeded,
        workspace_id=workspace_id,
    )
    return schemas.ReenableDisabledResponse(reenabled=count)


async def user_career(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /users/{user_id}/career (public): the player's accounts as the game shows them; a closed profile, no career.
    user_id = c.require_id(data)
    accounts = await portrait.career_accounts(session, [user_id], visible_only=True)
    return schemas.CareerResponse(user_id=user_id, accounts=accounts[user_id], generated_at=datetime.now(UTC))


async def career_signals(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    # GET /admin/rank/career-signals?user_id=..&user_id=.. — rank.read, scoped by workspace_id.
    workspace_id = authorize(user, data, "read")
    try:
        user_ids = list(dict.fromkeys(int(raw) for raw in c.q(data, "user_id") or ()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="user_id must be an integer") from exc
    if not user_ids or len(user_ids) > MAX_SIGNAL_USERS:
        raise HTTPException(status_code=422, detail=f"between 1 and {MAX_SIGNAL_USERS} user_id values")
    scope = None if workspace_id is None else workspace_account_ids(workspace_id, provider=SocialProvider.BATTLENET)
    now = datetime.now(UTC)
    users = await portrait.career_signals(session, user_ids, now=now, account_scope=scope)
    return schemas.CareerSignalsResponse(users=users, generated_at=now)


HANDLERS = {
    "rank.user_history": user_history,
    "rank.game_account_history": game_account_history,
    "rank.user_current": user_current,
    "rank.user_career": user_career,
    "rank.fetch_log": fetch_log,
    "rank.stats": stats,
    "rank.user_collection": user_collection,
    "rank.career_signals": career_signals,
    "rank.collect": collect,
    "rank.reenable_disabled": reenable_disabled,
}
