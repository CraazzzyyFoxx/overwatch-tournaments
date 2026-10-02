"""RBAC administration services.

The write surface behind ``rpc.app.rbac.*``: permissions, roles, auth-user
administration, per-user permission denies and the superuser session inventory.
Every guard lives in ``rbac_policy``, every statement in the repository layer;
what is left here is the flow — ordering, audit trail, cache invalidation and
the transaction boundary.

Audit rows are staged **before** the flow's own ``commit()`` so a rolled-back
mutation cannot keep its trail and a committed one cannot lose it. Where another
service owns the commit (the linked-player flows), the audit row is staged
before handing over, for the same reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.rbac import Permission, Role, UserPermissionDeny
from shared.rbac import ensure_permission_catalog, ensure_workspace_system_roles, user_has_only_workspace_owner_role
from shared.repository import (
    AuthUserRepository,
    OAuthConnectionRepository,
    PermissionRepository,
    RoleRepository,
    UserPermissionDenyRepository,
    UserRoleRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from shared.schemas.user_merge_auth import AuthMergeFinalizationRequest
from shared.services.audit import record_audit
from src import models, schemas
from src.services.auth_users import AuthUserService, auth_users
from src.services.players import PlayerLinkService, players
from src.services.rbac_policy import RbacPolicy, rbac_policy
from src.services.security import token_codec
from src.services.session_cache import SessionCache, session_cache
from src.services.sessions import SessionService, sessions


def _linked_players_payload(user: models.AuthUser) -> list[schemas.AuthUserLinkedPlayerRead]:
    """Return the 0-or-1 player linked to ``user`` via ``players.user.auth_user_id``
    (see ``token_payload`` for the wire-shape note)."""
    player = user.player
    if player is None:
        return []
    return [
        schemas.AuthUserLinkedPlayerRead(
            player_id=player.id,
            player_name=player.name,
            is_primary=True,
            linked_at=player.created_at.isoformat(),
        )
    ]


def _auth_user_list_payload(user: models.AuthUser) -> dict:
    payload = schemas.AuthUserListRead.model_validate(user, from_attributes=True).model_dump()
    payload["roles"] = AuthUserService.global_roles(user)
    payload["linked_players"] = _linked_players_payload(user)
    return payload


def _deny_payload(permission: Permission, workspace_id: int | None) -> dict:
    return {
        "permission_id": permission.id,
        "name": permission.name,
        "resource": permission.resource,
        "action": permission.action,
        "description": permission.description,
        "workspace_id": workspace_id,
    }


async def _invalidate_role_holders(
    session: AsyncSession,
    role_id: int,
    *,
    role_grants: UserRoleRepository,
    cache: SessionCache,
) -> None:
    """Invalidate RBAC cache for every user that holds a given role."""
    for user_id in await role_grants.user_ids_for_role(session, role_id):
        await cache.invalidate_rbac(user_id)


_SESSION_SORT_KEYS = frozenset({"login_at", "last_seen_at", "expires_at", "status"})


def _sort_session_summaries(
    summaries: Sequence[dict],
    sort: str,
    order: pagination.SortOrder | str,
) -> list[dict]:
    """Stable-sort aggregated session summaries by a whitelisted key.

    Logical sessions are aggregated from refresh tokens in Python, so sorting
    happens here (not in SQL). Falls back to ``last_seen_at`` for unknown keys.
    """
    key_name = sort if sort in _SESSION_SORT_KEYS else "last_seen_at"
    reverse = order == pagination.SortOrder.DESC or order == "desc"
    _min_dt = datetime.min.replace(tzinfo=UTC)

    if key_name == "status":

        def key(summary: dict) -> tuple:
            return (summary.get("status") or "",)
    else:

        def key(summary: dict) -> tuple:
            return (summary.get(key_name) or _min_dt,)

    return sorted(summaries, key=key, reverse=reverse)


class PermissionAdminService:
    """The permission catalog: read for RBAC operators, write for superusers."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        permissions: PermissionRepository = PermissionRepository(),
        role_grants: UserRoleRepository = UserRoleRepository(),
        cache: SessionCache = session_cache,
    ) -> None:
        self._policy = policy
        self._permissions = permissions
        self._role_grants = role_grants
        self._cache = cache

    async def list(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.PermissionListParams,
    ) -> dict:
        """List permissions visible to RBAC operators (paginated, server-side search)."""
        self._policy.require_scoped_permission(current_user, params.workspace_id, "permission", "read")

        # Same staleness the roles list closes below: catalog rows are upserted by
        # the workspace paths (``ensure_workspace_system_roles``), so a capability
        # that landed in ``PERMISSION_CATALOG`` since the last one ran would be
        # missing here -- and an operator cannot deny a permission the picker does
        # not list. This is the screen that must never be behind the code.
        await ensure_permission_catalog(session)
        await session.commit()

        permissions, total = await self._permissions.list_searchable(session, params, search=params.search)
        return pagination.paginated_dict(
            [schemas.PermissionRead.model_validate(p, from_attributes=True) for p in permissions], total, params
        )

    async def create(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        permission_data: schemas.PermissionCreate,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Permission:
        """Create a new permission (superuser only)."""
        self._policy.require_superuser(current_user)
        if await self._permissions.get_by_name(session, permission_data.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Permission with this name already exists"
            )

        permission = Permission(
            name=permission_data.name,
            resource=permission_data.resource,
            action=permission_data.action,
            description=permission_data.description,
        )
        # ``create`` flushes, so the audit row can name the id the operator will
        # see in the UI.
        await self._permissions.create(session, permission)
        await record_audit(
            session,
            action="permission.create",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
            entity_type="permission",
            entity_id=permission.id,
            entity_label=permission.name,
            after={
                "name": permission.name,
                "resource": permission.resource,
                "action": permission.action,
                "description": permission.description,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await session.refresh(permission)

        logger.info(f"Permission created: {permission.name}")
        return permission

    async def delete(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        permission_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Delete a permission (superuser only)."""
        self._policy.require_superuser(current_user)
        permission = await self._permissions.get(session, permission_id)

        if not permission:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

        for role_id in await self._permissions.role_ids_with_permission(session, permission_id):
            await _invalidate_role_holders(session, role_id, role_grants=self._role_grants, cache=self._cache)

        await record_audit(
            session,
            action="permission.delete",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
            entity_type="permission",
            entity_id=permission.id,
            entity_label=permission.name,
            before={
                "name": permission.name,
                "resource": permission.resource,
                "action": permission.action,
                "description": permission.description,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.delete(permission)
        await session.commit()
        logger.info(f"Permission deleted: {permission.name}")


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
        await record_audit(
            session,
            action="role.create",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
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

        await record_audit(
            session,
            action="role.update",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
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
            await _invalidate_role_holders(session, role.id, role_grants=self._role_grants, cache=self._cache)

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

        await _invalidate_role_holders(session, role.id, role_grants=self._role_grants, cache=self._cache)
        # ``role`` is loaded without its permissions here, so the snapshot stays on
        # the columns the row itself carries.
        await record_audit(
            session,
            action="role.delete",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
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
        await session.delete(role)
        await session.commit()
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
        if role.workspace_id is not None and not await self._members.exists_for_auth_user(
            session, workspace_id=role.workspace_id, auth_user_id=data.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target user must be a member of the workspace",
            )

        # Privilege ceiling: never hand out a role carrying permissions the actor
        # does not themselves hold (review M / RBAC escalation).
        self._policy.require_can_grant(current_user, role.permissions, role.workspace_id)

        if role in user.roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already has this role")

        user.roles.append(role)
        await record_audit(
            session,
            action="role.assign",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
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

        if role not in user.roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not have this role")

        if role.workspace_id is not None and role.name == "owner":
            if await user_has_only_workspace_owner_role(session, user_id=data.user_id, workspace_id=role.workspace_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove the last workspace owner role assignment",
                )

        if role.workspace_id is None and role.name in self._policy.ADMIN_EQUIVALENT_ROLE_NAMES:
            # A real COUNT: the guard only needs the tally, and this used to
            # hydrate every holder id just to call ``len()`` on the list.
            if await self._role_grants.count_for_role(session, role.id) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the last admin role assignment"
                )

        user.roles.remove(role)
        await record_audit(
            session,
            action="role.remove",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
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


class AuthUserAdminService:
    """Auth-account administration: listing, detail, player links, deletion, OAuth."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        accounts: AuthUserService = auth_users,
        users: AuthUserRepository = AuthUserRepository(),
        connections: OAuthConnectionRepository = OAuthConnectionRepository(),
        links: PlayerLinkService = players,
        cache: SessionCache = session_cache,
    ) -> None:
        self._policy = policy
        self._accounts = accounts
        self._users = users
        self._connections = connections
        self._links = links
        self._cache = cache

    async def list(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.AuthUserListParams,
    ) -> dict:
        """List auth users with assigned roles (paginated, server-side filters)."""
        self._policy.require_scoped_permission(current_user, params.workspace_id, "auth_user", "read")

        users, total = await self._accounts.list_with_rbac(session, params, include_player=True)
        return pagination.paginated_dict(
            [schemas.AuthUserListRead.model_validate(_auth_user_list_payload(user)) for user in users], total, params
        )

    async def get(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
    ) -> schemas.AuthUserDetailRead:
        """Get auth-user detail with assigned roles and effective permissions."""
        self._policy.require_permission(current_user, "auth_user", "read")

        user = await self._accounts.get_with_rbac(session, user_id, include_player=True)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        payload = _auth_user_list_payload(user)
        payload["effective_permissions"] = self._policy.effective_permissions(user)
        return schemas.AuthUserDetailRead.model_validate(payload)

    async def assign_linked_player(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        data: schemas.AuthUserPlayerLinkAssign,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Assign a player account from the analytics system to an auth user."""
        self._policy.require_permission(current_user, "auth_user", "update")

        user = await self._users.get(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # The player-link service owns the commit for this flow, so the audit row
        # is staged before the call to land in the same transaction as the link.
        await record_audit(
            session,
            action="linked_player.assign",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=user.username or user.email,
            after={"player_id": data.player_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._links.admin_link(session, user_id, data.player_id, data.is_primary)

    async def remove_linked_player(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        player_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Remove a player account link from an auth user."""
        self._policy.require_permission(current_user, "auth_user", "update")

        user = await self._users.get(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # The player-link service owns the commit for this flow, so the audit row
        # is staged before the call to land in the same transaction as the unlink.
        await record_audit(
            session,
            action="linked_player.remove",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=user.username or user.email,
            before={"player_id": player_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._links.admin_unlink(session, user_id, player_id)

    async def delete(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Permanently delete an auth account (superuser only).

        Cascades roles, permission denies, refresh tokens/sessions, OAuth
        connections, API keys and preview-access grants (FK ondelete=CASCADE). The
        linked ``players.user`` is preserved with its ``auth_user_id`` nulled
        (ondelete=SET NULL), so tournament history and ``workspace_member`` rows
        survive the deletion.
        """
        self._policy.require_superuser(current_user)

        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account",
            )

        user = await self._users.get(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        email = user.email  # capture before delete/commit expires the instance
        await record_audit(
            session,
            action="auth_user.delete",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=user.username or email,
            before={"email": email, "username": user.username},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.delete(user)
        await session.commit()
        await self._cache.invalidate_rbac(user_id)
        logger.info(f"Auth user deleted by admin: user_id={user_id} email={email} actor_user_id={current_user.id}")

    async def finalize_profile_merge(
        self,
        current_user: models.AuthUser,
        request: AuthMergeFinalizationRequest,
    ) -> None:
        """Retire merge-affected sessions using identity's configured token lifetime."""
        self._policy.require_superuser(current_user)
        await self._cache.finalize_profile_merge(
            request.auth_user_ids,
            {str(session_id) for session_id in request.session_ids},
            token_codec.access_token_ttl_seconds,
        )

    async def list_oauth_connections(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.OAuthConnectionListParams,
    ) -> dict:
        """List OAuth connections across all users (admin view, paginated)."""
        self._policy.require_permission(current_user, "auth_user", "read")

        connections, total = await self._connections.list_admin(
            session,
            params,
            provider=params.provider,
            auth_user_id=params.auth_user_id,
            search=params.search,
        )

        results = [
            schemas.OAuthConnectionAdminRead(
                id=conn.id,
                provider=conn.provider,
                provider_user_id=conn.provider_user_id,
                email=conn.email,
                username=conn.username,
                display_name=conn.display_name,
                avatar_url=conn.avatar_url,
                created_at=conn.created_at,
                updated_at=conn.updated_at,
                auth_user_id=conn.auth_user_id,
                auth_user_email=conn.auth_user.email if conn.auth_user else None,
                auth_user_username=conn.auth_user.username if conn.auth_user else None,
                token_expires_at=conn.token_expires_at,
            )
            for conn in connections
        ]
        return pagination.paginated_dict(results, total, params)

    async def delete_oauth_connection(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        connection_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Delete a specific OAuth connection from an auth user (admin view)."""
        self._policy.require_permission(current_user, "auth_user", "update")

        connection = await self._connections.get_with_auth_user(session, connection_id)

        if not connection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth connection not found")

        linked_user = connection.auth_user
        if linked_user and not linked_user.hashed_password:
            # A real COUNT: the guard only needs the tally, and this used to
            # hydrate every connection id just to call ``len()`` on the list.
            if await self._connections.count_for_user(session, connection.auth_user_id) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot unlink last OAuth provider for a passwordless account. Set a password first.",
                )

        await record_audit(
            session,
            action="oauth_connection.delete",
            source="admin",
            actor=current_user,
            actor_label=self._policy.actor_label(current_user),
            entity_type="oauth_connection",
            entity_id=connection.id,
            entity_label=connection.provider,
            before={"provider": connection.provider, "auth_user_id": connection.auth_user_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.delete(connection)
        await session.commit()
        logger.info(
            "OAuth connection deleted by admin: "
            f"connection_id={connection.id} provider={connection.provider} auth_user_id={connection.auth_user_id} "
            f"actor_user_id={current_user.id}"
        )


class PermissionDenyService:
    """Per-user permission denies (negative RBAC).

    ``workspace_id=None`` denies the permission globally (everywhere); a concrete
    ``workspace_id`` scopes the deny to that workspace only. A user can hold both
    a global and a workspace-scoped deny for the same permission at once
    (distinct rows per the partial-unique index), which is why every lookup goes
    through ``UserPermissionDenyRepository.workspace_scope`` — a NULL-safe scope
    predicate whose reasoning is documented at the repository.
    """

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        denies: UserPermissionDenyRepository = UserPermissionDenyRepository(),
        permissions: PermissionRepository = PermissionRepository(),
        users: AuthUserRepository = AuthUserRepository(),
        workspaces: WorkspaceRepository = WorkspaceRepository(),
        cache: SessionCache = session_cache,
    ) -> None:
        self._policy = policy
        self._denies = denies
        self._permissions = permissions
        self._users = users
        self._workspaces = workspaces
        self._cache = cache

    async def list(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
    ) -> list[dict]:
        """List the permissions explicitly denied for a user (global + per-workspace)."""
        self._policy.require_permission(current_user, "auth_user", "read")
        rows = await self._denies.list_with_permissions(session, user_id)
        return [_deny_payload(permission, workspace_id) for permission, workspace_id in rows]

    async def add(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        permission_id: int,
        reason: str | None = None,
        workspace_id: int | None = None,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[dict]:
        """Deny a permission to a user (idempotent). Rejects governance permissions."""
        self._policy.require_permission(current_user, "auth_user", "update")

        user = await self._users.get(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        permission = await self._permissions.get(session, permission_id)
        if permission is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
        if permission.resource in self._policy.DENY_PROTECTED_RESOURCES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot deny governance permission '{permission.name}'",
            )

        if workspace_id is not None and await self._workspaces.get(session, workspace_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

        existing = await self._denies.get_scoped(
            session, user_id=user_id, permission_id=permission_id, workspace_id=workspace_id
        )
        if existing is None:
            session.add(
                UserPermissionDeny(
                    user_id=user_id,
                    permission_id=permission_id,
                    workspace_id=workspace_id,
                    created_by=current_user.id,
                    reason=reason,
                )
            )
            await record_audit(
                session,
                action="permission_deny.add",
                source="admin",
                actor=current_user,
                actor_label=self._policy.actor_label(current_user),
                workspace_id=workspace_id,
                entity_type="auth_user",
                entity_id=user_id,
                entity_label=user.username or user.email,
                after={
                    "permission_id": permission_id,
                    "permission_name": permission.name,
                    "workspace_id": workspace_id,
                },
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await session.commit()
            logger.info(
                f"Permission denied to user: user_id={user_id} permission={permission.name} "
                f"workspace_id={workspace_id} actor={current_user.id}"
            )
        await self._cache.invalidate_rbac(user_id)
        return await self.list(session, current_user, user_id)

    async def remove(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        permission_id: int,
        workspace_id: int | None = None,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[dict]:
        """Remove a permission deny from a user (idempotent).

        Matches the exact ``(user_id, permission_id, workspace_id)`` scope so
        removing a global deny never removes a workspace-scoped deny for the same
        permission, and vice-versa.
        """
        self._policy.require_permission(current_user, "auth_user", "update")
        removed = await self._denies.delete_scoped(
            session, user_id=user_id, permission_id=permission_id, workspace_id=workspace_id
        )
        # Idempotent by contract: a remove that matched nothing lifted nothing, and
        # must not claim in the journal that it did.
        if removed:
            await record_audit(
                session,
                action="permission_deny.remove",
                source="admin",
                actor=current_user,
                actor_label=self._policy.actor_label(current_user),
                workspace_id=workspace_id,
                entity_type="auth_user",
                entity_id=user_id,
                before={"permission_id": permission_id, "workspace_id": workspace_id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        await session.commit()
        await self._cache.invalidate_rbac(user_id)
        logger.info(
            f"Permission deny removed: user_id={user_id} permission_id={permission_id} "
            f"workspace_id={workspace_id} actor={current_user.id}"
        )
        return await self.list(session, current_user, user_id)


class SessionAdminService:
    """The superuser session inventory across every auth account."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        session_reader: SessionService = sessions,
    ) -> None:
        self._policy = policy
        self._sessions = session_reader

    async def list_auth_sessions(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.SessionListParams,
    ) -> dict:
        """List logical auth sessions across all users (superuser only, paginated).

        Aggregation/status derivation stay in Python; sort + pagination are applied
        to the aggregated summaries, and ``total`` reflects the filtered set.
        """
        self._policy.require_superuser(current_user)
        summaries = await self._sessions.list_all_sessions(
            session,
            user_id=params.user_id,
            search=params.search,
            status=params.status,
        )
        summaries = _sort_session_summaries(summaries, params.sort, params.order)
        total = len(summaries)
        page_items = params.paginate_data(summaries)
        return pagination.paginated_dict(
            [schemas.AdminSessionRead.model_validate(summary) for summary in page_items], total, params
        )


permission_admin = PermissionAdminService()
role_admin = RoleAdminService()
auth_user_admin = AuthUserAdminService()
permission_denies = PermissionDenyService()
session_admin = SessionAdminService()
