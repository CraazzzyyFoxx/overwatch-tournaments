"""match_mvp_check — checks how many team players are in top-N by stat per match.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register("match_mvp_check")
async def execute(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Check how many of the team's players are in top-N by stat in a match.

    Grain: user_match. Awards all players on qualifying teams.

    params:
        stat: LogStatsName (e.g. "Performance", "Eliminations")
        top_n: int (default 3) — top N players in the match
        op: operator for team_count_in_top comparison (default "==")
        value: int (default 0) — how many team players in top N
            e.g. op="==" value=0 → none of team's players in top N
            e.g. op=">=" value=2 → at least 2 team players in top N

    Example: team won but 0 players in top-3 MVP:
        AND: [match_win, match_mvp_check(stat=Performance, top_n=3, op===, value=0)]
    """
    from . import resolve_stat_name
    stat = resolve_stat_name(params.get("stat", "performance"))
    top_n = params.get("top_n", 3)
    op = params.get("op", "==")
    value = params.get("value", 0)
    sort_order = params.get("sort_order", "auto")  # "asc", "desc", or "auto"
    op_fn = OPERATORS[op]

    # Step 1: Per-match per-player aggregated stat
    player_stats = (
        sa.select(
            models.MatchStatistics.match_id,
            models.MatchStatistics.user_id,
            models.MatchStatistics.team_id,
            sa.func.sum(models.MatchStatistics.value).label("stat_value"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.MatchStatistics.name == stat,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.Tournament.workspace_id == context.workspace_id,
        )
        .group_by(
            models.MatchStatistics.match_id,
            models.MatchStatistics.user_id,
            models.MatchStatistics.team_id,
        )
    )

    if context.tournament:
        player_stats = player_stats.where(models.Encounter.tournament_id == context.tournament.id)

    ps = player_stats.subquery("ps")

    # Step 2: Rank players within each match by stat_value.
    # "auto" detects sort direction from enum config (Performance=asc, most others=desc).
    if sort_order == "auto":
        from shared.core.enums import LogStatsName as _LSN, is_ascending_stat
        try:
            _use_asc = is_ascending_stat(_LSN[stat])
        except KeyError:
            _use_asc = False
    else:
        _use_asc = sort_order == "asc"

    rank_order = ps.c.stat_value.asc() if _use_asc else ps.c.stat_value.desc()

    ranked = (
        sa.select(
            ps.c.match_id,
            ps.c.user_id,
            ps.c.team_id,
            sa.func.row_number().over(
                partition_by=ps.c.match_id,
                order_by=rank_order,
            ).label("rank"),
        )
    ).subquery("ranked")

    # Step 3: For each (match, team), count how many players are in top_n
    team_top_count = (
        sa.select(
            ranked.c.match_id,
            ranked.c.team_id,
            sa.func.count().label("in_top"),
        )
        .where(ranked.c.rank <= top_n)
        .group_by(ranked.c.match_id, ranked.c.team_id)
    ).subquery("team_top")

    # Step 4: Also need teams that have 0 players in top — they won't appear in team_top.
    # Get all (match, team) combinations from the stats
    all_teams = (
        sa.select(
            ps.c.match_id,
            ps.c.team_id,
        )
        .group_by(ps.c.match_id, ps.c.team_id)
    ).subquery("all_teams")

    # Left join to get in_top count (0 if not in team_top)
    teams_with_count = (
        sa.select(
            all_teams.c.match_id,
            all_teams.c.team_id,
            sa.func.coalesce(team_top_count.c.in_top, 0).label("in_top"),
        )
        .outerjoin(
            team_top_count,
            sa.and_(
                all_teams.c.match_id == team_top_count.c.match_id,
                all_teams.c.team_id == team_top_count.c.team_id,
            ),
        )
        .where(op_fn(sa.func.coalesce(team_top_count.c.in_top, 0), value))
    ).subquery("filtered_teams")

    # Step 5: Get tournament_id and all players on qualifying teams
    query = (
        sa.select(
            models.Player.user_id,
            models.Encounter.tournament_id,
            teams_with_count.c.match_id,
        )
        .join(
            teams_with_count,
            models.Player.team_id == teams_with_count.c.team_id,
        )
        .join(
            models.Match,
            models.Match.id == teams_with_count.c.match_id,
        )
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(
            models.Player.is_substitution.is_(False),
            sa.or_(
                models.Match.home_team_id == teams_with_count.c.team_id,
                models.Match.away_team_id == teams_with_count.c.team_id,
            ),
        )
    )

    result = await session.execute(query)
    return {(row[0], row[1], row[2]) for row in result}
