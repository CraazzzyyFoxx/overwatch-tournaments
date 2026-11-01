"""Resolve the owning ``tournament_id`` for entity-level reads so the shared
hidden-tournament guard can gate them. Each resolver raises 404 when the entity
is absent (indistinguishable from a hidden tournament to outsiders).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException


class VisibilityResolverService:
    """Scalar ``tournament_id`` lookups.

    Each resolver reads exactly one column: loading the whole ORM row (and
    populating the identity map with it) would cost more than the guard it feeds.
    """

    async def _scalar_or_404(self, session: AsyncSession, stmt: sa.Select, detail: str) -> int:
        val = await session.scalar(stmt)
        if val is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return int(val)

    async def tournament_id_for_encounter(self, session: AsyncSession, encounter_id: int) -> int:
        return await self._scalar_or_404(
            session,
            sa.select(models.Encounter.tournament_id).where(models.Encounter.id == encounter_id),
            "Encounter not found",
        )

    async def tournament_id_for_team(self, session: AsyncSession, team_id: int) -> int:
        return await self._scalar_or_404(
            session,
            sa.select(models.Team.tournament_id).where(models.Team.id == team_id),
            "Team not found",
        )

    def _match_owner_stmt(self, match_id: int) -> sa.Select:
        return (
            sa.select(models.Encounter.tournament_id)
            .join(
                models.StatsMatch,
                sa.and_(
                    models.StatsMatch.encounter_id == models.Encounter.id,
                    models.StatsMatch.workspace_id == models.Encounter.workspace_id,
                    models.StatsMatch.discipline == models.Encounter.discipline,
                ),
            )
            .where(models.StatsMatch.id == match_id)
        )

    async def tournament_id_for_match(self, session: AsyncSession, match_id: int) -> int:
        return await self._scalar_or_404(session, self._match_owner_stmt(match_id), "Match not found")

    async def owner_tournament_id_for_match(self, session: AsyncSession, match_id: int) -> int | None:
        """The match's tournament, or ``None`` for a mix-owned match (public, D6); 404 when the match is absent."""
        row = (await session.execute(self._match_owner_stmt(match_id))).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
        return row[0]


visibility_resolvers_service = VisibilityResolverService()
