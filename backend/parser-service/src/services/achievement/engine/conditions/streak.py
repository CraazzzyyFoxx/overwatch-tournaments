"""consecutive / stable_streak — cross-tournament sequence detection.

Grain: user (global).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.domain.achievement_stage_filters import standing_is_elimination

from ..context import EvalContext
from . import ResultSet, register


@register("consecutive")
async def execute_consecutive(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Consecutive tournaments with a condition met (e.g., wins). Grain: user.

    Uses the (seq - row_number()) grouping trick over a per-workspace
    chronological sequence to detect consecutive sequences.

    params:
        metric: "win" | "day_two" | "playoffs" — what constitutes a qualifying tournament
        min_streak: int — minimum consecutive count
        position_op: str (optional) — for "day_two", position threshold operator
        position_value: int (optional) — for "day_two", position threshold
    """
    metric = params["metric"]
    min_streak = params["min_streak"]

    # Per-workspace chronological sequence over regular (non-league) tournaments.
    #
    # Hidden tournaments are excluded because the scrim container is one
    # (docs/plans/2026-08-12-scrim-rooms.md §4.1) and this rank is an ordinal
    # timeline: a row that takes a rank in the middle of it splits any streak
    # that spans it. The container used to be harmless here only by accident --
    # it had no start date, so ``NULLS LAST`` parked it at the end -- and it now
    # carries its creation date, so the accident is gone and the filter is what
    # keeps the sequence honest. Hidden PREVIEW tournaments are excluded too:
    # they are real tournaments, but one that is still hidden has not been played
    # yet, so it cannot be a link in a consecutive-tournament streak either.
    tournament_seq = (
        sa.select(
            models.Tournament.id.label("tournament_id"),
            sa.func.dense_rank()
            .over(order_by=[models.Tournament.start_date.nulls_last(), models.Tournament.id])
            .label("seq"),
        ).where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Tournament.is_league.is_(False),
            models.Tournament.is_hidden.is_(False),
        )
    ).subquery("tournament_seq")

    if metric == "win":
        # Users who won (position == 1) in consecutive tournaments
        # Only bracket/final standings (buchholz IS NULL) and non-league tournaments
        qualifying = (
            (
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    tournament_seq.c.seq.label("seq"),
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
                .join(tournament_seq, tournament_seq.c.tournament_id == models.Tournament.id)
                .where(
                    models.Standing.overall_position == 1,
                    standing_is_elimination(standing=models.Standing, stage=models.Stage),
                    models.Tournament.is_league.is_(False),
                    models.Tournament.workspace_id == context.workspace_id,
                    models.Player.is_substitution.is_(False),
                )
            )
            .distinct()
            .subquery("qualifying")
        )

    elif metric == "day_two":
        position_op = params.get("position_op", "<")
        position_value = params.get("position_value", 7)
        from .stat_threshold import OPERATORS

        op_fn = OPERATORS[position_op]

        qualifying = (
            (
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    tournament_seq.c.seq.label("seq"),
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
                .join(tournament_seq, tournament_seq.c.tournament_id == models.Tournament.id)
                .where(
                    op_fn(models.Standing.overall_position, position_value),
                    standing_is_elimination(standing=models.Standing, stage=models.Stage),
                    models.Tournament.is_league.is_(False),
                    models.Tournament.workspace_id == context.workspace_id,
                    models.Player.is_substitution.is_(False),
                )
            )
            .distinct()
            .subquery("qualifying")
        )

    elif metric == "playoffs":
        # Tournaments where the player reached the playoff/elimination bracket
        # (group→playoff transition visible via the stage system).
        qualifying = (
            (
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    tournament_seq.c.seq.label("seq"),
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
                .join(tournament_seq, tournament_seq.c.tournament_id == models.Tournament.id)
                .where(
                    standing_is_elimination(standing=models.Standing, stage=models.Stage),
                    models.Tournament.is_league.is_(False),
                    models.Tournament.workspace_id == context.workspace_id,
                    models.Player.is_substitution.is_(False),
                )
            )
            .distinct()
            .subquery("qualifying")
        )
    else:
        return set()

    # Apply consecutive grouping trick: group_id = seq - row_number()
    rn = (
        sa.func.row_number()
        .over(
            partition_by=qualifying.c.user_id,
            order_by=qualifying.c.seq,
        )
        .label("rn")
    )

    with_rn = (
        sa.select(
            qualifying.c.user_id,
            qualifying.c.seq,
            (qualifying.c.seq - rn).label("grp"),
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
    any tracked field changes or when prev is NULL. Skipping a tournament does
    not break the streak — only chronological order matters.

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
        )
        .order_by(models.WorkspaceMember.player_id, models.Tournament.start_date.nulls_last(), models.Tournament.id)
    )

    result = await session.execute(query)
    rows = result.all()

    # Process in Python: detect stable streaks per user using segments
    from collections import defaultdict

    user_rows: dict[int, list] = defaultdict(list)
    for user_id, _tournament_id, source_version_id, role, rank in rows:
        division = context.resolve_division(rank, source_version_id=source_version_id)
        div_num = division.number if division else None
        user_rows[user_id].append(
            {
                "role": str(role) if role else None,
                "division": div_num,
            }
        )

    qualifying_users: ResultSet = set()
    for user_id, entries in user_rows.items():
        # Rows arrive chronologically ordered per user (SQL ORDER BY above).
        streak = 0
        prev: dict[str, Any] | None = None
        for entry in entries:
            if any(entry.get(field) is None for field in fields):
                streak = 0
                prev = None
                continue
            if prev is not None and all(entry.get(field) == prev.get(field) for field in fields):
                streak += 1
            else:
                streak = 1
            prev = entry
            if streak >= min_streak:
                qualifying_users.add((user_id,))
                break
    return qualifying_users
