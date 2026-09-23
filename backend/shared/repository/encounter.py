"""Encounter-satellite CRUD: captain reports, map reports, audits, saved views, links.

The ``Encounter`` row itself lives in :mod:`shared.repository.tournament`
(``EncounterRepository``); this module owns the tables that hang off it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import enums
from shared.repository.base import BaseRepository


class EncounterCaptainReportRepository(BaseRepository[models.EncounterCaptainReport]):
    def __init__(self) -> None:
        super().__init__(models.EncounterCaptainReport)

    async def list_for_encounter(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.EncounterCaptainReport]:
        query = self._apply_options(
            self.select().where(models.EncounterCaptainReport.encounter_id == encounter_id),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_for_team(
        self,
        session: AsyncSession,
        *,
        encounter_id: int,
        team_id: int,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.EncounterCaptainReport | None:
        return await self.get_by(session, options=options, encounter_id=encounter_id, team_id=team_id)


class EncounterMapCodeRepository(BaseRepository[models.EncounterMapCode]):
    def __init__(self) -> None:
        super().__init__(models.EncounterMapCode)

    async def list_for_report(self, session: AsyncSession, report_id: int) -> Sequence[models.EncounterMapCode]:
        result = await session.execute(
            self.select()
            .where(models.EncounterMapCode.report_id == report_id)
            .order_by(models.EncounterMapCode.map_index)
        )
        return result.scalars().all()

    async def delete_for_report(self, session: AsyncSession, report_id: int) -> None:
        await session.execute(sa.delete(models.EncounterMapCode).where(models.EncounterMapCode.report_id == report_id))

    async def list_for_reports(
        self, session: AsyncSession, report_ids: Sequence[int]
    ) -> Sequence[models.EncounterMapCode]:
        """Map codes for many reports in ONE query, ordered by ``map_index``.

        The captain-report read documents itself as a fixed two-query load; looping
        ``list_for_report`` per report would turn that into 1 + N.
        """
        if not report_ids:
            return []
        result = await session.execute(
            self.select()
            .where(models.EncounterMapCode.report_id.in_(tuple(report_ids)))
            .order_by(models.EncounterMapCode.map_index)
        )
        return result.scalars().all()


class EncounterGameRepository(BaseRepository[models.EncounterGame]):
    def __init__(self) -> None:
        super().__init__(models.EncounterGame)

    async def list_for_encounter(
        self, session: AsyncSession, encounter_id: int, *, include_cancelled: bool = False
    ) -> Sequence[models.EncounterGame]:
        query = self.select().where(models.EncounterGame.encounter_id == encounter_id)
        if not include_cancelled:
            query = query.where(models.EncounterGame.state != enums.EncounterGameState.CANCELLED)
        result = await session.execute(query.order_by(models.EncounterGame.position, models.EncounterGame.id))
        return result.scalars().all()

    async def get_for_update(self, session: AsyncSession, game_id: int) -> models.EncounterGame | None:
        result = await session.execute(
            self.select()
            .where(models.EncounterGame.id == game_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()


class EncounterMapReportRepository(BaseRepository[models.EncounterMapReport]):
    def __init__(self) -> None:
        super().__init__(models.EncounterMapReport)

    async def list_for_games(
        self, session: AsyncSession, game_ids: Sequence[int]
    ) -> Sequence[models.EncounterMapReport]:
        if not game_ids:
            return []
        result = await session.execute(self.select().where(models.EncounterMapReport.game_id.in_(tuple(game_ids))))
        return result.scalars().all()


class EncounterResultAuditRepository(BaseRepository[models.EncounterResultAudit]):
    def __init__(self) -> None:
        super().__init__(models.EncounterResultAudit)

    def add(self, session: AsyncSession, row: models.EncounterResultAudit) -> models.EncounterResultAudit:
        """Stage one journal row. No flush — rides the caller's transaction."""
        session.add(row)
        return row

    async def list_for_encounter(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        limit: int | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.EncounterResultAudit]:
        query = self._apply_options(
            self.select()
            .where(models.EncounterResultAudit.encounter_id == encounter_id)
            .order_by(
                models.EncounterResultAudit.created_at.desc(),
                models.EncounterResultAudit.id.desc(),
            ),
            options,
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.execute(query)
        return result.unique().scalars().all()


class EncounterReportFormRepository(BaseRepository[models.EncounterReportForm]):
    def __init__(self) -> None:
        super().__init__(models.EncounterReportForm)

    async def get_by_tournament(self, session: AsyncSession, tournament_id: int) -> models.EncounterReportForm | None:
        return await self.get_by(session, tournament_id=tournament_id)


class EncounterSavedViewRepository(BaseRepository[models.EncounterSavedView]):
    def __init__(self) -> None:
        super().__init__(models.EncounterSavedView)

    async def list_for_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> Sequence[models.EncounterSavedView]:
        result = await session.execute(
            self.select()
            .where(
                models.EncounterSavedView.workspace_id == workspace_id,
                models.EncounterSavedView.auth_user_id == auth_user_id,
            )
            .order_by(
                models.EncounterSavedView.sort_order.asc(),
                models.EncounterSavedView.created_at.asc(),
            )
        )
        return result.scalars().all()

    async def get_owned(
        self,
        session: AsyncSession,
        *,
        saved_view_id: int,
        workspace_id: int,
        auth_user_id: int,
    ) -> models.EncounterSavedView | None:
        return await self.get_by(
            session,
            id=saved_view_id,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
        )


class EncounterLinkRepository(BaseRepository[models.EncounterLink]):
    """``encounter_link`` — bracket wiring between a source and a target encounter."""

    def __init__(self) -> None:
        super().__init__(models.EncounterLink)

    async def list_by_source_ids(
        self, session: AsyncSession, source_encounter_ids: Sequence[int]
    ) -> Sequence[models.EncounterLink]:
        if not source_encounter_ids:
            return []
        result = await session.execute(
            self.select().where(models.EncounterLink.source_encounter_id.in_(tuple(source_encounter_ids)))
        )
        return result.scalars().all()


__all__ = (
    "EncounterCaptainReportRepository",
    "EncounterGameRepository",
    "EncounterLinkRepository",
    "EncounterMapCodeRepository",
    "EncounterMapReportRepository",
    "EncounterReportFormRepository",
    "EncounterResultAuditRepository",
    "EncounterSavedViewRepository",
)
