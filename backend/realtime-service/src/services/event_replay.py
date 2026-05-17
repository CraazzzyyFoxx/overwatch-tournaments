from __future__ import annotations

import sqlalchemy as sa
from shared.models.realtime import WorkspaceEvent
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import config


class ReplayGapTooLarge(Exception):
    pass


class EventReplayService:
    async def current_cursor(self, session: AsyncSession, topic: str) -> int:
        cursor = await session.scalar(
            sa.select(sa.func.coalesce(sa.func.max(WorkspaceEvent.id), 0)).where(WorkspaceEvent.topic == topic)
        )
        return int(cursor or 0)

    async def since(
        self,
        session: AsyncSession,
        *,
        topic: str,
        after_event_id: int | None,
        up_to_event_id: int,
    ) -> list[WorkspaceEvent]:
        after = int(after_event_id or 0)
        limit = config.settings.ws_replay_limit
        result = await session.execute(
            sa.select(WorkspaceEvent)
            .where(
                WorkspaceEvent.topic == topic,
                WorkspaceEvent.id > after,
                WorkspaceEvent.id <= up_to_event_id,
            )
            .order_by(WorkspaceEvent.id.asc())
            .limit(limit + 1)
        )
        events = list(result.scalars().all())
        if len(events) > limit:
            raise ReplayGapTooLarge
        return events


event_replay_service = EventReplayService()
