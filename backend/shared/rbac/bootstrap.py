from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.errors import BaseAPIException
from shared.messaging.config import WORKSPACE_MEMBER_CHANGED_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.identity.rbac import Permission, Role, user_roles
from shared.models.tenancy.workspace import Workspace
from shared.schemas.events import WorkspaceMemberChangedEvent

from .catalog import PERMISSION_CATALOG, WORKSPACE_SYSTEM_ROLE_NAMES, permission_names_for_workspace_role

# Q2: the ``owner`` role is the one grant a role or member permission alone does not cover.
OWNER_ROLE_CHANGE_FORBIDDEN = "Only a workspace owner can grant or revoke the owner role"


async def stage_rbac_change(
    session: AsyncSession,
    auth_user_ids: Iterable[int],
    *,
    change: str,
    workspace_id: int | None = None,
) -> None:
    """Stage the event that makes identity drop these users' cached RBAC payload.

    Transactional outbox: the row commits or rolls back with the write that
    called this, and any service's outbox drain relays it to
    ``WORKSPACE_MEMBER_CHANGED_QUEUE``. Every writer of memberships or
    workspace role grants outside identity-service calls it (or, in
    app-service's ``WorkspaceService``, stages the same event itself), because
    identity caches the payload for minutes. No users, no event. A redundant
    copy is harmless: dropping a key is idempotent.
    """
    ids = sorted(set(auth_user_ids))
    if not ids:
        return
    await enqueue_outbox_event(
        session,
        WorkspaceMemberChangedEvent(workspace_id=workspace_id, auth_user_ids=ids, change=change),
        exchange="",
        routing_key=WORKSPACE_MEMBER_CHANGED_QUEUE.name,
    )


async def _catalog_permissions(session: AsyncSession) -> dict[str, Permission]:
    result = await session.execute(
        sa.select(Permission).where(Permission.name.in_([p.name for p in PERMISSION_CATALOG]))
    )
    return {permission.name: permission for permission in result.scalars().all()}


async def ensure_permission_catalog(session: AsyncSession) -> dict[str, Permission]:
    existing = await _catalog_permissions(session)
    missing = [spec for spec in PERMISSION_CATALOG if spec.name not in existing]
    if missing:
        # ON CONFLICT: two bootstraps racing on a fresh catalog (concurrent
        # workspace creates) wait on each other's row instead of one 500ing.
        await session.execute(
            pg_insert(Permission)
            .values(
                [
                    {"name": s.name, "resource": s.resource, "action": s.action, "description": s.description}
                    for s in missing
                ]
            )
            .on_conflict_do_nothing(index_elements=["name"])
        )
        existing = await _catalog_permissions(session)

    for spec in PERMISSION_CATALOG:
        permission = existing[spec.name]
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


async def _workspace_system_roles(session: AsyncSession, workspace_id: int) -> dict[str, Role]:
    result = await session.execute(
        sa.select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.workspace_id == workspace_id, Role.name.in_(WORKSPACE_SYSTEM_ROLE_NAMES))
    )
    return {role.name: role for role in result.scalars().all()}


async def ensure_workspace_system_roles(session: AsyncSession, workspace_id: int) -> dict[str, Role]:
    permissions = await ensure_permission_catalog(session)

    roles = await _workspace_system_roles(session, workspace_id)
    missing = [name for name in WORKSPACE_SYSTEM_ROLE_NAMES if name not in roles]
    if missing:
        # Same race as the catalog: a concurrent caller seeding this workspace
        # first is waited on and re-read, never a unique violation.
        await session.execute(
            pg_insert(Role)
            .values(
                [
                    {
                        "name": name,
                        "description": f"Workspace {name} system role",
                        "is_system": True,
                        "workspace_id": workspace_id,
                    }
                    for name in missing
                ]
            )
            .on_conflict_do_nothing(index_elements=["name", "workspace_id"], index_where=Role.workspace_id.is_not(None))
        )
        roles = await _workspace_system_roles(session, workspace_id)

    changed: list[int] = []
    for role_name in WORKSPACE_SYSTEM_ROLE_NAMES:
        role = roles[role_name]
        role.is_system = True
        if not role.description:
            role.description = f"Workspace {role_name} system role"
        granted = [permissions[name] for name in permission_names_for_workspace_role(role_name)]
        if {p.id for p in role.permissions} != {p.id for p in granted}:
            role.permissions = granted
            changed.append(role.id)

    await session.flush()
    if changed:
        # A reconciled permission set (a catalog release, or a drifted row) changes the RBAC payload of every holder.
        holders = await session.scalars(sa.select(user_roles.c.user_id).where(user_roles.c.role_id.in_(changed)))
        await stage_rbac_change(session, holders, change="role_permissions_changed", workspace_id=workspace_id)
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
    granted = await session.scalar(
        sa.insert(user_roles)
        .from_select(
            ["user_id", "role_id"],
            sa.select(sa.literal(user_id), sa.literal(role.id)).where(
                ~sa.exists().where(
                    user_roles.c.user_id == user_id,
                    user_roles.c.role_id == role.id,
                )
            ),
        )
        .returning(user_roles.c.user_id)
    )
    await session.flush()
    if granted is not None:
        await stage_rbac_change(session, [user_id], change="roles_changed", workspace_id=workspace_id)
    return role


