import typing

import sqlalchemy as sa
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.rbac import user_roles
from shared.rbac import (
    ensure_workspace_system_roles,
    legacy_workspace_role_name_for_user,
    replace_user_workspace_roles,
    user_has_only_workspace_owner_role,
)
from shared.repository import (
    RoleRepository,
    UserRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
    get_or_create_workspace_member,
)
from shared.services import division_grid_cache
from shared.services.division_grid_access import get_default_division_grid_version_id
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

_role_repo = RoleRepository()
_workspace_member_repo = WorkspaceMemberRepository()
_workspace_repo = WorkspaceRepository()
_user_repo = UserRepository()


async def get_by_id(session: AsyncSession, workspace_id: int) -> models.Workspace | None:
    return await _workspace_repo.get_with_default_grid(session, workspace_id)


async def get_by_slug(session: AsyncSession, slug: str) -> models.Workspace | None:
    return await _workspace_repo.get_by_slug(session, slug)


async def get_all(session: AsyncSession) -> typing.Sequence[models.Workspace]:
    return await _workspace_repo.list_ordered(session)


async def get_user_workspaces(
    session: AsyncSession, auth_user_id: int
) -> typing.Sequence[tuple[models.Workspace, str]]:
    """Workspaces ``auth_user_id`` belongs to, with the RBAC-derived legacy role name.

    ``workspace_member`` no longer stores a denormalized ``role`` column; the
    role string is computed per-workspace from ``user_roles`` (RBAC), which
    stays keyed on ``auth_user_id``.
    """
    result = await session.execute(
        sa.select(models.Workspace)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.workspace_id == models.Workspace.id,
        )
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(models.User.auth_user_id == auth_user_id)
        .order_by(models.Workspace.id)
    )
    workspaces = result.scalars().all()
    return [
        (
            workspace,
            await legacy_workspace_role_name_for_user(
                session, user_id=auth_user_id, workspace_id=workspace.id
            ),
        )
        for workspace in workspaces
    ]


async def _resolve_default_division_grid_version_id(
    session: AsyncSession,
    version_id: int | None,
) -> int:
    if version_id is not None:
        return version_id

    resolved_version_id = await get_default_division_grid_version_id(session)
    if resolved_version_id is None:
        raise RuntimeError("System default division grid version is not configured")
    return resolved_version_id


async def create(session: AsyncSession, **kwargs) -> models.Workspace:
    payload = dict(kwargs)
    payload["default_division_grid_version_id"] = await _resolve_default_division_grid_version_id(
        session,
        payload.get("default_division_grid_version_id"),
    )

    workspace = models.Workspace(**payload)
    return await _workspace_repo.create(session, workspace)


async def update(
    session: AsyncSession, workspace: models.Workspace, data: dict
) -> models.Workspace:
    resolved_data = dict(data)
    if "default_division_grid_version_id" in resolved_data:
        resolved_data["default_division_grid_version_id"] = await _resolve_default_division_grid_version_id(
            session,
            resolved_data["default_division_grid_version_id"],
        )

    should_invalidate_grid = (
        "default_division_grid_version_id" in resolved_data
        and resolved_data["default_division_grid_version_id"] != workspace.default_division_grid_version_id
    )
    await _workspace_repo.update_fields(session, workspace, resolved_data)
    if should_invalidate_grid:
        await division_grid_cache.invalidate_workspace(workspace.id)
    return workspace


async def delete(session: AsyncSession, workspace: models.Workspace) -> None:
    await _workspace_repo.delete(session, workspace)


async def get_members(
    session: AsyncSession, workspace_id: int
) -> typing.Sequence[models.WorkspaceMember]:
    return await _workspace_member_repo.list_by_workspace(session, workspace_id)


async def get_member(
    session: AsyncSession, workspace_id: int, auth_user_id: int
) -> models.WorkspaceMember | None:
    return await _workspace_member_repo.get_member(
        session,
        workspace_id=workspace_id,
        auth_user_id=auth_user_id,
    )


async def _resolve_player_id_for_auth_user(session: AsyncSession, auth_user_id: int) -> int:
    """Resolve the ``players.user.id`` linked to ``auth_user_id``.

    Post-Phase-A every signup provisions a ``players.user`` row, so a caller
    reaching here with a real auth user should always resolve. A miss means
    the identity link is broken (pre-Phase-A leftover / data bug) and is
    treated as a hard error rather than silently skipped.
    """
    player = await _user_repo.get_by_auth_user_id(session, auth_user_id)
    if player is None:
        raise HTTPException(
            status_code=500,
            detail=f"No players.user is linked to auth_user_id={auth_user_id}; cannot add workspace member",
        )
    return player.id


