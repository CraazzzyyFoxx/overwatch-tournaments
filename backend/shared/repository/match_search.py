"""``stats.match_search`` reads and writes. Repositories flush; the stats service owns retries and commit boundaries."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import MatchSearch, MatchSearchStatus

__all__ = ("MatchSearchRepository",)


class MatchSearchRepository:
    async def get(self, session: AsyncSession, search_id: int) -> MatchSearch | None:
        return await session.get(MatchSearch, search_id)

    async def get_for_update(self, session: AsyncSession, search_id: int) -> MatchSearch | None:
        return await session.get(MatchSearch, search_id, with_for_update=True, populate_existing=True)

    async def enroll(self, session: AsyncSession, rounds: sa.Select) -> None:
        """One row per ``(workspace_id, discipline, encounter_id, next_attempt_at)`` of ``rounds`` that has none yet."""
        await session.execute(
            pg_insert(MatchSearch)
            .from_select(["workspace_id", "discipline", "encounter_id", "next_attempt_at"], rounds)
            .on_conflict_do_nothing(constraint="uq_match_search_encounter")
        )

    async def restart(
        self, session: AsyncSession, *, workspace_id: int, discipline: str, encounter_id: int, now: datetime
    ) -> None:
        """The round's search, due at once with a fresh window: created if it has none, reset unless still looking."""
        fresh = {
            "status": MatchSearchStatus.PENDING,
            "attempts": 0,
            "next_attempt_at": now,
            "created_at": now,
            "last_error": None,
            "external_id": None,
        }
        insert = pg_insert(MatchSearch).values(
            workspace_id=workspace_id, discipline=discipline, encounter_id=encounter_id, **fresh
        )
        await session.execute(
            insert.on_conflict_do_update(
                constraint="uq_match_search_encounter",
                set_=fresh,
                where=MatchSearch.status != MatchSearchStatus.PENDING,
            )
        )

    async def due_ids(self, session: AsyncSession, *, now: datetime, limit: int, discipline: str) -> list[int]:
        return list(
            await session.scalars(
                sa.select(MatchSearch.id)
                .where(
                    MatchSearch.status == MatchSearchStatus.PENDING,
                    MatchSearch.next_attempt_at <= now,
                    MatchSearch.discipline == discipline,
                )
                .order_by(MatchSearch.next_attempt_at)
                .limit(limit)
            )
        )

    async def stop_pending(self, session: AsyncSession, encounter_id: int) -> None:
        """A round whose match id was filed another way stops looking."""
        await session.execute(
            sa.update(MatchSearch)
            .where(MatchSearch.encounter_id == encounter_id, MatchSearch.status == MatchSearchStatus.PENDING)
            .values(status=MatchSearchStatus.STOPPED)
        )