async def user_has_any_workspace_role(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> bool:
    """True when ``user_id`` holds at least one role scoped to ``workspace_id``."""
    return bool(
        await session.scalar(
            sa.select(sa.literal(True))
            .select_from(user_roles.join(Role, Role.id == user_roles.c.role_id))
            .where(user_roles.c.user_id == user_id, Role.workspace_id == workspace_id)
            .limit(1)
        )
    )


async def assign_default_member_role_if_roleless(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> bool:
    """Grant the workspace ``player`` system role to ``user_id`` iff they hold
    no role in ``workspace_id`` yet. Returns True when a role was assigned.

    The members screen treats every auth-linked ``workspace_member`` as an RBAC
    member; a row whose auth user has zero workspace roles is the "role-less
    member" this autofill closes. Idempotent and additive — it never touches an
    existing role, so an ``admin`` / custom assignment is preserved and never
    downgraded.

    Kept cheap for the hot anchor path (``get_or_create_workspace_member``):
    resolves the existing ``player`` role directly and only falls back to the
    full ``ensure_workspace_system_roles`` upsert when the workspace has no
    system roles yet, rather than upserting the whole catalog on every call.

    Stages no RBAC-change event itself: every caller already tells identity
    (``get_or_create_workspace_member`` stages ``added``, ``WorkspaceService``
    its own event, identity's player link drops the cache after its commit).
    """
    if await user_has_any_workspace_role(session, user_id=user_id, workspace_id=workspace_id):
        return False

    member_role = await get_workspace_system_role(session, workspace_id, "player")
    if member_role is None:
        member_role = (await ensure_workspace_system_roles(session, workspace_id))["player"]

    await session.execute(
        sa.insert(user_roles).from_select(
            ["user_id", "role_id"],
            sa.select(sa.literal(user_id), sa.literal(member_role.id)).where(
                ~sa.exists().where(
                    user_roles.c.user_id == user_id,
                    user_roles.c.role_id == member_role.id,
                )
            ),
        )
    )
    await session.flush()
    return True


async def _workspace_roles_by_ids(
    session: AsyncSession,
    *,
    workspace_id: int,
    role_ids: list[int],
) -> list[Role]:
    if not role_ids:
        return []
    result = await session.execute(
        sa.select(Role).where(Role.workspace_id == workspace_id, Role.id.in_(role_ids)).order_by(Role.id)
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
        roles = [
            await assign_workspace_system_role(session, user_id=user_id, workspace_id=workspace_id, role_name="player")
        ]
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


async def ensure_can_change_owner_role(session: AsyncSession, *, actor: Any, workspace_id: int) -> None:
    """403 unless ``actor`` may grant or revoke ``workspace_id``'s ``owner`` role: a superuser, or an owner there.

    The one rule every path that hands out or takes away ``owner`` applies (app-service member writes, identity's
    role assign/remove), on top of whatever permission that path already requires. Read from the database, not the
    actor's cached RBAC. Ownership transfer keeps its own gate.
    """
    if actor.is_superuser:
        return
    holds_owner = await session.scalar(
        sa.select(
            sa.exists().where(
                user_roles.c.user_id == actor.id,
                user_roles.c.role_id == Role.id,
                Role.workspace_id == workspace_id,
                Role.name == "owner",
            )
        )
    )
    if not holds_owner:
        raise BaseAPIException(status_code=403, detail=OWNER_ROLE_CHANGE_FORBIDDEN)


async def workspace_names_blocking_player_unlink(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[str]:
    """Distinct names of the workspaces where ``user_id`` holds a role beyond
    the baseline ``player`` role — i.e. staff RBAC memberships (``admin`` /
    ``owner`` / ``referee`` / ``host`` or a custom workspace role). Empty list
    means unlinking the user's player is allowed.

    Guards player-unlink. ``workspace_member`` is anchored on
    ``players.user.id`` while RBAC (``user_roles``) is keyed on
    ``auth_user_id``; clearing ``players.user.auth_user_id`` (unlink) would
    leave any such member row auth-less — hidden from the members list
    (``list_page`` joins ``auth.user``) and
    unmanageable via the auth-keyed ``get_member`` join. The caller refuses the
    unlink and names these workspaces so the user knows which to leave first.

    The baseline ``player`` role (auto-granted on enrollment and
    self-registration) is intentionally excluded: a plain participant holds no
    staff role, so unlinking their public player must stay allowed.
    """
    result = await session.execute(
        sa.select(Workspace.name)
        .select_from(
            user_roles.join(Role, Role.id == user_roles.c.role_id).join(Workspace, Workspace.id == Role.workspace_id)
        )
        .where(
            user_roles.c.user_id == user_id,
            Role.workspace_id.isnot(None),
            Role.name != "player",
        )
        .distinct()
        .order_by(Workspace.name)
    )
    return list(result.scalars().all())
