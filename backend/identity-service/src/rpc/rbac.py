"""RBAC administration: permissions, roles, users, denies, sessions.

Authed RPC methods resolve the active user from the gateway-injected bearer
access_token via ``c.with_active_user``, then the admin services run the full
permission checks, the exact 403/404 semantics, and the RBAC cache
invalidation side effects.

Transport only: parse the RPC payload, resolve the caller when the method needs
one, hand off to a service object, serialise the result. Every authorization
decision, query and error message belongs to ``src/services/**``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.common import actor
from shared.rpc.query import build_query_model
from shared.schemas.user_merge_auth import AuthMergeFinalizationRequest
from src import schemas
from src.services.rbac_admin import (
    auth_user_admin,
    permission_admin,
    permission_denies,
    role_admin,
    session_admin,
)

from . import _common as c

__all__ = ("register",)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.identity.rbac.finalize_profile_merge")
    async def _finalize_profile_merge(data: dict, msg: RabbitMessage) -> dict:
        async def op() -> None:
            await auth_user_admin.finalize_profile_merge(
                actor(data),
                AuthMergeFinalizationRequest.model_validate(data.get("payload")),
            )

        return await c.envelope(logger, "profile_merge.finalize", op)

    @broker.subscriber("rpc.identity.rbac.list_permissions")
    async def _rbac_list_permissions(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            qp = build_query_model(schemas.PermissionListQueryParams, data.get("query"))
            params = schemas.PermissionListParams.from_query_params(qp)
            return c.paginated_dump(await permission_admin.list(session, user, params))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.create_permission")
    async def _rbac_create_permission(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            payload = schemas.PermissionCreate.model_validate(data)
            permission = await permission_admin.create(
                session, user, payload, ip_address=data.get("ip_address"), user_agent=data.get("user_agent")
            )
            return schemas.PermissionRead.model_validate(permission, from_attributes=True).model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.delete_permission")
    async def _rbac_delete_permission(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            await permission_admin.delete(
                session,
                user,
                c.require_int(data, "permission_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.list_roles")
    async def _rbac_list_roles(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            qp = build_query_model(schemas.RoleListQueryParams, data.get("query"))
            params = schemas.RoleListParams.from_query_params(qp)
            return c.paginated_dump(await role_admin.list(session, user, params))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.get_role")
    async def _rbac_get_role(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            role = await role_admin.get(session, user, c.require_int(data, "role_id"))
            return schemas.RoleWithPermissions.model_validate(role, from_attributes=True).model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.create_role")
    async def _rbac_create_role(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            payload = schemas.RoleCreate.model_validate(data)
            role = await role_admin.create(
                session, user, payload, ip_address=data.get("ip_address"), user_agent=data.get("user_agent")
            )
            return schemas.RoleRead.model_validate(role, from_attributes=True).model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.update_role")
    async def _rbac_update_role(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            payload = schemas.RoleUpdate.model_validate(data)
            role = await role_admin.update(
                session,
                user,
                c.require_int(data, "role_id"),
                payload,
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )
            return schemas.RoleRead.model_validate(role, from_attributes=True).model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.delete_role")
    async def _rbac_delete_role(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            await role_admin.delete(
                session,
                user,
                c.require_int(data, "role_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.list_auth_users")
    async def _rbac_list_auth_users(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            qp = build_query_model(schemas.AuthUserListQueryParams, data.get("query"))
            params = schemas.AuthUserListParams.from_query_params(qp)
            return c.paginated_dump(await auth_user_admin.list(session, user, params))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.get_auth_user")
    async def _rbac_get_auth_user(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            detail = await auth_user_admin.get(session, user, c.require_int(data, "user_id"))
            return detail.model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.assign_linked_player")
    async def _rbac_assign_linked_player(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            user_id = c.require_int(data, "user_id")
            payload = schemas.AuthUserPlayerLinkAssign.model_validate(data)
            await auth_user_admin.assign_linked_player(
                session, user, user_id, payload, ip_address=data.get("ip_address"), user_agent=data.get("user_agent")
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.remove_linked_player")
    async def _rbac_remove_linked_player(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            await auth_user_admin.remove_linked_player(
                session,
                user,
                c.require_int(data, "user_id"),
                c.require_int(data, "player_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.delete_auth_user")
    async def _rbac_delete_auth_user(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            await auth_user_admin.delete(
                session,
                user,
                c.require_int(data, "user_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.assign_role")
    async def _rbac_assign_role(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            payload = schemas.UserRoleAssign.model_validate(data)
            await role_admin.assign_to_user(
                session, user, payload, ip_address=data.get("ip_address"), user_agent=data.get("user_agent")
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.remove_role")
    async def _rbac_remove_role(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            payload = schemas.UserRoleRemove.model_validate(data)
            await role_admin.remove_from_user(
                session, user, payload, ip_address=data.get("ip_address"), user_agent=data.get("user_agent")
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.get_user_roles")
    async def _rbac_get_user_roles(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> list[dict]:
            roles = await role_admin.user_roles(session, user, c.require_int(data, "user_id"))
            return [schemas.RoleRead.model_validate(r, from_attributes=True).model_dump(mode="json") for r in roles]

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.list_user_denies")
    async def _rbac_list_user_denies(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> list[dict]:
            return await permission_denies.list(session, user, c.require_int(data, "user_id"))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.add_user_deny")
    async def _rbac_add_user_deny(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> list[dict]:
            user_id = c.opt_int(data, "user_id")
            permission_id = c.opt_int(data, "permission_id")
            if user_id is None or permission_id is None:
                raise HTTPException(status_code=422, detail="user_id and permission_id are required")
            return await permission_denies.add(
                session,
                user,
                user_id,
                permission_id,
                reason=data.get("reason"),
                workspace_id=c.opt_int(data, "workspace_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.remove_user_deny")
    async def _rbac_remove_user_deny(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> list[dict]:
            user_id = c.opt_int(data, "user_id")
            permission_id = c.opt_int(data, "permission_id")
            if user_id is None or permission_id is None:
                raise HTTPException(status_code=422, detail="user_id and permission_id are required")
            return await permission_denies.remove(
                session,
                user,
                user_id,
                permission_id,
                workspace_id=c.opt_int(data, "workspace_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.list_oauth_connections")
    async def _rbac_list_oauth_connections(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            qp = build_query_model(schemas.OAuthConnectionListQueryParams, data.get("query"))
            params = schemas.OAuthConnectionListParams.from_query_params(qp)
            return c.paginated_dump(await auth_user_admin.list_oauth_connections(session, user, params))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.list_sessions")
    async def _rbac_list_sessions(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            qp = build_query_model(schemas.SessionListQueryParams, data.get("query"))
            params = schemas.SessionListParams.from_query_params(qp)
            return c.paginated_dump(await session_admin.list_auth_sessions(session, user, params))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.rbac.delete_oauth_connection")
    async def _rbac_delete_oauth_connection(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            await auth_user_admin.delete_oauth_connection(
                session,
                user,
                c.require_int(data, "connection_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)
