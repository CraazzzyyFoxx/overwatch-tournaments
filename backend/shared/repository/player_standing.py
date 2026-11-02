from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository


class PlayerStandingPinRepository(BaseRepository[models.PlayerStandingPin]):
    def __init__(self) -> None:
        super().__init__(models.PlayerStandingPin)

    async def replace(
        self,
        session: AsyncSession,
        *,
        stage_id: int,
        pins: Sequence[models.PlayerStandingPin],
    ) -> None:
        """Replace one stage's pins; the delete runs before the new rows flush, so the unique index never sees both."""
        await session.execute(sa.delete(models.PlayerStandingPin).where(models.PlayerStandingPin.stage_id == stage_id))
        await self.create_many(session, pins)


class PlayerStandingRepository(BaseRepository[models.PlayerStanding]):
    def __init__(self) -> None:
        super().__init__(models.PlayerStanding)

    async def for_stage(self, session: AsyncSession, stage_id: int) -> list[models.PlayerStanding]:
        result = await session.scalars(
            self.select().where(models.PlayerStanding.stage_id == stage_id).order_by(models.PlayerStanding.id)
        )
        return list(result.all())

    async def delete_for_stage(self, session: AsyncSession, stage_id: int) -> None:
        await session.execute(sa.delete(models.PlayerStanding).where(models.PlayerStanding.stage_id == stage_id))