async def add_member(
    session: AsyncSession, workspace_id: int, auth_user_id: int
) -> models.WorkspaceMember:
    """Create (or fetch) the membership row for the player linked to ``auth_user_id``.

    Callers keep passing ``auth_user_id`` (unchanged signature); internally we
    resolve the ``player_id`` the ``workspace_member`` row is actually
    anchored on. No longer accepts/writes a ``role`` — the column was dropped;
    RBAC (``user_roles``, keyed on ``auth_user_id``) is the source of truth.
    """
    await ensure_workspace_system_roles(session, workspace_id)
    player_id = await _resolve_player_id_for_auth_user(session, auth_user_id)
    return await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)


async def add_member_with_roles(
    session: AsyncSession,
    workspace_id: int,
    auth_user_id: int,
    *,
    role_ids: list[int],
    legacy_role: str = "member",
) -> models.WorkspaceMember:
    member = await add_member(session, workspace_id, auth_user_id)
    await replace_user_workspace_roles(
        session,
        user_id=auth_user_id,
        workspace_id=workspace_id,
        role_ids=role_ids,
    )
    await session.flush()
    # ``updated_at`` (onupdate=func.now()) is server-computed and gets expired by
    # the flush; refresh inside the async context so callers can read it without
    # triggering a lazy load outside the greenlet (sqlalchemy.exc.MissingGreenlet).
    await session.refresh(member)
    return member


async def _workspace_roles_from_ids(
    session: AsyncSession,
    workspace_id: int,
    role_ids: list[int],
) -> list[models.Role]:
    if not role_ids:
        return []
    roles = await _role_repo.bulk_get(
        session,
        role_ids,
    )
    roles = [role for role in roles if role.workspace_id == workspace_id]
    if len({role.id for role in roles}) != len(set(role_ids)):
        raise ValueError("All role_ids must refer to roles in the target workspace")
    return roles


async def get_member_auth_user_id(session: AsyncSession, member: models.WorkspaceMember) -> int:
    """Resolve the RBAC (``auth.user.id``) identity behind a membership row.

    ``workspace_member`` is anchored on ``player_id``; RBAC (``user_roles``,
    role assignment, ownership checks) stays keyed on ``auth_user_id``. This
    is the bridge between the two for code that only has the member row.
    """
    player = await _user_repo.get(session, member.player_id)
    if player is None or player.auth_user_id is None:
        raise HTTPException(
            status_code=500,
            detail=f"workspace_member {member.id} has no linked auth user (player_id={member.player_id})",
        )
    return player.auth_user_id


async def update_member_roles(
    session: AsyncSession,
    member: models.WorkspaceMember,
    *,
    role_ids: list[int],
) -> models.WorkspaceMember:
    auth_user_id = await get_member_auth_user_id(session, member)
    if await user_has_only_workspace_owner_role(
        session,
        user_id=auth_user_id,
        workspace_id=member.workspace_id,
    ):
        roles = await _workspace_roles_from_ids(session, member.workspace_id, role_ids)
        if all(role.name != "owner" for role in roles):
            raise ValueError("Cannot remove the last workspace owner")

    await replace_user_workspace_roles(
        session,
        user_id=auth_user_id,
        workspace_id=member.workspace_id,
        role_ids=role_ids,
    )
    await session.flush()
    # ``updated_at`` (onupdate=func.now()) is server-computed and gets expired by
    # the flush; refresh inside the async context so callers can read it without
    # triggering a lazy load outside the greenlet (sqlalchemy.exc.MissingGreenlet).
    await session.refresh(member)
    return member


async def get_member_workspace_roles(
    session: AsyncSession,
    workspace_id: int,
    auth_user_id: int,
) -> list[models.Role]:
    return await _role_repo.list_for_user_workspace(
        session,
        user_id=auth_user_id,
        workspace_id=workspace_id,
    )


async def can_remove_member(session: AsyncSession, member: models.WorkspaceMember) -> bool:
    auth_user_id = await get_member_auth_user_id(session, member)
    return not await user_has_only_workspace_owner_role(
        session,
        user_id=auth_user_id,
        workspace_id=member.workspace_id,
    )


async def remove_member(session: AsyncSession, member: models.WorkspaceMember) -> None:
    auth_user_id = await get_member_auth_user_id(session, member)
    await session.execute(
        sa.delete(user_roles).where(
            user_roles.c.user_id == auth_user_id,
            user_roles.c.role_id.in_(
                sa.select(models.Role.id).where(models.Role.workspace_id == member.workspace_id)
            ),
        )
    )
    await session.delete(member)
    await session.flush()
