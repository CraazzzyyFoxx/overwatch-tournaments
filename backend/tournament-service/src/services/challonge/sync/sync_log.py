"""The ``challonge_sync_log`` audit trail and its daily purge."""

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.repository import (
    ChallongeSyncLogRepository,
)
from src.core import db

#: ``challonge_sync_log`` rows older than this go in the daily purge.
SYNC_LOG_RETENTION = timedelta(days=30)
SYNC_LOG_PURGE_BATCH = 5000


class ChallongeSyncLogService:
    """The ``challonge_sync_log`` audit trail: every import/export write, conflict and failure.

    An imported match Challonge left unchanged writes no row. Rows older than
    ``SYNC_LOG_RETENTION`` go in ``purge_sync_log``.

    Its own collaborator rather than a method on ``ChallongeSyncService`` because
    ``ChallongeMappingService`` writes to the same trail when it auto-maps
    participants, and injecting the whole orchestration service into the mapping
    service just to reach one write would be circular.
    """

    def __init__(self, *, sync_log_repo: ChallongeSyncLogRepository = ChallongeSyncLogRepository()) -> None:
        self.sync_log_repo = sync_log_repo

    async def _log_sync(
        self,
        session: AsyncSession,
        tournament_id: int,
        direction: str,
        entity_type: str,
        entity_id: int | None,
        challonge_id: int | None,
        status: str,
        *,
        source_id: int | None = None,
        operation: str | None = None,
        payload: dict | None = None,
        conflict_type: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        error_message: str | None = None,
    ) -> models.ChallongeSyncLog:
        entry = models.ChallongeSyncLog(
            tournament_id=tournament_id,
            source_id=source_id,
            direction=direction,
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            challonge_id=challonge_id,
            status=status,
            conflict_type=conflict_type,
            payload_json=payload,
            before_json=before,
            after_json=after,
            error_message=error_message,
        )
        return await self.sync_log_repo.create(session, entry)

    async def get_sync_log(
        self, session: AsyncSession, tournament_id: int, limit: int = 50
    ) -> list[models.ChallongeSyncLog]:
        return list(await self.sync_log_repo.list_by_tournament(session, tournament_id, limit=limit))


async def purge_sync_log(session_factory: async_sessionmaker[AsyncSession] = db.async_session_maker) -> int:
    """Delete sync-log rows older than ``SYNC_LOG_RETENTION``; returns how many went.

    Daily scheduler job. ``SYNC_LOG_PURGE_BATCH`` rows per transaction so no single delete holds locks or bloats WAL
    for long.
    """
    cutoff = datetime.now(UTC) - SYNC_LOG_RETENTION
    deleted = 0
    while True:
        async with session_factory() as session:
            count = await sync_log_service.sync_log_repo.delete_older_than(session, cutoff, limit=SYNC_LOG_PURGE_BATCH)
            await session.commit()
        deleted += count
        if count < SYNC_LOG_PURGE_BATCH:
            break
    if deleted:
        logger.info("Purged {} Challonge sync-log rows", deleted)
    return deleted


sync_log_service = ChallongeSyncLogService()
