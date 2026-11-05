"""Organizer-dashboard trends: the last 10 finished, public, non-league tournaments.

One round-trip: a CTE picks the tournaments, two grouped subqueries (roster,
encounters) aggregate over them and are LEFT-joined back, so a tournament with
no players or encounters still yields a zero point.

Only duels (``slot_count == 2``) count toward log coverage: a lobby never
produces a match log. The confirmation median ignores rows missing either
timestamp or confirmed before the match ended (manual corrections); a
tournament with none of those left gets ``None``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.chrono import tournament_chrono_key
from src.schemas.dashboard_trends import DashboardTrendPoint, DashboardTrends

__all__ = ("DashboardTrendsService", "trends")


class DashboardTrendsService:
    async def get_trends(self, session: AsyncSession, *, workspace_id: int, discipline: str | None) -> DashboardTrends:
        tournament = models.Tournament
        start, end, _ = tournament_chrono_key()
        picked_q = sa.select(
            tournament.id,
            tournament.name,
            tournament.discipline,
            tournament.start_date,
            start.label("chrono_start"),
            end.label("chrono_end"),
        ).where(
            tournament.workspace_id == workspace_id,
            tournament.status.in_((enums.TournamentStatus.COMPLETED, enums.TournamentStatus.ARCHIVED)),
            tournament.is_hidden.is_(False),
            tournament.is_league.is_(False),
        )
        if discipline is not None:
            picked_q = picked_q.where(tournament.discipline == discipline)
        picked = picked_q.order_by(*(c.desc() for c in tournament_chrono_key())).limit(10).cte("trend_tournaments")
        picked_ids = sa.select(picked.c.id)

        player = models.Player
        roster = (
            sa.select(
                player.tournament_id,
                sa.func.count(player.id).label("participants"),
                sa.func.count(player.id).filter(player.is_newcomer.is_(True)).label("newcomers"),
            )
            .where(player.tournament_id.in_(picked_ids))
            .group_by(player.tournament_id)
            .subquery("trend_roster")
        )

        encounter = models.Encounter
        duel = encounter.slot_count == 2
        # NULL unless both timestamps are set and ordered; percentile_cont skips NULLs
        # and returns NULL when nothing is left.
        confirm_seconds = sa.case(
            (
                encounter.confirmed_at >= encounter.ended_at,
                sa.cast(sa.extract("epoch", encounter.confirmed_at - encounter.ended_at), sa.Float),
            )
        )
        play = (
            sa.select(
                encounter.tournament_id,
                sa.func.count(encounter.id).filter(duel).label("duels"),
                sa.func.count(encounter.id).filter(duel, encounter.has_logs.is_(True)).label("duels_with_logs"),
                sa.func.percentile_cont(0.5).within_group(confirm_seconds).label("median_confirm_seconds"),
            )
            .where(encounter.tournament_id.in_(picked_ids))
            .group_by(encounter.tournament_id)
            .subquery("trend_encounters")
        )

        rows = await session.execute(
            sa.select(
                picked.c.id.label("tournament_id"),
                picked.c.name.label("tournament_name"),
                picked.c.discipline,
                picked.c.start_date,
                sa.func.coalesce(roster.c.participants, 0).label("participants"),
                sa.func.coalesce(roster.c.newcomers, 0).label("newcomers"),
                sa.func.coalesce(play.c.duels, 0).label("duel_encounters_total"),
                sa.func.coalesce(play.c.duels_with_logs, 0).label("duel_encounters_with_logs"),
                play.c.median_confirm_seconds,
            )
            .select_from(picked)
            .outerjoin(roster, roster.c.tournament_id == picked.c.id)
            .outerjoin(play, play.c.tournament_id == picked.c.id)
            # Oldest first: the exact reverse of the picking order.
            .order_by(picked.c.chrono_start, picked.c.chrono_end, picked.c.id)
        )
        return DashboardTrends(points=[DashboardTrendPoint(**row._mapping) for row in rows])


trends = DashboardTrendsService()
