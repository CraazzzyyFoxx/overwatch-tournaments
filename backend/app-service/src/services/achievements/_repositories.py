"""SQL helpers for achievement flows.

These were previously in `services/_internal/{tournament,encounter}/service.py`.
"""

from __future__ import annotations

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src import models


async def get_tournaments_bulk(
    session: AsyncSession, tournament_ids: typing.Sequence[int]
) -> typing.Sequence[models.Tournament]:
    if not tournament_ids:
        return []
    query = sa.select(models.Tournament).where(models.Tournament.id.in_(tournament_ids))
    result = await session.execute(query)
    return list(result.unique().scalars().all())


async def get_matches_bulk(
    session: AsyncSession, match_ids: typing.Sequence[int]
) -> typing.Sequence[models.Match]:
    if not match_ids:
        return []
    query = (
        sa.select(models.Match)
        .options(
            joinedload(models.Match.home_team),
            joinedload(models.Match.away_team),
        )
        .where(models.Match.id.in_(match_ids))
    )
    result = await session.execute(query)
    return list(result.unique().scalars().all())
