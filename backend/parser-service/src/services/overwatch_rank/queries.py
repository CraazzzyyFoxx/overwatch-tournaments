"""Read/query layer for rank history (public endpoints)."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.domain.overwatch_rank import Granularity, fill_rank_series


def _point(snap: models.UserRankSnapshot, at: datetime) -> schemas.RankHistoryPoint:
    return schemas.RankHistoryPoint(
        captured_at=at,
        rank_value=snap.rank_value,
        division=snap.division,
        tier=snap.tier,
        is_ranked=snap.is_ranked,
        season=snap.season,
    )


def _apply_filters(
    query: sa.Select,
    *,
    user_id: int | None,
    social_account_id: int | None,
    platform: str | None,
    role: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> sa.Select:
    snap = models.UserRankSnapshot
    if user_id is not None:
        query = query.where(snap.user_id == user_id)
    if social_account_id is not None:
        query = query.where(snap.social_account_id == social_account_id)
    if platform is not None:
        query = query.where(snap.platform == platform)
    if role is not None:
        query = query.where(snap.role == role)
    if date_from is not None:
        query = query.where(snap.captured_at >= date_from)
    if date_to is not None:
        query = query.where(snap.captured_at <= date_to)
    return query


class RankQueries:
    """Analytical reads for the public rank-history endpoints.

    ``DISTINCT ON`` queries stay here rather than behind a CRUD
    repository, per ``backend/docs/repository-boundaries.md``.
    """

    async def get_rank_series(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        social_account_id: int | None = None,
        platform: str | None = None,
        role: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        granularity: Granularity = "raw",
    ) -> list[schemas.RankSeries]:
        """Return per-(battle_tag, role, platform) time series, filled between changes.

        ``rank_snapshot`` holds changes, not polls, so the rows inside the window
        alone draw nothing for a rank that held all along, and leave the line
        hanging at the last change. Each series is read together with the row it
        entered the window in, extended to the account's last successful poll --
        the last moment its rank is known to hold -- and expanded per
        ``granularity`` by :func:`fill_rank_series`. ``current`` stays the real
        latest row.
        """
        snap = models.UserRankSnapshot
        series_key = (snap.social_account_id, snap.role, snap.platform)
        scope = {"user_id": user_id, "social_account_id": social_account_id, "platform": platform, "role": role}

        window = _apply_filters(sa.select(snap), **scope, date_from=date_from, date_to=date_to)
        rows = list((await session.scalars(window.order_by(*series_key, snap.captured_at))).all())
        if date_from is not None:
            opening = (
                _apply_filters(sa.select(snap), **scope, date_from=None, date_to=None)
                .where(snap.captured_at < date_from)
                .distinct(*series_key)
                .order_by(*series_key, snap.captured_at.desc())
            )
            rows.extend((await session.scalars(opening)).all())
        if not rows:
            return []

        state = models.BattleTagRankState
        polled_at: dict[int, datetime | None] = dict(
            (
                await session.execute(
                    sa.select(state.social_account_id, state.last_success_at).where(
                        state.social_account_id.in_({row.social_account_id for row in rows})
                    )
                )
            ).all()
        )

        grouped: dict[tuple[int, str, str], list[models.UserRankSnapshot]] = {}
        for row in rows:
            grouped.setdefault((row.social_account_id, row.role, row.platform), []).append(row)

        series: list[schemas.RankSeries] = []
        for (bt_id, role_key, platform_key), snaps in sorted(grouped.items()):
            snaps.sort(key=lambda s: s.captured_at)
            last = snaps[-1]
            end = max(last.captured_at, polled_at.get(bt_id) or last.captured_at)
            if date_to is not None:
                end = min(end, date_to)
            filled = fill_rank_series([s.captured_at for s in snaps], start=date_from, end=end, granularity=granularity)
            if not filled:
                continue
            ranked_values = [s.rank_value for s in snaps if s.rank_value is not None]
            series.append(
                schemas.RankSeries(
                    social_account_id=bt_id,
                    battle_tag=last.battle_tag,
                    role=role_key,
                    platform=platform_key,
                    points=[_point(snaps[i], at) for at, i in filled],
                    current=_point(last, last.captured_at),
                    peak_rank_value=max(ranked_values, default=None),
                    latest_captured_at=last.captured_at,
                )
            )
        return series

    async def get_current_ranks(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        social_account_id: int | None = None,
        platform: str | None = None,
    ) -> list[schemas.CurrentRank]:
        """Latest snapshot per (battle_tag, role, platform)."""
        snap = models.UserRankSnapshot
        query = _apply_filters(
            sa.select(snap),
            user_id=user_id,
            social_account_id=social_account_id,
            platform=platform,
            role=None,
            date_from=None,
            date_to=None,
        )
        query = query.distinct(snap.social_account_id, snap.role, snap.platform).order_by(
            snap.social_account_id, snap.role, snap.platform, snap.captured_at.desc()
        )
        rows = (await session.scalars(query)).all()
        return [
            schemas.CurrentRank(
                social_account_id=s.social_account_id,
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


rank_queries = RankQueries()

# Module-attribute compatibility seam: rpc/rank.py and tests call these as bare
# ``queries.<name>(...)`` — see service.py's matching note.
get_rank_series = rank_queries.get_rank_series
get_current_ranks = rank_queries.get_current_ranks
