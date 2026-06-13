"""reached_playoffs — team advanced from groups into the playoff bracket.

Grain: user_tournament (scope="tournament") or user (scope="global").

"Reached playoffs" means the team has an elimination/bracket standing
(``standing_is_elimination``), i.e. the group→playoff transition is visible in
the stage system. With scope="global" the leaf counts how many tournaments the
user reached the playoffs in (e.g. ``op="==", value=0`` for "never").
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import standing_is_elimination
from .stat_threshold import OPERATORS


def _base_query() -> sa.Select[tuple[int, int]]:
    return (
        sa.select(
            models.Player.user_id,
            models.Standing.tournament_id,
        )
        .select_from(models.Standing)
        .join(models.Tournament, models.Tournament.id == models.Standing.tournament_id)
        .outerjoin(models.Stage, models.Stage.id == models.Standing.stage_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == models.Standing.team_id,
                models.Player.tournament_id == models.Standing.tournament_id,
            ),
        )
    )


@register("reached_playoffs")
async def execute_reached_playoffs(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Reached the playoff bracket. Grain: user_tournament or user.

    params:
        scope: "tournament" (default) → user_tournament grain
               "global" → user grain, count-based
        op: (global only) comparison operator (default ">=")
        value: (global only) playoff-appearance count threshold (default 1)
    """
    scope = params.get("scope", "tournament")

    where_clauses = [
        standing_is_elimination(standing=models.Standing, stage=models.Stage),
        models.Tournament.workspace_id == context.workspace_id,
        models.Player.is_substitution.is_(False),
    ]

    if scope == "global":
        op = params.get("op", ">=")
        value = params.get("value", 1)
        op_fn = OPERATORS[op]

        counts_query = (
            _base_query()
            .with_only_columns(
                models.Player.user_id,
                sa.func.count(models.Standing.tournament_id.distinct()).label("cnt"),
            )
            .where(*where_clauses)
            .group_by(models.Player.user_id)
        )
        result = await session.execute(counts_query)
        counts = {row[0]: row[1] for row in result}

        # Count==0 / <N cases need the complement against all eligible users,
        # since a grouped count only sees users with at least one appearance.
        from . import get_all_eligible_users

        eligible = await get_all_eligible_users(session, context)
        return {(user_id,) for (user_id,) in eligible if op_fn(counts.get(user_id, 0), value)}

    query = _base_query().where(*where_clauses)
    if context.tournament:
        query = query.where(models.Standing.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
