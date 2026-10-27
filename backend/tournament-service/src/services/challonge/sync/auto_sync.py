"""The periodic Challonge -> local pull of every active linked tournament."""

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.core import enums
from src.core import config

# "Active" = matches are in play.
ACTIVE_TOURNAMENT_STATUSES = (
    enums.TournamentStatus.LIVE,
    enums.TournamentStatus.PLAYOFFS,
)


class AutoSyncMixin:
    """``ChallongeSyncService``'s background auto-sync; the service owns the repositories."""

    async def list_active_challonge_tournament_ids(self, session: AsyncSession) -> list[int]:
        """Active tournaments that have a Challonge link, i.e. any ``challonge_source`` row."""
        result = await session.execute(
            sa.select(models.Tournament.id)
            .where(
                models.Tournament.status.in_(ACTIVE_TOURNAMENT_STATUSES),
                self.source_repo.linked_tournament_exists(),
            )
            .order_by(models.Tournament.id.asc())
        )
        return list(result.scalars().all())

    async def sync_active_challonge_tournaments(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> list[dict]:
        """Periodic pull: import every active Challonge-linked tournament.

        Runs in the worker. No-ops when disabled or when credentials are missing (otherwise it would
        spam 401s every interval). Each tournament is imported in its own session — ``import_tournament``
        commits and takes its own Redis lock — so one failure never aborts the rest.
        """
        if not config.settings.challonge_auto_sync_enabled:
            return []
        if not (config.settings.challonge_username and config.settings.challonge_api_key):
            logger.warning("Challonge auto-sync skipped: credentials are not configured")
            return []

        async with session_factory() as session:
            tournament_ids = await self.list_active_challonge_tournament_ids(session)

        results: list[dict] = []
        for tournament_id in tournament_ids:
            async with session_factory() as session:
                try:
                    stats = await self.import_tournament(session, tournament_id)
                    results.append(
                        {
                            "tournament_id": tournament_id,
                            "status": "success",
                            "created": stats.get("created", 0),
                            "updated": stats.get("updated", 0),
                            "conflicts": stats.get("conflicts", 0),
                            "errors": stats.get("errors", 0),
                            "matches_synced": stats.get("matches_synced", 0),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Challonge auto-sync failed for tournament {}", tournament_id)
                    results.append(
                        {
                            "tournament_id": tournament_id,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
        return results
