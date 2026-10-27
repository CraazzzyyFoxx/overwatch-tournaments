"""Challonge link CRUD: the normalized ``challonge_source`` and its id mappings.

``challonge_source`` is the single source of truth for "this tournament/stage/stage-item
is mirrored on Challonge". ``ChallongeParticipantMapping``/``ChallongeMatchMapping``
translate Challonge's ids to local team/encounter ids under one source.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.repository.base import BaseRepository

TOURNAMENT_SOURCE_TYPE = "tournament"


class ChallongeSourceRepository(BaseRepository[models.ChallongeSource]):
    def __init__(self) -> None:
        super().__init__(models.ChallongeSource)

    async def get_tournament_source(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.ChallongeSource | None:
        """The ``source_type='tournament'`` row — the tournament-level Challonge link."""
        return await self.get_by(
            session,
            options=options,
            tournament_id=tournament_id,
            source_type=TOURNAMENT_SOURCE_TYPE,
        )

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        source_type: str | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.ChallongeSource]:
        filters: list[sa.ColumnElement[bool]] = [models.ChallongeSource.tournament_id == tournament_id]
        if source_type is not None:
            filters.append(models.ChallongeSource.source_type == source_type)
        query = self._apply_options(self.select().where(*filters), options)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def delete_tournament_source(self, session: AsyncSession, tournament_id: int) -> None:
        await session.execute(
            sa.delete(models.ChallongeSource).where(
                models.ChallongeSource.tournament_id == tournament_id,
                models.ChallongeSource.source_type == TOURNAMENT_SOURCE_TYPE,
            )
        )

    @staticmethod
    def linked_tournament_exists() -> sa.Exists:
        """Correlated ``EXISTS`` for "this tournament has any Challonge source".

        Used as a filter on a ``Tournament`` query rather than executed on its own.
        """
        return (
            sa.select(models.ChallongeSource.id)
            .where(models.ChallongeSource.tournament_id == models.Tournament.id)
            .exists()
        )


class ChallongeParticipantMappingRepository(BaseRepository[models.ChallongeParticipantMapping]):
    def __init__(self) -> None:
        super().__init__(models.ChallongeParticipantMapping)

    async def list_by_source_ids(
        self,
        session: AsyncSession,
        source_ids: Sequence[int],
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.ChallongeParticipantMapping]:
        if not source_ids:
            return []
        query = self._apply_options(
            self.select().where(models.ChallongeParticipantMapping.source_id.in_(tuple(source_ids))),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()


class ChallongeMatchMappingRepository(BaseRepository[models.ChallongeMatchMapping]):
    def __init__(self) -> None:
        super().__init__(models.ChallongeMatchMapping)

    async def list_by_source_ids(
        self,
        session: AsyncSession,
        source_ids: Sequence[int],
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.ChallongeMatchMapping]:
        """Match mappings for every source of a tournament, in ONE query.

        Mirrors ``ChallongeParticipantMappingRepository.list_by_source_ids``; one
        query per source would be an N+1 on the sync hot path.
        """
        if not source_ids:
            return []
        query = self._apply_options(
            self.select().where(models.ChallongeMatchMapping.source_id.in_(tuple(source_ids))),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_encounter_ids(self, session: AsyncSession, source_ids: Sequence[int]) -> Sequence[int]:
        if not source_ids:
            return []
        result = await session.execute(
            sa.select(models.ChallongeMatchMapping.encounter_id).where(
                models.ChallongeMatchMapping.source_id.in_(tuple(source_ids))
            )
        )
        return result.scalars().all()


class ChallongeSyncLogRepository(BaseRepository[models.ChallongeSyncLog]):
    def __init__(self) -> None:
        super().__init__(models.ChallongeSyncLog)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        limit: int | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.ChallongeSyncLog]:
        query = self._apply_options(
            self.select()
            .where(models.ChallongeSyncLog.tournament_id == tournament_id)
            .order_by(
                models.ChallongeSyncLog.created_at.desc(),
                models.ChallongeSyncLog.id.desc(),
            ),
            options,
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def delete_older_than(self, session: AsyncSession, cutoff: datetime, *, limit: int) -> int:
        """Drop up to ``limit`` rows created before ``cutoff``; returns how many went.

        Bounded so a retention job can run one short transaction per batch.
        """
        log = models.ChallongeSyncLog
        batch = sa.select(log.id).where(log.created_at < cutoff).limit(limit)
        result = await session.execute(
            sa.delete(log).where(log.id.in_(batch)).execution_options(synchronize_session=False)
        )
        return result.rowcount or 0


__all__ = (
    "TOURNAMENT_SOURCE_TYPE",
    "ChallongeMatchMappingRepository",
    "ChallongeParticipantMappingRepository",
    "ChallongeSourceRepository",
    "ChallongeSyncLogRepository",
)
