from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.rbac import Permission
from shared.rbac import ensure_permission_catalog
from shared.repository import PermissionRepository, UserPermissionDenyRepository, UserRoleRepository
from src import schemas
from src.services.audit import record_operator_audit
from src.services.rbac_policy import RbacPolicy, rbac_policy
from src.services.session_cache import SessionCache, session_cache


def _snapshot(permission: Permission) -> dict:
    return {
        "name": permission.name,
        "resource": permission.resource,
        "action": permission.action,
        "description": permission.description,
    }


class PermissionAdminService:
    """The permission catalog: read for RBAC operators, write for superusers."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        permissions: PermissionRepository = PermissionRepository(),
        role_grants: UserRoleRepository = UserRoleRepository(),
        denies: UserPermissionDenyRepository = UserPermissionDenyRepository(),
        cache: SessionCache = session_cache,
    ) -> None:
        self._policy = policy
        self._permissions = permissions
        self._role_grants = role_grants
        self._denies = denies
        self._cache = cache

    async def list(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.PermissionListParams,
    ) -> dict:
        """List permissions visible to RBAC operators (paginated, server-side search)."""
        self._policy.require_scoped_permission(current_user, params.workspace_id, "permission", "read")

        # Catalog rows are upserted by the workspace paths
        # (``ensure_workspace_system_roles``), so a capability added to
        # ``PERMISSION_CATALOG`` since the last one ran would be missing here --
        # and an operator cannot deny a permission the picker does not list.
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
        await record_operator_audit(
            session,
            current_user,
            action="permission.create",
            entity_type="permission",
            entity_id=permission.id,
            entity_label=permission.name,
            after=_snapshot(permission),
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

        # Read before the delete cascades the role grants and denies away: a
        # cached entry of either kind still names this permission.
        holders: set[int] = set(await self._denies.user_ids_for_permission(session, permission_id))
        for role_id in await self._permissions.role_ids_with_permission(session, permission_id):
            holders.update(await self._role_grants.user_ids_for_role(session, role_id))

        await record_operator_audit(
            session,
            current_user,
            action="permission.delete",
            entity_type="permission",
            entity_id=permission.id,
            entity_label=permission.name,
            before=_snapshot(permission),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._permissions.delete(session, permission)
        await session.commit()
        await self._cache.invalidate_rbac(*holders)
        logger.info(f"Permission deleted: {permission.name}")


permission_admin = PermissionAdminService()
