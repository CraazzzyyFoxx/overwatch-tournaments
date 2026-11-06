"""div_span — division climb across tournaments in one role.

Grain: user (global).

Backs ``my-drill-will-pierce-the-sky``: within a single role,
the last tournament's division minus the first (chronological) must meet a
threshold. A drop does not count as a climb. Division resolution happens in
Python (needs the grid/normalizer).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.chrono import tournament_chrono_key
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain

from . import ResultSet, always, register
from .stat_threshold import OPERATORS


@register(
    "div_span",
    grain=AchievementGrain.user,
    description="Division climbed between first and last tournament",
    required=("op", "value"),
    requires_normalized_divisions=always,
    depends_on=("analytics.player_shift", "tournament.player"),
)
async def execute_div_span(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Chronological last−first division per role meets threshold. Grain: user.

    params:
        op: comparison operator (e.g. ">=")
        value: minimum division climb
    """
    op = params["op"]
    value = params["value"]

    if context.grid is None and context.normalizer is None:
        return set()

    op_fn = OPERATORS[op]

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Player.role,
            models.Player.rank,
            models.Tournament.division_grid_version_id,
            *tournament_chrono_key(),
        )
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
            models.Player.is_substitution.is_(False),
        )
    )

    result = await session.execute(query)

    series: dict[tuple[int, str], list[tuple]] = defaultdict(list)
    for user_id, role, rank, source_version_id, start, end, tournament_id in result:
        division = context.resolve_division(rank, source_version_id=source_version_id)
        if division is not None:
            series[(user_id, str(role))].append((start, end, tournament_id, division.number))

    qualifying: ResultSet = set()
    for (user_id, _role), points in series.items():
        if len(points) < 2:
            continue
        points.sort()
        climb = points[-1][3] - points[0][3]
        if op_fn(climb, value):
            qualifying.add((user_id,))
    return qualifying
