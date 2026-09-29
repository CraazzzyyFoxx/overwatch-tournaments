"""Typed-RPC handlers for the OverFast rank domain.

Mirrors the public rank-history reads in ``src/routes/rank_history.py`` and the
admin collection routes in ``src/routes/admin/rank_collection.py``. Reads are
public (AuthNone).

The admin handlers gate on the RBAC permissions ``rank.read`` / ``rank.update``,
not on a role name. ``workspace_id`` doubles as the authorization scope and the
data filter: pass it and the caller needs the permission *in that workspace*
(which a workspace owner or admin holds via their wildcard) and sees only the
battle tags of that workspace's players; omit it and the caller needs the same
permission globally, which is what buys the cross-workspace view. Rank rows have
no workspace column of their own — the hop is
``social_account -> players.user -> workspace_member`` (see
``overwatch_rank.service.workspace_account_ids``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src import schemas
from src.core import db
from src.domain.overwatch_rank import resolve_date_range
from src.services.overwatch_rank import admin as rank_admin
from src.services.overwatch_rank import queries

from . import _common as c

_SF = db.async_session_maker


def _dt(data: dict, key: str) -> datetime | None:
    raw = c.q1(data, key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid datetime for {key}") from exc


def _authorize(data: dict, action: str) -> int | None:
    """Gate on ``rank.<action>`` and return the workspace scope.

    ``None`` means "every workspace", and only a global permission holder ever
    gets it — a workspace-scoped grant cannot widen itself into a cross-tenant
    read by dropping the query param.
    """
    user = c.actor(data)
    c.require_active(user)
    workspace_id: int | None = c.q1(data, "workspace_id", int)
    if workspace_id is not None:
        ensure_workspace_permission(user, workspace_id, "rank", action)
        return workspace_id
    if not user.has_permission("rank", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: rank.{action} required")
    return None


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.rank.user_history")
    async def _user_history(data: dict, msg: RabbitMessage) -> dict:
        # GET /users/{user_id}/rank-history (public).
        async def op(session: Any) -> Any:
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

        return await c.envelope(logger, "rank.user_history", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.battle_tag_history")
    async def _battle_tag_history(data: dict, msg: RabbitMessage) -> dict:
        # GET /battle-tags/{battle_tag_id}/rank-history (public; path id = social_account_id).
        async def op(session: Any) -> Any:
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

        return await c.envelope(logger, "rank.battle_tag_history", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.user_current")
    async def _user_current(data: dict, msg: RabbitMessage) -> dict:
        # GET /users/{user_id}/current-ranks (public).
        async def op(session: Any) -> Any:
            user_id = c.require_id(data)
            ranks = await queries.get_current_ranks(session, user_id=user_id, platform=c.q1(data, "platform"))
            return schemas.CurrentRanksResponse(user_id=user_id, ranks=ranks, generated_at=datetime.now(UTC))

        return await c.envelope(logger, "rank.user_current", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.fetch_log")
    async def _fetch_log(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/rank/fetch-log — rank.read, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "read")
            rows = await rank_admin.list_fetch_log(
                session,
                workspace_id=workspace_id,
                status=c.q1(data, "status"),
                source=c.q1(data, "source"),
                before_id=c.q1(data, "before_id", int),
                limit=c.q1(data, "limit", int, 50),
            )
            return [schemas.FetchLogRead.model_validate(row) for row in rows]

        return await c.envelope(logger, "rank.fetch_log", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.stats")
    async def _stats(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/rank/stats — rank.read, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "read")
            result = await rank_admin.get_collection_stats(session, workspace_id=workspace_id)
            return schemas.RankCollectionStats.model_validate(result)

        return await c.envelope(logger, "rank.stats", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.user_collection")
    async def _user_collection(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/rank/users/{user_id}/collection — rank.read, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "read")
            rows = await rank_admin.get_user_collection_status(session, c.require_id(data), workspace_id=workspace_id)
            return [schemas.CollectionStatusRead(**row) for row in rows]

        return await c.envelope(logger, "rank.user_collection", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.collect")
    async def _collect(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/rank/collect — rank.update, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "update")
            body = schemas.CollectTriggerRequest.model_validate(c.payload(data))
            enqueued = await rank_admin.trigger_collection(
                session,
                user_id=body.user_id,
                social_account_ids=body.social_account_ids,
                workspace_id=workspace_id,
            )
            return schemas.CollectTriggerResponse(enqueued=enqueued)

        return await c.envelope(logger, "rank.collect", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.reenable_disabled")
    async def _reenable_disabled(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/rank/reenable-disabled — rank.update, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "update")
            body = schemas.ReenableDisabledRequest.model_validate(c.payload(data))
            count = await rank_admin.reenable_disabled(
                session,
                only_previously_succeeded=body.only_previously_succeeded,
                workspace_id=workspace_id,
            )
            return schemas.ReenableDisabledResponse(reenabled=count)

        return await c.envelope(logger, "rank.reenable_disabled", op, session_factory=_SF)
