"""Typed-RPC subscribers for the notification inbox, DM preferences and banner.

Five queues, one service module underneath. The only thing decided here is
*who is asking*: everything except ``active_announcements`` takes the identity
from the gateway envelope and refuses to run without it, while that one is the
``AuthOptional`` banner read whose anonymous response the gateway caches for
every visitor.

No handler ever reads a caller-supplied user or workspace id: the audience --
and, for the preference writes, the row being edited -- is computed from
``c.actor(data).id`` alone (Global Constraint 3).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.repository.notification import DEFAULT_PAGE_LIMIT
from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services import notifications as notification_service

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.notifications_list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            return await notification_service.inbox_page(
                session,
                auth_user_id=user.id,
                cursor=c.q1(data, "cursor"),
                limit=c.q1(data, "limit", int, DEFAULT_PAGE_LIMIT),
            )

        return await c.envelope(logger, "notifications.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.notifications_mark_read")
    async def _mark_read(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            body = schemas.NotificationMarkRead.model_validate(c.payload(data))
            return await notification_service.mark_read(
                session,
                auth_user_id=user.id,
                notification_ids=body.ids,
            )

        return await c.envelope(logger, "notifications.mark_read", op, session_factory=_SF)

    @broker.subscriber("rpc.app.notifications_delete")
    async def _delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            body = schemas.NotificationDelete.model_validate(c.payload(data))
            return await notification_service.delete(
                session,
                auth_user_id=user.id,
                notification_ids=body.ids,
                only_read=body.only_read,
            )

        return await c.envelope(logger, "notifications.delete", op, session_factory=_SF)

    @broker.subscriber("rpc.app.notification_preferences_get")
    async def _preferences_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            return await notification_service.preferences(session, auth_user_id=user.id)

        return await c.envelope(logger, "notifications.preferences_get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.notification_preferences_update")
    async def _preferences_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            body = schemas.NotificationPreferencesUpdate.model_validate(c.payload(data))
            return await notification_service.update_preferences(
                session,
                auth_user_id=user.id,
                # ``exclude_none`` is what makes the edit partial: an omitted
                # (or explicitly null) group keeps its stored value, while
                # False is a value like any other.
                discord_dm=body.discord_dm.model_dump(exclude_none=True),
            )

        return await c.envelope(logger, "notifications.preferences_update", op, session_factory=_SF)

    @broker.subscriber("rpc.app.active_announcements")
    async def _active_announcements(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = c.optional_actor(data)
            return await notification_service.active_announcements(
                session,
                auth_user_id=viewer.id if viewer is not None else None,
            )

        return await c.envelope(logger, "notifications.active_announcements", op, session_factory=_SF)
