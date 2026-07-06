import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.rbac import user_roles
from shared.rbac import (
    WORKSPACE_SYSTEM_ROLE_NAMES,
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
from src import models

_role_repo = RoleRepository()
_workspace_member_repo = WorkspaceMemberRepository()
_workspace_repo = WorkspaceRepository()
_user_repo = UserRepository()


async def get_by_id(session: AsyncSession, workspace_id: int) -> models.Workspace | None:
    return await _workspace_repo.get_with_default_grid(session, workspace_id)


async def get_by_slug(session: AsyncSession, slug: str) -> models.Workspace | None:
    return await _workspace_repo.get_by_slug(session, slug)


async def get_by_subdomain(session: AsyncSession, subdomain: str) -> models.Workspace | None:
    return await _workspace_repo.get_by_subdomain(session, subdomain)


async def get_by_custom_domain(session: AsyncSession, domain: str) -> models.Workspace | None:
    """Resolve a verified custom domain to its workspace (Phase 2 of ``by_host``).

    Delegates to the verified-only repo query — an unverified ``custom_domain``
    never resolves here.
    """
    return await _workspace_repo.get_by_verified_custom_domain(session, domain)


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
            await legacy_workspace_role_name_for_user(session, user_id=auth_user_id, workspace_id=workspace.id),
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


async def update(session: AsyncSession, workspace: models.Workspace, data: dict) -> models.Workspace:
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


async def get_members(session: AsyncSession, workspace_id: int) -> typing.Sequence[models.WorkspaceMember]:
    return await _workspace_member_repo.list_by_workspace(session, workspace_id)


_UNLIMITED_MEMBERS_CAP = 10_000
MEMBERS_SORT_FIELDS = ("username", "role")
_ROLELESS_RANK = 99


def _members_filtered_query(
    base: sa.Select, workspace_id: int, search: str | None, role_id: int | None = None
) -> sa.Select:
    """Attach the auth-linked join + workspace filter (+ optional username/email
    search + optional role filter) shared by the count and page queries.

    Auth-linked only (INNER JOIN ``players.user`` + ``auth.user``) so the
    ``auth_user_id IS NOT NULL`` invariant holds and every row resolves an auth
    identity — the same scoping ``list_by_workspace`` applies. ``role_id`` narrows
    to members whose auth user holds that (workspace-scoped) role.
    """
    base = (
        base.join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .join(models.AuthUser, models.AuthUser.id == models.User.auth_user_id)
        .where(models.WorkspaceMember.workspace_id == workspace_id)
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        base = base.where(sa.or_(models.AuthUser.username.ilike(like), models.AuthUser.email.ilike(like)))
    if role_id is not None:
        base = base.where(
            sa.exists().where(
                user_roles.c.user_id == models.AuthUser.id,
                user_roles.c.role_id == role_id,
            )
        )
    return base


def _primary_role_rank(workspace_id: int):
    """Correlated scalar: the highest system role rank the current ``auth.user``
    holds in ``workspace_id`` (owner=0 … player=3; custom/none -> 99), used to
    ORDER BY the effective primary role."""
    rank_case = sa.case(
        *[(models.Role.name == name, idx) for idx, name in enumerate(WORKSPACE_SYSTEM_ROLE_NAMES)],
        else_=_ROLELESS_RANK,
    )
    return (
        sa.select(sa.func.coalesce(sa.func.min(rank_case), _ROLELESS_RANK))
        .select_from(user_roles.join(models.Role, models.Role.id == user_roles.c.role_id))
        .where(user_roles.c.user_id == models.AuthUser.id, models.Role.workspace_id == workspace_id)
        .correlate(models.AuthUser)
        .scalar_subquery()
    )


async def list_members_page(
    session: AsyncSession,
    workspace_id: int,
    *,
    page: int,
    per_page: int,
    search: str | None,
    role_id: int | None = None,
    sort: str = "username",
    order: str = "asc",
) -> tuple[int, list[tuple[models.WorkspaceMember, models.AuthUser, list[models.Role]]]]:
    """Paginated + searchable + role-filterable/sortable RBAC members, batched to
    kill the per-row N+1 the old ``_member_payload`` loop incurred.

    Returns ``(total, [(member, auth_user, workspace_roles)])``. Roles for the
    whole page are loaded in a single query and grouped in memory, so the cost is
    ~3 queries (count + page + roles) regardless of page size. ``per_page == -1``
    returns all members (capped) for selector/combobox callers. ``sort`` is one of
    ``username`` / ``role`` (primary system-role rank); ``order`` is ``asc`` /
    ``desc``.
    """
    descending = order == "desc"
    total = (
        await session.scalar(
            _members_filtered_query(
                sa.select(sa.func.count()).select_from(models.WorkspaceMember),
                workspace_id,
                search,
                role_id,
            )
        )
        or 0
    )

    if sort == "role":
        rank = _primary_role_rank(workspace_id)
        order_cols = [
            rank.desc() if descending else rank.asc(),
            models.AuthUser.username.asc(),
            models.WorkspaceMember.id.asc(),
        ]
    else:
        name_col = models.AuthUser.username
        order_cols = [
            name_col.desc() if descending else name_col.asc(),
            models.WorkspaceMember.id.asc(),
        ]

    page_q = _members_filtered_query(
        sa.select(models.WorkspaceMember, models.AuthUser), workspace_id, search, role_id
    ).order_by(*order_cols)
    if per_page == -1:
        page_q = page_q.limit(_UNLIMITED_MEMBERS_CAP)
    else:
        page_q = page_q.offset(max(page - 1, 0) * per_page).limit(per_page)

    rows = (await session.execute(page_q)).all()
    auth_ids = [auth_user.id for (_member, auth_user) in rows]

    roles_by_user: dict[int, list[models.Role]] = {}
    if auth_ids:
        role_rows = await session.execute(
            sa.select(user_roles.c.user_id, models.Role)
            .join(models.Role, models.Role.id == user_roles.c.role_id)
            .where(
                user_roles.c.user_id.in_(auth_ids),
                models.Role.workspace_id == workspace_id,
            )
        )
        for user_id, role in role_rows.all():
            roles_by_user.setdefault(user_id, []).append(role)

    return total, [(member, auth_user, roles_by_user.get(auth_user.id, [])) for (member, auth_user) in rows]


async def autofill_member_roles(session: AsyncSession, workspace_id: int) -> int:
    """Grant the baseline ``member`` role to every auth-linked member of
    ``workspace_id`` whose auth user currently holds no role there.

    Set-based and idempotent (the ``NOT EXISTS`` guard only touches role-less
    members, so re-running assigns nothing and never duplicates). Ensures the
    workspace system roles exist first so the ``member`` role is guaranteed
    present. Returns the number of grants inserted.
    """
    await ensure_workspace_system_roles(session, workspace_id)
    result = await session.execute(
        sa.text(
            """
            INSERT INTO auth.user_roles (user_id, role_id)
            SELECT DISTINCT pu.auth_user_id, r.id
            FROM workspace_member wm
            JOIN players."user" pu ON pu.id = wm.player_id AND pu.auth_user_id IS NOT NULL
            JOIN auth.roles r ON r.workspace_id = wm.workspace_id AND r.name = 'member'
            WHERE wm.workspace_id = :workspace_id
              AND NOT EXISTS (
                SELECT 1 FROM auth.user_roles ur
                JOIN auth.roles r2 ON r2.id = ur.role_id
                WHERE ur.user_id = pu.auth_user_id AND r2.workspace_id = wm.workspace_id
              )
            """
        ),
        {"workspace_id": workspace_id},
    )
    return result.rowcount or 0


async def get_member(session: AsyncSession, workspace_id: int, auth_user_id: int) -> models.WorkspaceMember | None:
    return await _workspace_member_repo.get_member(
        session,
        workspace_id=workspace_id,
        auth_user_id=auth_user_id,
    )


async def _resolve_player_id_for_auth_user(session: AsyncSession, auth_user_id: int) -> int:
    """Resolve the ``players.user.id`` linked to ``auth_user_id``, provisioning a
    bare player if none exists.

    ``workspace_member`` is anchored on ``player_id``, so adding a member needs
    the auth user to have a linked ``players.user``. Post-Phase-A signups get one
    automatically, but legacy accounts (registered before that provisioning) have
    none — and Add Member explicitly targets staff who never played. Rather than
    500 on such users, provision the identity backbone on demand (mirrors
    ``ensure_player_for_auth_user``); the auth user's existence is validated by
    the caller (member_add) before we get here.
    """
    auth_user = await session.get(models.AuthUser, auth_user_id)
    name_hint = (auth_user.username or auth_user.email) if auth_user is not None else None
    player = await _user_repo.ensure_for_auth_user(session, auth_user_id=auth_user_id, name_hint=name_hint)
    return player.id


async def add_member(session: AsyncSession, workspace_id: int, auth_user_id: int) -> models.WorkspaceMember:
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
            user_roles.c.role_id.in_(sa.select(models.Role.id).where(models.Role.workspace_id == member.workspace_id)),
        )
    )
    await session.delete(member)
    await session.flush()
