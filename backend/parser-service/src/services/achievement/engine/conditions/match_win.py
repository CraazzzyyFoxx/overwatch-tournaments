"""match_win — user's team won the match.

Uses Player → Team → Match join (not MatchStatistics) so results don't depend
on any particular stat row existing.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register


@register("match_win")
async def execute(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    # Winning team_id per match
    winning_team = sa.case(
        (models.Match.home_score > models.Match.away_score, models.Match.home_team_id),
        else_=models.Match.away_team_id,
    )

    query = (
        sa.select(
            models.Player.user_id,
            models.Encounter.tournament_id,
            models.Match.id.label("match_id"),
        )
        .select_from(models.Match)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == winning_team,
                models.Player.tournament_id == models.Encounter.tournament_id,
            ),
        )
        .where(
            models.Match.home_score != models.Match.away_score,
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1], row[2]) for row in result}
