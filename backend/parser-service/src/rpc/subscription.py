"""Typed-RPC handlers for subscription-collection admin.

The subscription counterpart of ``rpc/rank.py``: collection health, the
append-only check history, per-player entitlement state and a manual re-check.

Gating is RBAC permissions, not a role name. ``subscription`` entitlements and
check-log rows are workspace-keyed, so ``workspace_id`` doubles as the
authorization scope and the data filter: pass it and the caller needs
``subscription.read``/``subscription.update`` *in that workspace* (which a
workspace owner or admin holds via their wildcard) and sees only that
workspace's rows; omit it and the caller needs the same permission globally,
which is what buys the cross-workspace view.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src import schemas
from src.core import db
from src.core.config import settings
from src.services.subscription_collection import admin as subscription_admin

from . import _common as c

_SF = db.async_session_maker


def _authorize(data: dict, action: str) -> int | None:
    """Gate on ``subscription.<action>`` and return the workspace scope.

    ``None`` means "every workspace", and only a global permission holder ever
    gets it — a workspace-scoped grant cannot widen itself into a cross-tenant
    read by dropping the query param.
    """
    user = c.actor(data)
    c.require_active(user)
    workspace_id: int | None = c.q1(data, "workspace_id", int)
    if workspace_id is not None:
        ensure_workspace_permission(user, workspace_id, "subscription", action)
        return workspace_id
    if not user.has_permission("subscription", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: subscription.{action} required")
    return None


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.subscription.stats")
    async def _stats(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/subscriptions/stats — subscription.read, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "read")
            result = await subscription_admin.get_collection_stats(session, workspace_id=workspace_id)
            return schemas.SubscriptionCollectionStats.model_validate(result)

        return await c.envelope(logger, "subscription.stats", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.subscription.check_log")
    async def _check_log(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/subscriptions/check-log — subscription.read, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "read")
            rows = await subscription_admin.list_check_log(
                session,
                workspace_id=workspace_id,
                state=c.q1(data, "state"),
                source=c.q1(data, "source"),
                provider=c.q1(data, "provider"),
                user_id=c.q1(data, "user_id", int),
                before_id=c.q1(data, "before_id", int),
                limit=c.q1(data, "limit", int, 50),
            )
            return [schemas.SubscriptionCheckLogRead.model_validate(row) for row in rows]

        return await c.envelope(logger, "subscription.check_log", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.subscription.user_collection")
    async def _user_collection(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/subscriptions/users/{user_id}/collection — subscription.read.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "read")
            rows = await subscription_admin.get_user_collection_status(
                session, c.require_id(data), workspace_id=workspace_id
            )
            return [schemas.SubscriptionUserCollectionRead.model_validate(row) for row in rows]

        return await c.envelope(logger, "subscription.user_collection", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.subscription.collect")
    async def _collect(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/subscriptions/collect — subscription.update, scoped by workspace_id.
        async def op(session: Any) -> Any:
            workspace_id = _authorize(data, "update")
            body = schemas.SubscriptionCollectTriggerRequest.model_validate(c.payload(data))
            checked = await subscription_admin.trigger_collection(
                session,
                user_id=body.user_id,
                providers=body.providers,
                workspace_id=workspace_id,
                discord_bot_token=settings.discord_token,
                twitch_client_id=settings.twitch_client_id,
                broker=broker,
                proxy=settings.proxy_url,
            )
            return schemas.SubscriptionCollectTriggerResponse(checked=checked)

        return await c.envelope(logger, "subscription.collect", op, session_factory=_SF)
