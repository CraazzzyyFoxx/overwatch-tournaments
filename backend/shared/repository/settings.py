from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository


class SettingsRepository(BaseRepository[models.Settings]):
    def __init__(self) -> None:
        super().__init__(models.Settings)

    async def get_by_key(self, session: AsyncSession, key: str) -> models.Settings | None:
        return await self.get_by(session, key=key)

    async def upsert(
        self,
        session: AsyncSession,
        key: str,
        value: dict,
        *,
        description: str | None = None,
        updated_by: int | None = None,
    ) -> models.Settings:
        """Create the row for ``key`` or replace its ``value`` wholesale.

        Transaction-neutral (flushes only); the caller commits.
        """
        instance = await self.get_by_key(session, key)
        if instance is None:
            instance = models.Settings(
                key=key,
                value=value,
                description=description,
                updated_by=updated_by,
            )
            return await self.create(session, instance)

        data: dict = {"value": value, "updated_by": updated_by}
        if description is not None:
            data["description"] = description
        return await self.update_fields(session, instance, data)
