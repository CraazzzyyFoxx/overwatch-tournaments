"""rank_history — Overwatch competitive rank peaks and climbs.

Grain: user (user_id,).

Both nodes read ``overwatch_rank.rank_snapshot``, the append-only history of
observed rank changes. Those rows hang off ``players.user`` and carry no
workspace of their own, so every query here restricts to the users who hold a
roster spot in this workspace — the same ``Player -> WorkspaceMember ->
Tournament`` join ``get_all_eligible_users`` uses.

Distance is measured in *divisions*, not ``rank_value``: the mapped integer is
optional on a snapshot (and rebaseable, see ``owemerald01``), while the native
``division`` is always stored. ``tier`` only breaks ties for the peak evidence —
in Overwatch tier 1 is the top of a division and tier 5 the bottom
(``shared.domain.ow_ladder``), so a *lower* tier number is better.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import RankDivision
from shared.models.achievements.achievement import AchievementGrain
from src import models

from ..context import EvalContext
from . import ResultSet, register

OPERATORS = {
    "==": lambda col, val: col == val,
    "!=": lambda col, val: col != val,
    ">=": lambda col, val: col >= val,
    ">": lambda col, val: col > val,
    "<=": lambda col, val: col <= val,
    "<": lambda col, val: col < val,
}

#: Divisions bottom to top. The index is the "division step" both nodes count in.
DIVISION_ORDER: tuple[str, ...] = tuple(division.value for division in RankDivision)
DIVISION_INDEX: dict[str, int] = {value: index for index, value in enumerate(DIVISION_ORDER)}

#: Worse than any real tier, so a snapshot with no tier loses the peak tie-break.
_NO_TIER = 99

_SNAPSHOT_TABLES = ("overwatch_rank.rank_snapshot", "tournament.player")


def _workspace_user_ids(context: EvalContext) -> sa.Select:
    """Users on a roster in this workspace — mirrors ``get_all_eligible_users``."""
    return (
        sa.select(models.WorkspaceMember.player_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(models.Tournament.workspace_id == context.workspace_id)
    )


def _ranked_snapshots(
    context: EvalContext,
    params: dict[str, Any],
    *columns: Any,
) -> sa.Select:
    """Ranked snapshots of this workspace's users, narrowed by the optional filters."""
    query = sa.select(*columns).where(
        models.UserRankSnapshot.is_ranked.is_(True),
        models.UserRankSnapshot.division.is_not(None),
        models.UserRankSnapshot.user_id.in_(_workspace_user_ids(context)),
    )
    platform = params.get("platform")
    if platform is not None:
        query = query.where(models.UserRankSnapshot.platform == platform)
    role = params.get("role")
    if role is not None:
        query = query.where(models.UserRankSnapshot.role == role)
    season = params.get("season")
    if season is not None:
        query = query.where(models.UserRankSnapshot.season == season)
    return query


@register(
    "rank_peak",
    grain=AchievementGrain.user,
    description="Reached at least this Overwatch division",
    required=("min_division",),
    optional=("platform", "role", "season"),
    depends_on=_SNAPSHOT_TABLES,
)
async def execute_rank_peak(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    # An unknown division name is a rule error, not an empty result.
    floor = DIVISION_INDEX[RankDivision(params["min_division"]).value]

    query = _ranked_snapshots(
        context,
        params,
        models.UserRankSnapshot.user_id,
        models.UserRankSnapshot.division,
        models.UserRankSnapshot.tier,
        models.UserRankSnapshot.season,
        models.UserRankSnapshot.role,
    ).where(models.UserRankSnapshot.division.in_(DIVISION_ORDER[floor:]))

    result = await session.execute(query)
    # Keep the single best snapshot per user: highest division, then best tier.
    best: dict[int, tuple[tuple[int, int], Any]] = {}
    for row in result:
        rank = (DIVISION_INDEX[row.division], -(row.tier if row.tier is not None else _NO_TIER))
        current = best.get(row.user_id)
        if current is None or rank > current[0]:
            best[row.user_id] = (rank, row)

    keys: ResultSet = set()
    for user_id, (_, row) in best.items():
        key = (user_id,)
        keys.add(key)
        context.record_evidence(
            key,
            division=row.division,
            tier=int(row.tier) if row.tier is not None else None,
            season=int(row.season) if row.season is not None else None,
            role=row.role,
        )
    return keys


@register(
    "rank_climb",
    grain=AchievementGrain.user,
    description="Climbed this many divisions inside one season",
    required=("op", "value"),
    optional=("platform", "role", "season"),
    depends_on=_SNAPSHOT_TABLES,
)
async def execute_rank_climb(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    op_fn = OPERATORS[params["op"]]
    value = params["value"]

    query = _ranked_snapshots(
        context,
        params,
        models.UserRankSnapshot.user_id,
        models.UserRankSnapshot.division,
        models.UserRankSnapshot.season,
        models.UserRankSnapshot.role,
        models.UserRankSnapshot.platform,
        models.UserRankSnapshot.captured_at,
        models.UserRankSnapshot.id,
    ).order_by(
        models.UserRankSnapshot.user_id,
        models.UserRankSnapshot.season,
        models.UserRankSnapshot.role,
        models.UserRankSnapshot.platform,
        models.UserRankSnapshot.captured_at,
        models.UserRankSnapshot.id,
    )

    result = await session.execute(query)
    # One series = one (user, season, role, platform); a climb never spans two of them.
    series: dict[tuple[int, Any, str, str], list[Any]] = {}
    for row in result:
        if row.division not in DIVISION_INDEX:
            continue
        series.setdefault((row.user_id, row.season, row.role, row.platform), []).append(row)

    # Best climb per user: from each series' earliest snapshot up to the highest
    # one that came after it. A later drop is not a climb, and a peak that sits
    # before the earliest snapshot's trough cannot be one either.
    best: dict[int, tuple[int, str, str, Any]] = {}
    for (user_id, season, _role, _platform), snapshots in series.items():
        start = snapshots[0]
        start_index = DIVISION_INDEX[start.division]
        steps = 0
        peak = start
        for snapshot in snapshots[1:]:
            gain = DIVISION_INDEX[snapshot.division] - start_index
            if gain > steps:
                steps = gain
                peak = snapshot
        current = best.get(user_id)
        if current is None or steps > current[0]:
            best[user_id] = (steps, start.division, peak.division, season)

    keys: ResultSet = set()
    for user_id, (steps, from_division, to_division, season) in best.items():
        if not op_fn(steps, value):
            continue
        key = (user_id,)
        keys.add(key)
        context.record_evidence(
            key,
            from_division=from_division,
            to_division=to_division,
            steps=steps,
            season=int(season) if season is not None else None,
        )
    return keys
