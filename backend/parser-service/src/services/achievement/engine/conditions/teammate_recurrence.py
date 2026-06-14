"""teammate_recurrence — shared a team with the same player N+ times.

Grain: user (global).

Ports the legacy ``lfs-4500`` achievement: any pair of users who were on the
same team in ``value`` or more distinct teams both qualify.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("teammate_recurrence")
async def execute_teammate_recurrence(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Both members of a recurring teammate pair qualify. Grain: user.

    params:
        op: comparison operator (default ">=")
        value: minimum number of shared teams (default 3)
    """
    op = params.get("op", ">=")
    value = params.get("value", 3)
    op_fn = OPERATORS[op]

    p1 = sa.orm.aliased(models.Player, name="p1")
    p2 = sa.orm.aliased(models.Player, name="p2")
    tournament = sa.orm.aliased(models.Tournament, name="trec")

    shared_teams = sa.func.count(p1.team_id.distinct())

    query = (
        sa.select(
            sa.func.least(p1.user_id, p2.user_id).label("u1"),
            sa.func.greatest(p1.user_id, p2.user_id).label("u2"),
        )
        .select_from(p1)
        .join(p2, p1.team_id == p2.team_id)
        .join(tournament, tournament.id == p1.tournament_id)
        .where(
            p1.user_id != p2.user_id,
            tournament.workspace_id == context.workspace_id,
        )
        .group_by(
            sa.func.least(p1.user_id, p2.user_id),
            sa.func.greatest(p1.user_id, p2.user_id),
        )
        .having(op_fn(shared_teams, value))
    )

    result = await session.execute(query)
    users: ResultSet = set()
    for u1, u2 in result:
        users.add((u1,))
        users.add((u2,))
    return users
