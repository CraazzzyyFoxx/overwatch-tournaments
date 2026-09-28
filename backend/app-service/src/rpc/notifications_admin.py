"""Typed-RPC subscribers for the notification operator screens.

Transport plus one decision: *what authorizes this operator*. Two scopes live
here and they never mix.

The workspace screen (``notification_admin_*``) is always an explicit
``workspace_id`` checked against ``notification.<action>`` in that workspace --
there is no platform-wide mode, unlike announcements. A superuser reaching
every tenant's produced rows through one unscoped list would be a cross-tenant
read with no workspace to audit it against, and the per-workspace call already
serves them wherever they hold the grant.

The account screen (``admin_user_notifications_*``) is platform-scoped instead:
it inspects and edits ONE account's own notification state, so the gate is the
global ``auth_user.read`` / ``auth_user.update`` that already governs the
accounts admin, and the account is named by the path id. That path id is the
one place in the notification handlers where a caller-supplied user id is
honoured (Global Constraint 3): the operator is acting *on* somebody else by
definition, and the grant above is what makes it legal.

Announcements are deliberately unreachable through these subjects: they have
their own CRUD, their own locale rules and their own permission. See
``services/notification_admin.py`` for why a "delete" here is a retire.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.rpc.identity import ensure_workspace_permission
from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services import notification_admin as admin_service
from src.services import notifications as notification_service

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.notification_admin_list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            workspace_id = c.require_query_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "notification", "read")
            return await admin_service.list_for_workspace(
                session,
                workspace_id=workspace_id,
                kind=c.q1(data, "kind"),
                page=c.q1(data, "page", int, 1),
                per_page=c.q1(data, "per_page", int, admin_service.DEFAULT_PER_PAGE),
            )

        return await c.envelope(logger, "notification_admin.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.notification_admin_retire")
    async def _retire(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            body = schemas.NotificationRetire.model_validate(c.payload(data))
            ensure_workspace_permission(user, body.workspace_id, "notification", "delete")
            return await admin_service.retire(
                session,
                actor=user,
                data=data,
                workspace_id=body.workspace_id,
                ids=body.ids,
                kind=body.kind,
            )

        return await c.envelope(logger, "notification_admin.retire", op, session_factory=_SF)

    @broker.subscriber("rpc.app.admin_user_notifications_get")
    async def _user_notifications_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_permission(user, "auth_user", "read")
            # Path id, not the caller's: an operator inspecting another account.
            return await notification_service.admin_user_notifications(session, auth_user_id=c.require_id(data))

        return await c.envelope(logger, "notifications.admin_user_get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.admin_user_notification_preferences_update")
    async def _user_preferences_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_permission(user, "auth_user", "update")
            body = schemas.NotificationPreferencesUpdate.model_validate(c.payload(data))
            # Path id, not the caller's: the edited row is the target's.
            return await notification_service.admin_update_user_preferences(
                session,
                auth_user_id=c.require_id(data),
                # ``exclude_none`` keeps the edit partial, as in the self-service
                # write this delegates to.
                discord_dm=body.discord_dm.model_dump(exclude_none=True),
            )

        return await c.envelope(logger, "notifications.admin_user_preferences_update", op, session_factory=_SF)
