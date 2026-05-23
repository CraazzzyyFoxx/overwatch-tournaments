from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.repository.base import BaseRepository


class BalancerRegistrationRepository(BaseRepository[models.BalancerRegistration]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistration)

    async def get_active_for_user(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user_id: int,
    ) -> models.BalancerRegistration | None:
        result = await session.execute(
            sa.select(models.BalancerRegistration)
            .options(selectinload(models.BalancerRegistration.roles))
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.auth_user_id == auth_user_id,
                models.BalancerRegistration.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_active_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.BalancerRegistration]:
        result = await session.execute(
            sa.select(models.BalancerRegistration)
            .options(selectinload(models.BalancerRegistration.roles))
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
            )
            .order_by(models.BalancerRegistration.id.asc())
        )
        return result.scalars().all()


class RegistrationFormRepository(BaseRepository[models.BalancerRegistrationForm]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationForm)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerRegistrationForm | None:
        return await self.get_by(session, tournament_id=tournament_id)


class RegistrationStatusRepository(BaseRepository[models.BalancerRegistrationStatus]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationStatus)

    async def get_by_slug(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None,
        scope: str,
        slug: str,
        kind: str | None = None,
    ) -> models.BalancerRegistrationStatus | None:
        filters: list[sa.ColumnElement[bool]] = [
            models.BalancerRegistrationStatus.workspace_id.is_(None)
            if workspace_id is None
            else models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == slug,
        ]
        if kind is not None:
            filters.append(models.BalancerRegistrationStatus.kind == kind)
        result = await session.execute(sa.select(models.BalancerRegistrationStatus).where(*filters))
        return result.scalar_one_or_none()

    async def list_for_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        scope: str | None = None,
    ) -> Sequence[models.BalancerRegistrationStatus]:
        filters: list[sa.ColumnElement[bool]] = [
            sa.or_(
                models.BalancerRegistrationStatus.workspace_id == workspace_id,
                models.BalancerRegistrationStatus.workspace_id.is_(None),
            )
        ]
        if scope is not None:
            filters.append(models.BalancerRegistrationStatus.scope == scope)
        result = await session.execute(
            sa.select(models.BalancerRegistrationStatus)
            .where(*filters)
            .order_by(
                models.BalancerRegistrationStatus.scope.asc(),
                sa.case((models.BalancerRegistrationStatus.workspace_id.is_(None), 0), else_=1).asc(),
                models.BalancerRegistrationStatus.kind.asc(),
                models.BalancerRegistrationStatus.name.asc(),
                models.BalancerRegistrationStatus.id.asc(),
            )
        )
        return result.scalars().all()


class GoogleSheetFeedRepository(BaseRepository[models.BalancerRegistrationGoogleSheetFeed]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationGoogleSheetFeed)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerRegistrationGoogleSheetFeed | None:
        return await self.get_by(session, tournament_id=tournament_id)
