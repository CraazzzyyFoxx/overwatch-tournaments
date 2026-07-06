"""consecutive / stable_streak — cross-tournament sequence detection.

Grain: user (global).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import standing_is_elimination


@register("consecutive")
async def execute_consecutive(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Consecutive tournaments with a condition met (e.g., wins). Grain: user.

    Uses the (tournament_number - row_number()) grouping trick to detect
    consecutive sequences.

    params:
        metric: "win" | "day_two" | "playoffs" — what constitutes a qualifying tournament
        min_streak: int — minimum consecutive count
        position_op: str (optional) — for "day_two", position threshold operator
        position_value: int (optional) — for "day_two", position threshold
    """
    metric = params["metric"]
    min_streak = params["min_streak"]

    if metric == "win":
        # Users who won (position == 1) in consecutive tournaments
        # Only bracket/final standings (buchholz IS NULL) and non-league tournaments
        qualifying = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Tournament.number.label("t_num"),
            )
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == models.Team.id,
                    models.Standing.tournament_id == models.Player.tournament_id,
                ),
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .outerjoin(models.Stage, models.Stage.id == models.Standing.stage_id)
            .where(
                models.Standing.overall_position == 1,
                standing_is_elimination(standing=models.Standing, stage=models.Stage),
                models.Tournament.is_league.is_(False),
                models.Tournament.workspace_id == context.workspace_id,
                models.Player.is_substitution.is_(False),
                models.Tournament.number.isnot(None),
            )
        ).subquery("qualifying")

    elif metric == "day_two":
        position_op = params.get("position_op", "<")
        position_value = params.get("position_value", 7)
        from .stat_threshold import OPERATORS

        op_fn = OPERATORS[position_op]

        qualifying = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Tournament.number.label("t_num"),
            )
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == models.Team.id,
                    models.Standing.tournament_id == models.Player.tournament_id,
                ),
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .outerjoin(models.Stage, models.Stage.id == models.Standing.stage_id)
            .where(
                op_fn(models.Standing.overall_position, position_value),
                standing_is_elimination(standing=models.Standing, stage=models.Stage),
                models.Tournament.is_league.is_(False),
                models.Tournament.workspace_id == context.workspace_id,
                models.Player.is_substitution.is_(False),
                models.Tournament.number.isnot(None),
            )
        ).subquery("qualifying")

    elif metric == "playoffs":
        # Tournaments where the player reached the playoff/elimination bracket
        # (group→playoff transition visible via the stage system).
        qualifying = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Tournament.number.label("t_num"),
            )
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == models.Team.id,
                    models.Standing.tournament_id == models.Player.tournament_id,
                ),
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .outerjoin(models.Stage, models.Stage.id == models.Standing.stage_id)
            .where(
                standing_is_elimination(standing=models.Standing, stage=models.Stage),
                models.Tournament.is_league.is_(False),
                models.Tournament.workspace_id == context.workspace_id,
                models.Player.is_substitution.is_(False),
                models.Tournament.number.isnot(None),
            )
        ).subquery("qualifying")
    else:
        return set()

    # Apply consecutive grouping trick: group_id = t_num - row_number()
    rn = (
        sa.func.row_number()
        .over(
            partition_by=qualifying.c.user_id,
            order_by=qualifying.c.t_num,
        )
        .label("rn")
    )

    with_rn = (
        sa.select(
            qualifying.c.user_id,
            qualifying.c.t_num,
            (qualifying.c.t_num - rn).label("grp"),
        )
    ).subquery("with_rn")

    # Count consecutive sequences
    streaks = (
        sa.select(
            with_rn.c.user_id,
            sa.func.count().label("streak_len"),
        )
        .group_by(with_rn.c.user_id, with_rn.c.grp)
        .having(sa.func.count() >= min_streak)
    ).subquery("streaks")

    query = sa.select(streaks.c.user_id.distinct())
    result = await session.execute(query)
    return {(row[0],) for row in result}


@register("stable_streak")
async def execute_stable_streak(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """N+ consecutive participations at same values for given fields. Grain: user.

    Uses segment-based detection (like the legacy code): a new segment starts when
    any tracked field changes or when prev is NULL. Consecutive tournament numbers
    are NOT required — skipping a tournament does not break the streak.

    params:
        fields: list of field names (e.g., ["role", "division"])
        min_streak: int
    """
    fields = params["fields"]
    min_streak = params["min_streak"]

    if context.grid is None and context.normalizer is None:
        return set()

    # Build player data with tournament ordering (exclude leagues)
    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Player.tournament_id,
            models.Tournament.number.label("t_num"),
            models.Tournament.division_grid_version_id,
            models.Player.role,
            models.Player.rank,
        )
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Tournament.is_league.is_(False),
            models.Player.is_substitution.is_(False),
            models.Tournament.number.isnot(None),
        )
        .order_by(models.WorkspaceMember.player_id, models.Tournament.number)
    )

    result = await session.execute(query)
    rows = result.all()

    # Process in Python: detect stable streaks per user using segments
    from collections import defaultdict

    user_rows: dict[int, list] = defaultdict(list)
    for user_id, _tournament_id, t_num, source_version_id, role, rank in rows:
        division = context.resolve_division(rank, source_version_id=source_version_id)
        div_num = division.number if division else None
        user_rows[user_id].append(
            {
                "t_num": t_num,
                "role": str(role) if role else None,
                "division": div_num,
            }
        )

    qualifying_users: ResultSet = set()
    for user_id, entries in user_rows.items():
        entries.sort(key=lambda x: x["t_num"])
        streak = 1
        for i in range(1, len(entries)):
            # Segment breaks when any tracked field changes (gaps are OK)
            same = all(entries[i].get(f) == entries[i - 1].get(f) for f in fields)
            if same:
                streak += 1
                if streak >= min_streak:
                    qualifying_users.add((user_id,))
                    break
            else:
                streak = 1

    return qualifying_users
