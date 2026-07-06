"""div_span — total division climb across all tournaments.

Grain: user (global).

Ports the legacy ``my-drill-will-pierce-the-sky`` query: within a single role,
``max(division) - min(division)`` across the user's tournaments must meet a
threshold. Division resolution happens in Python (needs the grid/normalizer).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("div_span")
async def execute_div_span(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """max(div) - min(div) per role across tournaments meets threshold. Grain: user.

    params:
        op: comparison operator (e.g. ">=")
        value: minimum division span
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
        )
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    result = await session.execute(query)

    # Division numbers per (user, role).
    spans: dict[tuple[int, str], list[int]] = defaultdict(list)
    for user_id, role, rank, source_version_id in result:
        division = context.resolve_division(rank, source_version_id=source_version_id)
        if division is not None:
            spans[(user_id, str(role))].append(division.number)

    qualifying: ResultSet = set()
    for (user_id, _role), numbers in spans.items():
        if len(numbers) >= 2 and op_fn(max(numbers) - min(numbers), value):
            qualifying.add((user_id,))
    return qualifying
