from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.models.rbac import Permission, Role, user_roles

from .catalog import PERMISSION_CATALOG, WORKSPACE_SYSTEM_ROLE_NAMES, permission_names_for_workspace_role


async def ensure_permission_catalog(session: AsyncSession) -> dict[str, Permission]:
    result = await session.execute(sa.select(Permission).where(Permission.name.in_([p.name for p in PERMISSION_CATALOG])))
    existing = {permission.name: permission for permission in result.scalars().all()}

    for spec in PERMISSION_CATALOG:
        permission = existing.get(spec.name)
        if permission is None:
            permission = Permission(
                name=spec.name,
                resource=spec.resource,
                action=spec.action,
                description=spec.description,
            )
            session.add(permission)
            existing[spec.name] = permission
        else:
            permission.resource = spec.resource
            permission.action = spec.action
            permission.description = spec.description

    await session.flush()
    return existing


async def get_workspace_system_role(
    session: AsyncSession,
    workspace_id: int,
    role_name: str,
) -> Role | None:
    result = await session.execute(
        sa.select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.workspace_id == workspace_id, Role.name == role_name)
    )
    return result.scalar_one_or_none()


async def ensure_workspace_system_roles(session: AsyncSession, workspace_id: int) -> dict[str, Role]:
    permissions = await ensure_permission_catalog(session)

    result = await session.execute(
        sa.select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.workspace_id == workspace_id, Role.name.in_(WORKSPACE_SYSTEM_ROLE_NAMES))
    )
    roles = {role.name: role for role in result.scalars().all()}

    for role_name in WORKSPACE_SYSTEM_ROLE_NAMES:
        role = roles.get(role_name)
        if role is None:
            role = Role(
                name=role_name,
                description=f"Workspace {role_name} system role",
                is_system=True,
                workspace_id=workspace_id,
            )
            session.add(role)
            roles[role_name] = role
        else:
            role.is_system = True
            role.workspace_id = workspace_id
            if not role.description:
                role.description = f"Workspace {role_name} system role"

        role.permissions = [permissions[name] for name in permission_names_for_workspace_role(role_name)]

    await session.flush()
    return roles


async def assign_workspace_system_role(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
    role_name: str,
) -> Role:
    roles = await ensure_workspace_system_roles(session, workspace_id)
    role = roles[role_name]
    await session.execute(
        sa.insert(user_roles).from_select(
            ["user_id", "role_id"],
            sa.select(sa.literal(user_id), sa.literal(role.id)).where(
                ~sa.exists().where(
                    user_roles.c.user_id == user_id,
                    user_roles.c.role_id == role.id,
                )
            ),
        )
    )
    await session.flush()
    return role


async def _workspace_roles_by_ids(
    session: AsyncSession,
    *,
    workspace_id: int,
    role_ids: list[int],
) -> list[Role]:
    if not role_ids:
        return []
    result = await session.execute(
        sa.select(Role)
        .where(Role.workspace_id == workspace_id, Role.id.in_(role_ids))
        .order_by(Role.id)
    )
    roles = list(result.scalars().all())
    if len({role.id for role in roles}) != len(set(role_ids)):
        raise ValueError("All role_ids must refer to roles in the target workspace")
    return roles


async def replace_user_workspace_roles(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
    role_ids: list[int] | None,
) -> list[Role]:
    if role_ids is None:
        roles = [await assign_workspace_system_role(session, user_id=user_id, workspace_id=workspace_id, role_name="member")]
        return roles

    roles = await _workspace_roles_by_ids(session, workspace_id=workspace_id, role_ids=role_ids)
    await session.execute(
        sa.delete(user_roles).where(
            user_roles.c.user_id == user_id,
            user_roles.c.role_id.in_(sa.select(Role.id).where(Role.workspace_id == workspace_id)),
        )
    )
    if roles:
        await session.execute(
            sa.insert(user_roles),
            [{"user_id": user_id, "role_id": role.id} for role in roles],
        )
    await session.flush()
    return roles


async def user_has_only_workspace_owner_role(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> bool:
    owner_role = await get_workspace_system_role(session, workspace_id, "owner")
    if owner_role is None:
        return False

    target_has_owner = await session.scalar(
        sa.select(sa.exists().where(user_roles.c.user_id == user_id, user_roles.c.role_id == owner_role.id))
    )
    if not target_has_owner:
        return False

    owner_count = await session.scalar(
        sa.select(sa.func.count(sa.distinct(user_roles.c.user_id))).where(user_roles.c.role_id == owner_role.id)
    )
    return int(owner_count or 0) <= 1


async def legacy_workspace_role_name_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> str:
    result = await session.execute(
        sa.select(Role.name)
        .select_from(user_roles.join(Role, Role.id == user_roles.c.role_id))
        .where(user_roles.c.user_id == user_id, Role.workspace_id == workspace_id)
    )
    role_names = set(result.scalars().all())
    for role_name in WORKSPACE_SYSTEM_ROLE_NAMES:
        if role_name in role_names:
            return role_name
    return "member"

