"""Read/query layer for rank history (public endpoints)."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas

Granularity = Literal["raw", "daily"]


def _apply_filters(
    query: sa.Select,
    *,
    user_id: int | None,
    battle_tag_id: int | None,
    platform: str | None,
    role: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> sa.Select:
    snap = models.UserRankSnapshot
    if user_id is not None:
        query = query.where(snap.user_id == user_id)
    if battle_tag_id is not None:
        query = query.where(snap.battle_tag_id == battle_tag_id)
    if platform is not None:
        query = query.where(snap.platform == platform)
    if role is not None:
        query = query.where(snap.role == role)
    if date_from is not None:
        query = query.where(snap.captured_at >= date_from)
    if date_to is not None:
        query = query.where(snap.captured_at <= date_to)
    return query


async def get_rank_series(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    battle_tag_id: int | None = None,
    platform: str | None = None,
    role: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    granularity: Granularity = "raw",
) -> list[schemas.RankSeries]:
    """Return per-(battle_tag, role, platform) time series.

    ``granularity="daily"`` keeps only the last snapshot per calendar day per
    series (Postgres ``DISTINCT ON``) so charts stay light over long windows.
    """
    snap = models.UserRankSnapshot
    query = _apply_filters(
        sa.select(snap),
        user_id=user_id,
        battle_tag_id=battle_tag_id,
        platform=platform,
        role=role,
        date_from=date_from,
        date_to=date_to,
    )

    if granularity == "daily":
        day = sa.func.date_trunc("day", snap.captured_at)
        query = query.distinct(snap.battle_tag_id, snap.role, snap.platform, day).order_by(
            snap.battle_tag_id, snap.role, snap.platform, day, snap.captured_at.desc()
        )
    else:
        query = query.order_by(snap.battle_tag_id, snap.role, snap.platform, snap.captured_at)

    rows = (await session.scalars(query)).all()

    grouped: OrderedDict[tuple[int, str, str], list[models.UserRankSnapshot]] = OrderedDict()
    for row in rows:
        grouped.setdefault((row.battle_tag_id, row.role, row.platform), []).append(row)

    series: list[schemas.RankSeries] = []
    for (bt_id, role_key, platform_key), snaps in grouped.items():
        snaps.sort(key=lambda s: s.captured_at)
        points = [
            schemas.RankHistoryPoint(
                captured_at=s.captured_at,
                rank_value=s.rank_value,
                division=s.division,
                tier=s.tier,
                is_ranked=s.is_ranked,
                season=s.season,
            )
            for s in snaps
        ]
        ranked_values = [s.rank_value for s in snaps if s.rank_value is not None]
        series.append(
            schemas.RankSeries(
                battle_tag_id=bt_id,
                battle_tag=snaps[-1].battle_tag,
                role=role_key,
                platform=platform_key,
                points=points,
                current=points[-1] if points else None,
                peak_rank_value=max(ranked_values) if ranked_values else None,
                latest_captured_at=snaps[-1].captured_at if snaps else None,
            )
        )
    return series


async def get_current_ranks(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    battle_tag_id: int | None = None,
    platform: str | None = None,
) -> list[schemas.CurrentRank]:
    """Latest snapshot per (battle_tag, role, platform)."""
    snap = models.UserRankSnapshot
    query = _apply_filters(
        sa.select(snap),
        user_id=user_id,
        battle_tag_id=battle_tag_id,
        platform=platform,
        role=None,
        date_from=None,
        date_to=None,
    )
    query = query.distinct(snap.battle_tag_id, snap.role, snap.platform).order_by(
        snap.battle_tag_id, snap.role, snap.platform, snap.captured_at.desc()
    )
    rows = (await session.scalars(query)).all()
    return [
        schemas.CurrentRank(
            battle_tag_id=s.battle_tag_id,
            battle_tag=s.battle_tag,
            role=s.role,
            platform=s.platform,
            rank_value=s.rank_value,
            division=s.division,
            tier=s.tier,
            is_ranked=s.is_ranked,
            season=s.season,
            captured_at=s.captured_at,
        )
        for s in rows
    ]
