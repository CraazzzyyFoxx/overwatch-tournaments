from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.rbac import Permission, Role
from shared.rbac import ensure_workspace_system_roles, user_has_only_workspace_owner_role
from shared.rbac.bootstrap import ensure_can_change_owner_role
from shared.repository import (
    AuthUserRepository,
    PermissionRepository,
    RoleRepository,
    UserRoleRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from src import schemas
from src.services.audit import record_operator_audit
from src.services.auth_users import AuthUserService
from src.services.rbac_policy import RbacPolicy, rbac_policy
from src.services.session_cache import SessionCache, session_cache


class RoleAdminService:
    """Roles and role grants, global and workspace-scoped."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        roles: RoleRepository = RoleRepository(),
        permissions: PermissionRepository = PermissionRepository(),
        users: AuthUserRepository = AuthUserRepository(),
        role_grants: UserRoleRepository = UserRoleRepository(),
        workspaces: WorkspaceRepository = WorkspaceRepository(),
        members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        cache: SessionCache = session_cache,
    ) -> None:
        self._policy = policy
        self._roles = roles
        self._permissions = permissions
        self._users = users
        self._role_grants = role_grants
        self._workspaces = workspaces
        self._members = members
        self._cache = cache

    async def list(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.RoleListParams,
    ) -> dict:
        """List roles by scope (paginated, server-side search)."""
        self._policy.require_role_scope(current_user, params.workspace_id, "read")

        if params.workspace_id is not None:
            # System roles (owner/admin/referee/host/member/player) are created lazily by
            # add_member/grant/registration paths, not on workspace creation alone.
            # A workspace that has not exercised one of those since a new system
            # role landed in the catalog would otherwise show a stale role list --
            # e.g. the members page's role picker missing "Host" entirely.
            await ensure_workspace_system_roles(session, params.workspace_id)
            await session.commit()

        roles, total = await self._roles.list_in_scope(
            session, params, workspace_id=params.workspace_id, search=params.search
        )
        return pagination.paginated_dict(
            [schemas.RoleRead.model_validate(r, from_attributes=True) for r in roles], total, params
        )

    async def get(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        role_id: int,
    ) -> Role:
        """Get role with permissions."""
        role = await self._roles.get_with_permissions(session, role_id)

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        self._policy.require_role_scope(current_user, role.workspace_id, "read")
        return role

    async def create(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        role_data: schemas.RoleCreate,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """Create a new role (global or workspace-scoped)."""
        # Creation requires the grant in the role's own scope: a global
        # ``role.create`` holder must not be able to mint roles inside an
        # arbitrary workspace, so there is no global fallback here.
        self._policy.require_role_scope(current_user, role_data.workspace_id, "create", global_fallback=False)
        if role_data.workspace_id is not None and not await self._workspaces.exists(session, id=role_data.workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

        # Never let an operator mint a role under a reserved/trusted name (esp.
        # ``admin``, a hardcoded full-bypass marker in the shared model).
        if role_data.name.strip().lower() in self._policy.RESERVED_ROLE_NAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role name '{role_data.name}' is reserved",
            )

        if await self._roles.find_in_scope(session, name=role_data.name, workspace_id=role_data.workspace_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role with this name already exists")

        permissions: list[Permission] = []
        if role_data.permission_ids:
            permissions = list(await self._permissions.bulk_get(session, role_data.permission_ids))
            # Privilege ceiling: cannot mint a role more powerful than the actor.
            self._policy.require_can_grant(current_user, permissions, role_data.workspace_id)

        role = Role(
            name=role_data.name,
            description=role_data.description,
            is_system=False,
            workspace_id=role_data.workspace_id,
        )
        role.permissions = permissions

        # ``create`` flushes, so the audit row can name the id the operator will
        # see in the UI.
        await self._roles.create(session, role)
        await record_operator_audit(
            session,
            current_user,
            action="role.create",
            workspace_id=role.workspace_id,
            entity_type="role",
            entity_id=role.id,
            entity_label=role.name,
            after={
                "name": role.name,
                "description": role.description,
                "workspace_id": role.workspace_id,
                "permissions": sorted(permission.name for permission in permissions),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await session.refresh(role)

        logger.info(f"Role created: {role.name} (workspace_id={role.workspace_id})")
        return role

    async def update(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        role_id: int,
        role_data: schemas.RoleUpdate,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Role:
        """Update a role."""
        role = await self._roles.get_with_permissions(session, role_id)

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        if role.is_system:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify system roles")

        self._policy.require_role_access(current_user, role, "update")

        # Snapshot before any field is touched; ``role.permissions`` is eager-loaded
        # above, so reading it here costs nothing and cannot lazy-load mid-flow.
        before = {
            "name": role.name,
            "description": role.description,
            "permissions": sorted(permission.name for permission in role.permissions),
        }

        if role_data.name is not None:
            if await self._roles.find_in_scope(
                session, name=role_data.name, workspace_id=role.workspace_id, exclude_id=role_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Role with this name already exists"
                )
            role.name = role_data.name

        if role_data.description is not None:
            role.description = role_data.description

        permissions_changed = False
        if role_data.permission_ids is not None:
            permissions = list(await self._permissions.bulk_get(session, role_data.permission_ids))
            # Privilege ceiling: cannot raise a role above the actor's own permissions.
            self._policy.require_can_grant(current_user, permissions, role.workspace_id)
            role.permissions = permissions
            permissions_changed = True

        await record_operator_audit(
            session,
            current_user,
            action="role.update",
            workspace_id=role.workspace_id,
            entity_type="role",
            entity_id=role.id,
            entity_label=role.name,
            before=before,
            after={
                "name": role.name,
                "description": role.description,
                "permissions": sorted(permission.name for permission in role.permissions),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await session.refresh(role)

        if permissions_changed:
            await self._cache.invalidate_rbac(*await self._role_grants.user_ids_for_role(session, role.id))

        logger.info(f"Role updated: {role.name}")
        return role

    async def delete(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        role_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Delete a role."""
        role = await self._roles.get(session, role_id)

        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        if role.is_system:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete system roles")

        self._policy.require_role_access(current_user, role, "delete")

        # Read before the delete cascades the grants away.
        holders = await self._role_grants.user_ids_for_role(session, role.id)
        # ``role`` is loaded without its permissions here, so the snapshot stays on
        # the columns the row itself carries.
        await record_operator_audit(
            session,
            current_user,
            action="role.delete",
            workspace_id=role.workspace_id,
            entity_type="role",
            entity_id=role.id,
            entity_label=role.name,
            before={
                "name": role.name,
                "description": role.description,
                "workspace_id": role.workspace_id,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._roles.delete(session, role)
        await session.commit()
        await self._cache.invalidate_rbac(*holders)
        logger.info(f"Role deleted: {role.name}")

    async def assign_to_user(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        data: schemas.UserRoleAssign,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Assign a role to a user."""
        user = await self._users.get(session, data.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        role = await self._roles.get_with_permissions(session, data.role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        # A grant must be authorized in the role's own scope; a global
        # ``role.update`` holder is not thereby an operator inside a workspace.
        self._policy.require_role_scope(current_user, role.workspace_id, "update", global_fallback=False)
        if role.workspace_id is not None and role.name == "owner":
            await ensure_can_change_owner_role(session, actor=current_user, workspace_id=role.workspace_id)
        if role.workspace_id is not None and not await self._members.exists_for_auth_user(
            session, workspace_id=role.workspace_id, auth_user_id=data.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target user must be a member of the workspace",
            )

        # Privilege ceiling: never hand out a role carrying permissions the actor
        # does not themselves hold.
        self._policy.require_can_grant(current_user, role.permissions, role.workspace_id)

        if role in user.roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already has this role")

        user.roles.append(role)
        await record_operator_audit(
            session,
            current_user,
            action="role.assign",
            workspace_id=role.workspace_id,
            entity_type="auth_user",
            entity_id=data.user_id,
            entity_label=user.username or user.email,
            after={"role_id": role.id, "role_name": role.name, "workspace_id": role.workspace_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await self._cache.invalidate_rbac(data.user_id)
        logger.info(f"Role {role.name} assigned to user {user.email}")

    async def remove_from_user(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        data: schemas.UserRoleRemove,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Remove a role from a user."""
        user = await self._users.get_with_roles(session, data.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        role = await self._roles.get(session, data.role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

        self._policy.require_role_scope(current_user, role.workspace_id, "update", global_fallback=False)
        if role.workspace_id is not None and role.name == "owner":
            await ensure_can_change_owner_role(session, actor=current_user, workspace_id=role.workspace_id)

        if role not in user.roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not have this role")

        if role.workspace_id is not None and role.name == "owner":
            if await user_has_only_workspace_owner_role(session, user_id=data.user_id, workspace_id=role.workspace_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove the last workspace owner role assignment",
                )

        if role.workspace_id is None and role.name in self._policy.ADMIN_EQUIVALENT_ROLE_NAMES:
            if await self._role_grants.count_for_role(session, role.id) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the last admin role assignment"
                )

        user.roles.remove(role)
        await record_operator_audit(
            session,
            current_user,
            action="role.remove",
            workspace_id=role.workspace_id,
            entity_type="auth_user",
            entity_id=data.user_id,
            entity_label=user.username or user.email,
            before={"role_id": role.id, "role_name": role.name, "workspace_id": role.workspace_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await self._cache.invalidate_rbac(data.user_id)
        logger.info(f"Role {role.name} removed from user {user.email}")

    async def user_roles(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
    ) -> list[Role]:
        """Get all roles for a user."""
        self._policy.require_permission(current_user, "auth_user", "read")

        user = await self._users.get_with_roles(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        return AuthUserService.global_roles(user)


role_admin = RoleAdminService()
