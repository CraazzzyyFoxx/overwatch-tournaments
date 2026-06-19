"""Typed-RPC handlers for the OverFast rank domain.

Mirrors the public rank-history reads in ``src/routes/rank_history.py`` and the
admin collection routes in ``src/routes/admin/rank_collection.py``. Reads are
public (AuthNone); admin routes require the global ``admin`` role (gated here,
mirroring the ``require_role("admin")`` router dependency).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from faststream.rabbit import RabbitMessage

from src import schemas
from src.core import db
from src.routes.rank_history import _resolve_date_range
from src.schemas.admin import rank_collection as rc_schemas
from src.services.overwatch_rank import admin as rank_admin
from src.services.overwatch_rank import read_service

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


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.rank.user_history")
    async def _user_history(data: dict, msg: RabbitMessage) -> dict:
        # GET /users/{user_id}/rank-history (public).
        async def op(session: Any) -> Any:
            user_id = c.require_id(data)
            granularity = c.q1(data, "granularity", str, "daily")
            date_from, date_to = _resolve_date_range(granularity, _dt(data, "date_from"), _dt(data, "date_to"))
            service_granularity = "daily" if granularity == "daily" else "raw"
            series = await read_service.get_rank_series(
                session,
                user_id=user_id,
                battle_tag_id=c.q1(data, "battle_tag_id", int),
                platform=c.q1(data, "platform"),
                role=c.q1(data, "role"),
                date_from=date_from,
                date_to=date_to,
                granularity=service_granularity,
            )
            return schemas.RankHistoryResponse(user_id=user_id, series=series, generated_at=datetime.now(UTC))

        return await c.envelope(logger, "rank.user_history", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.battle_tag_history")
    async def _battle_tag_history(data: dict, msg: RabbitMessage) -> dict:
        # GET /battle-tags/{battle_tag_id}/rank-history (public).
        async def op(session: Any) -> Any:
            battle_tag_id = c.require_id(data)
            granularity = c.q1(data, "granularity", str, "daily")
            date_from, date_to = _resolve_date_range(granularity, _dt(data, "date_from"), _dt(data, "date_to"))
            service_granularity = "daily" if granularity == "daily" else "raw"
            series = await read_service.get_rank_series(
                session,
                battle_tag_id=battle_tag_id,
                platform=c.q1(data, "platform"),
                role=c.q1(data, "role"),
                date_from=date_from,
                date_to=date_to,
                granularity=service_granularity,
            )
            return schemas.RankHistoryResponse(user_id=None, series=series, generated_at=datetime.now(UTC))

        return await c.envelope(logger, "rank.battle_tag_history", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.user_current")
    async def _user_current(data: dict, msg: RabbitMessage) -> dict:
        # GET /users/{user_id}/current-ranks (public).
        async def op(session: Any) -> Any:
            user_id = c.require_id(data)
            ranks = await read_service.get_current_ranks(session, user_id=user_id, platform=c.q1(data, "platform"))
            return schemas.CurrentRanksResponse(user_id=user_id, ranks=ranks, generated_at=datetime.now(UTC))

        return await c.envelope(logger, "rank.user_current", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.fetch_log")
    async def _fetch_log(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/rank/fetch-log — require_role("admin").
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")
            rows = await rank_admin.list_fetch_log(
                session,
                status=c.q1(data, "status"),
                source=c.q1(data, "source"),
                before_id=c.q1(data, "before_id", int),
                limit=c.q1(data, "limit", int, 50),
            )
            return [rc_schemas.FetchLogRead.model_validate(row) for row in rows]

        return await c.envelope(logger, "rank.fetch_log", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.user_collection")
    async def _user_collection(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/rank/users/{user_id}/collection — require_role("admin").
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")
            rows = await rank_admin.get_user_collection_status(session, c.require_id(data))
            return [rc_schemas.CollectionStatusRead(**row) for row in rows]

        return await c.envelope(logger, "rank.user_collection", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.rank.collect")
    async def _collect(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/rank/collect — require_role("admin").
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")
            body = rc_schemas.CollectTriggerRequest.model_validate(c.payload(data))
            enqueued = await rank_admin.trigger_collection(
                session, user_id=body.user_id, battle_tag_ids=body.battle_tag_ids
            )
            return rc_schemas.CollectTriggerResponse(enqueued=enqueued)

        return await c.envelope(logger, "rank.collect", op, session_factory=_SF)
