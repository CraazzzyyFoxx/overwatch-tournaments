"""Row access for the ``quota`` policy tables.

Thin on purpose: the interesting part of a quota write is the authority rule
(``shared.quota.admin``), not the persistence. What lives here is only what the
repository boundary asks for -- nobody outside this module adds, deletes or
flushes a quota row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

__all__ = (
    "QuotaApiKeyLimitRepository",
    "QuotaOperationRepository",
    "QuotaPlanLimitRepository",
    "QuotaPlanRepository",
    "QuotaWorkspaceLimitRepository",
)


class QuotaPlanRepository(BaseRepository[models.QuotaPlan]):
    def __init__(self) -> None:
        super().__init__(models.QuotaPlan)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.QuotaPlan | None:
        return await self.get_by(session, slug=slug)

    async def list_all(self, session: AsyncSession) -> list[models.QuotaPlan]:
        rows = await session.execute(select(models.QuotaPlan).order_by(models.QuotaPlan.slug))
        return list(rows.scalars().all())

    async def create_plan(
        self,
        session: AsyncSession,
        *,
        slug: str,
        title: str,
        description: str | None,
    ) -> models.QuotaPlan:
        return await self.create(session, models.QuotaPlan(slug=slug, title=title, description=description))


class QuotaPlanLimitRepository(BaseRepository[models.QuotaPlanLimit]):
    def __init__(self) -> None:
        super().__init__(models.QuotaPlanLimit)

    async def list_all(self, session: AsyncSession) -> list[models.QuotaPlanLimit]:
        rows = await session.execute(select(models.QuotaPlanLimit))
        return list(rows.scalars().all())

    async def get_for(self, session: AsyncSession, *, plan_id: int, scope: str) -> models.QuotaPlanLimit | None:
        return await self.get_by(session, plan_id=plan_id, scope=scope)

    async def replace_for_plan(
        self,
        session: AsyncSession,
        *,
        plan_id: int,
        rows: list[dict[str, Any]],
    ) -> None:
        """Swap a plan's scope rows wholesale.

        A plan is read as a complete statement of its tier, so a partial update
        would leave a scope nobody remembers setting.
        """
        await session.execute(delete(models.QuotaPlanLimit).where(models.QuotaPlanLimit.plan_id == plan_id))
        for row in rows:
            await self.create(session, models.QuotaPlanLimit(plan_id=plan_id, **row))


class QuotaOperationRepository(BaseRepository[models.QuotaOperation]):
    def __init__(self) -> None:
        super().__init__(models.QuotaOperation)

    async def list_all(self, session: AsyncSession) -> list[models.QuotaOperation]:
        rows = await session.execute(select(models.QuotaOperation).order_by(models.QuotaOperation.slug))
        return list(rows.scalars().all())

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.QuotaOperation | None:
        return await self.get_by(session, slug=slug)

    async def upsert(
        self,
        session: AsyncSession,
        *,
        slug: str,
        cost: int,
        enabled: bool,
        description: str | None,
    ) -> models.QuotaOperation:
        instance = await self.get_by_slug(session, slug)
        fields = {"cost": cost, "enabled": enabled, "description": description}
        if instance is None:
            return await self.create(session, models.QuotaOperation(slug=slug, **fields))
        return await self.update_fields(session, instance, fields)


class QuotaWorkspaceLimitRepository(BaseRepository[models.QuotaWorkspaceLimit]):
    def __init__(self) -> None:
        super().__init__(models.QuotaWorkspaceLimit)

    async def get_for(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        scope: str,
    ) -> models.QuotaWorkspaceLimit | None:
        return await self.get_by(session, workspace_id=workspace_id, scope=scope)

    async def upsert(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        scope: str,
        values: dict[str, int | None],
        updated_by: int | None,
    ) -> models.QuotaWorkspaceLimit:
        instance = await self.get_for(session, workspace_id=workspace_id, scope=scope)
        fields = {**values, "updated_by": updated_by}
        if instance is None:
            return await self.create(
                session,
                models.QuotaWorkspaceLimit(workspace_id=workspace_id, scope=scope, **fields),
            )
        return await self.update_fields(session, instance, fields)

    async def remove(self, session: AsyncSession, *, workspace_id: int, scope: str) -> None:
        instance = await self.get_for(session, workspace_id=workspace_id, scope=scope)
        if instance is not None:
            await self.delete(session, instance)


class QuotaApiKeyLimitRepository(BaseRepository[models.QuotaApiKeyLimit]):
    def __init__(self) -> None:
        super().__init__(models.QuotaApiKeyLimit)

    async def get_for(self, session: AsyncSession, *, api_key_id: int) -> models.QuotaApiKeyLimit | None:
        return await self.get_by(session, api_key_id=api_key_id)

    async def upsert(
        self,
        session: AsyncSession,
        *,
        api_key_id: int,
        values: dict[str, int | None],
        updated_by: int | None,
    ) -> models.QuotaApiKeyLimit:
        instance = await self.get_for(session, api_key_id=api_key_id)
        fields = {**values, "updated_by": updated_by}
        if instance is None:
            return await self.create(session, models.QuotaApiKeyLimit(api_key_id=api_key_id, **fields))
        return await self.update_fields(session, instance, fields)

    async def remove(self, session: AsyncSession, *, api_key_id: int) -> None:
        instance = await self.get_for(session, api_key_id=api_key_id)
        if instance is not None:
            await self.delete(session, instance)
