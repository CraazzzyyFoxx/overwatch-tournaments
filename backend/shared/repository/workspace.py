from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.models.identity.rbac import user_roles
from shared.repository.base import BaseRepository


class WorkspaceRepository(BaseRepository[models.Workspace]):
    def __init__(self) -> None:
        super().__init__(models.Workspace)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.Workspace | None:
        return await self.get_by(session, options=self.default_grid_options(), slug=slug)

    async def get_with_default_grid(self, session: AsyncSession, workspace_id: int) -> models.Workspace | None:
        return await self.get(session, workspace_id, options=self.default_grid_options())

    async def list_ordered(self, session: AsyncSession) -> Sequence[models.Workspace]:
        result = await session.execute(
            sa.select(models.Workspace)
            .options(*self.default_grid_options())
            .order_by(models.Workspace.id.asc())
        )
        return result.scalars().all()

    @staticmethod
    def default_grid_options() -> list[object]:
        return [
            selectinload(models.Workspace.default_division_grid_version).selectinload(
                models.DivisionGridVersion.tiers
            )
        ]


class WorkspaceMemberRepository(BaseRepository[models.WorkspaceMember]):
    def __init__(self) -> None:
        super().__init__(models.WorkspaceMember)

    async def get_member(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> models.WorkspaceMember | None:
        """Look up a member by the auth identity, joining through ``players.user``.

        ``workspace_member`` is anchored on ``player_id``; this join is the
        bridge so RPC/route callers that only know the current auth user's id
        can still resolve their membership row.
        """
        result = await session.execute(
            sa.select(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .options(selectinload(models.WorkspaceMember.player))
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.User.auth_user_id == auth_user_id,
            )
        )
        return result.scalars().first()

    async def get_by_player(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        player_id: int,
    ) -> models.WorkspaceMember | None:
        result = await session.execute(
            sa.select(models.WorkspaceMember).where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.player_id == player_id,
            )
        )
        return result.scalars().first()

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.WorkspaceMember]:
        """List the workspace's RBAC members — auth-linked players only.

        ``workspace_member`` is anchored on ``player_id`` and now holds two
        distinct populations: real RBAC members (auth users who joined via
        ``add_member``) and tournament participants anchored by
        registration / team / draft / achievement flows via
        ``get_or_create_workspace_member``. The latter frequently have no auth
        account (``players.user.auth_user_id IS NULL``) — they are pure
        tournament players, not workspace members.

        The RBAC members screen (``rpc.app.workspaces.members_list``) only
        deals with the former, and every downstream step resolves the row's
        auth identity (``get_member_auth_user_id``); an auth-less row would
        make the whole listing 500. The INNER JOIN on ``players.user`` plus the
        ``auth_user_id IS NOT NULL`` filter scope this to auth-linked members
        (mirrors ``get_member``'s bridge join).
        """
        result = await session.execute(
            sa.select(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .options(selectinload(models.WorkspaceMember.player))
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.User.auth_user_id.isnot(None),
            )
            .order_by(models.WorkspaceMember.id.asc())
        )
        return result.scalars().all()


async def get_or_create_workspace_member(
    session: AsyncSession,
    *,
    workspace_id: int,
    player_id: int,
) -> models.WorkspaceMember:
    """Idempotently create (or fetch) the membership row for ``player_id``.

    Insert-or-select on ``uq_workspace_member_workspace_player``: an
    ``INSERT ... ON CONFLICT DO NOTHING`` followed by a ``SELECT`` when the
    row already existed, so concurrent calls never raise
    ``IntegrityError``/duplicate-key races.
    """
    insert_stmt = (
        pg_insert(models.WorkspaceMember)
        .values(workspace_id=workspace_id, player_id=player_id)
        .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
        .returning(models.WorkspaceMember.id)
    )
    result = await session.execute(insert_stmt)
    member_id = result.scalar_one_or_none()
    if member_id is not None:
        await session.flush()
        member = await session.get(models.WorkspaceMember, member_id)
        assert member is not None
        return member

    existing = await WorkspaceMemberRepository().get_by_player(
        session, workspace_id=workspace_id, player_id=player_id
    )
    if existing is None:
        raise RuntimeError(
            f"get_or_create_workspace_member: no row after ON CONFLICT DO NOTHING "
            f"(workspace_id={workspace_id}, player_id={player_id})"
        )
    return existing


class RoleRepository(BaseRepository[models.Role]):
    def __init__(self) -> None:
        super().__init__(models.Role)

    async def get_by_name(
        self,
        session: AsyncSession,
        *,
        name: str,
        workspace_id: int | None = None,
    ) -> models.Role | None:
        return await self.get_by(session, name=name, workspace_id=workspace_id)

    async def list_for_user_workspace(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        workspace_id: int,
    ) -> list[models.Role]:
        result = await session.execute(
            sa.select(models.Role)
            .join(user_roles, user_roles.c.role_id == models.Role.id)
            .where(user_roles.c.user_id == user_id, models.Role.workspace_id == workspace_id)
            .order_by(models.Role.is_system.desc(), models.Role.name.asc())
        )
        return list(result.scalars().all())


class PermissionRepository(BaseRepository[models.Permission]):
    def __init__(self) -> None:
        super().__init__(models.Permission)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Permission | None:
        return await self.get_by(session, name=name)
