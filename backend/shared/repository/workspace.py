from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.models.rbac import user_roles
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
        result = await session.execute(
            sa.select(models.WorkspaceMember)
            .options(selectinload(models.WorkspaceMember.auth_user).selectinload(models.AuthUser.roles))
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.auth_user_id == auth_user_id,
            )
        )
        return result.scalars().first()

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.WorkspaceMember]:
        result = await session.execute(
            sa.select(models.WorkspaceMember)
            .options(selectinload(models.WorkspaceMember.auth_user).selectinload(models.AuthUser.roles))
            .where(models.WorkspaceMember.workspace_id == workspace_id)
            .order_by(models.WorkspaceMember.id.asc())
        )
        return result.scalars().all()


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
