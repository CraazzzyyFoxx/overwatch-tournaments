"""Workspace typed-RPC subscribers: public reads + create + member management.

Reads (list/get) are public. create is superuser-global. Member ops are
workspace-scoped (workspace_member.{read,create,update,delete}). workspace
update/delete go through the shared CRUD engine (see services/workspace/registry.py
+ rpc/admin_crud.py).

The role-resolution / member-payload / RBAC-cache-bust helpers are replicated
here (not imported from the route module) so the headless worker never depends on
route internals — the route module is deleted at decommission.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage
from shared.core.errors import BaseAPIException as HTTPException
from redis.asyncio import Redis
from shared.rbac import (
    assign_workspace_system_role,
    ensure_workspace_system_roles,
    get_workspace_system_role,
)
from shared.repository import AuthUserRepository
from shared.rpc.identity import ensure_workspace_permission
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, db
from src.rpc import _common as c
from src.services.workspace import service as workspace_service

_SF = db.async_session_maker
_auth_user_repo = AuthUserRepository()


def _path_int(data: dict[str, Any], key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} is required") from exc


async def _invalidate_auth_rbac_cache(auth_user_id: int, logger: Any) -> None:
    redis = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
    try:
        await redis.delete(f"rbac:user:{auth_user_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to invalidate auth RBAC cache for user %s: %s", auth_user_id, exc)
    finally:
        await redis.aclose()


async def _member_payload(session: AsyncSession, member: models.WorkspaceMember) -> schemas.WorkspaceMemberRead:
    auth_user = await _auth_user_repo.get(session, member.auth_user_id)
    roles = await workspace_service.get_member_workspace_roles(session, member.workspace_id, member.auth_user_id)
    return schemas.WorkspaceMemberRead.model_validate(
        {
            "id": member.id,
            "created_at": member.created_at,
            "updated_at": member.updated_at,
            "workspace_id": member.workspace_id,
            "auth_user_id": member.auth_user_id,
            "role": member.role,
            "username": auth_user.username if auth_user else None,
            "email": auth_user.email if auth_user else None,
            "first_name": auth_user.first_name if auth_user else None,
            "last_name": auth_user.last_name if auth_user else None,
            "avatar_url": auth_user.avatar_url if auth_user else None,
            "rbac_roles": roles,
        }
    )


async def _resolve_role_ids(
    session: AsyncSession, workspace_id: int, *, role_ids: list[int] | None, legacy_role: str | None
) -> list[int]:
    await ensure_workspace_system_roles(session, workspace_id)
    if role_ids is not None:
        return role_ids
    role = await get_workspace_system_role(session, workspace_id, legacy_role or "member")
    if role is None:
        raise HTTPException(status_code=500, detail="Workspace system role is not configured")
    return [role.id]


def register(broker: Any, logger: Any) -> None:
    # --- public reads -------------------------------------------------------
    @broker.subscriber("rpc.app.workspaces.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspaces = await workspace_service.get_all(session)
            return [schemas.WorkspaceRead.model_validate(w, from_attributes=True) for w in workspaces]

        return await c.envelope(logger, "workspaces.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await workspace_service.get_by_id(session, c.require_id(data))
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.get", op, session_factory=_SF)

    # --- create (superuser) -------------------------------------------------
    @broker.subscriber("rpc.app.workspaces.create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            body = schemas.WorkspaceCreate.model_validate(c.payload(data))
            if await workspace_service.get_by_slug(session, body.slug):
                raise HTTPException(status_code=400, detail="Workspace with this slug already exists")
            workspace = await workspace_service.create(session, **body.model_dump())
            await ensure_workspace_system_roles(session, workspace.id)
            await workspace_service.add_member(session, workspace.id, user.id, role="owner")
            await assign_workspace_system_role(session, user_id=user.id, workspace_id=workspace.id, role_name="owner")
            await session.commit()
            await _invalidate_auth_rbac_cache(int(user.id), logger)
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.create", op, session_factory=_SF)

    # --- members ------------------------------------------------------------
    @broker.subscriber("rpc.app.workspaces.members_list")
    async def _members_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "read")
            if not await workspace_service.get_by_id(session, workspace_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            members = await workspace_service.get_members(session, workspace_id)
            return [await _member_payload(session, m) for m in members]

        return await c.envelope(logger, "workspaces.members_list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.member_add")
    async def _member_add(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "create")
            if not await workspace_service.get_by_id(session, workspace_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            body = schemas.WorkspaceMemberCreate.model_validate(c.payload(data))
            if await _auth_user_repo.get(session, body.auth_user_id) is None:
                raise HTTPException(status_code=404, detail="Auth user not found")
            if await workspace_service.get_member(session, workspace_id, body.auth_user_id):
                raise HTTPException(status_code=400, detail="User is already a member")
            role_ids = await _resolve_role_ids(session, workspace_id, role_ids=body.role_ids, legacy_role=body.role)
            try:
                member = await workspace_service.add_member_with_roles(
                    session, workspace_id, body.auth_user_id, role_ids=role_ids, legacy_role=body.role or "member"
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload = await _member_payload(session, member)
            await session.commit()
            await _invalidate_auth_rbac_cache(body.auth_user_id, logger)
            return payload

        return await c.envelope(logger, "workspaces.member_add", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.member_update")
    async def _member_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            auth_user_id = _path_int(data, "auth_user_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "update")
            member = await workspace_service.get_member(session, workspace_id, auth_user_id)
            if not member:
                raise HTTPException(status_code=404, detail="Member not found")
            body = schemas.WorkspaceMemberUpdate.model_validate(c.payload(data))
            if body.role_ids is None and body.role is None:
                raise HTTPException(status_code=400, detail="role_ids or role is required")
            role_ids = await _resolve_role_ids(session, workspace_id, role_ids=body.role_ids, legacy_role=body.role)
            try:
                member = await workspace_service.update_member_roles(session, member, role_ids=role_ids)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload = await _member_payload(session, member)
            await session.commit()
            await _invalidate_auth_rbac_cache(auth_user_id, logger)
            return payload

        return await c.envelope(logger, "workspaces.member_update", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.member_remove")
    async def _member_remove(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            auth_user_id = _path_int(data, "auth_user_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "delete")
            member = await workspace_service.get_member(session, workspace_id, auth_user_id)
            if not member:
                raise HTTPException(status_code=404, detail="Member not found")
            if not await workspace_service.can_remove_member(session, member):
                raise HTTPException(status_code=400, detail="Cannot remove the last workspace owner")
            await workspace_service.remove_member(session, member)
            await session.commit()
            await _invalidate_auth_rbac_cache(auth_user_id, logger)
            return None

        return await c.envelope(logger, "workspaces.member_remove", op, session_factory=_SF)
