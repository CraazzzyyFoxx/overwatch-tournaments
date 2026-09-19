"""map_coverage / map_winrate — which maps and gamemodes a player actually played.

Participation is telemetry, not a roster: a player counts for a map when they
have ``MatchStatistics`` rows on it, so substitutes who never played are absent
by construction and no ``is_substitution`` filter is needed.

Grains: ``map_coverage`` is user (user_tournament with ``scope="tournament"``),
``map_winrate`` is user.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

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

#: The player's side (``MatchStatistics.team_id``) is the map winner. A map that
#: ended level counts as neither side's win.
_PLAYER_WON_MAP = sa.or_(
    sa.and_(
        models.MatchStatistics.team_id == models.Match.home_team_id,
        models.Match.home_score > models.Match.away_score,
    ),
    sa.and_(
        models.MatchStatistics.team_id == models.Match.away_team_id,
        models.Match.away_score > models.Match.home_score,
    ),
)


@register(
    "map_coverage",
    grain=AchievementGrain.user,
    description="Distinct maps or gamemodes the player has played or won on",
    required=("field", "op", "value"),
    optional=("gamemode", "outcome", "scope"),
    depends_on=("matches.match", "matches.statistics", "tournament.encounter"),
    grain_for=lambda params: (
        AchievementGrain.user_tournament if params.get("scope") == "tournament" else AchievementGrain.user
    ),
)
async def execute_map_coverage(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    field = params["field"]
    op = params["op"]
    value = params["value"]
    outcome = params.get("outcome", "played")
    gamemode = params.get("gamemode")
    scope = params.get("scope", "global")

    if field == "map":
        distinct_col = models.Match.map_id
    elif field == "gamemode":
        distinct_col = models.Map.gamemode_id
    else:
        raise ValueError(f"Unsupported map_coverage field: {field!r}")

    if outcome not in ("played", "won"):
        raise ValueError(f"Unsupported map_coverage outcome: {outcome!r}")

    op_fn = OPERATORS[op]
    count_expr = sa.func.count(sa.distinct(distinct_col))

    group_cols: list[Any] = [models.MatchStatistics.user_id]
    if scope == "tournament":
        group_cols.append(models.Encounter.tournament_id)

    query = (
        sa.select(*group_cols, count_expr.label("measured"))
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Map, models.Map.id == models.Match.map_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(models.Tournament.workspace_id == context.workspace_id)
        .group_by(*group_cols)
        .having(op_fn(count_expr, value))
    )

    if outcome == "won":
        query = query.where(_PLAYER_WON_MAP)

    if gamemode:
        query = query.join(models.Gamemode, models.Gamemode.id == models.Map.gamemode_id).where(
            models.Gamemode.name == gamemode
        )

    if context.tournament and scope == "tournament":
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    width = len(group_cols)
    for row in result:
        key = tuple(row[:width])
        keys.add(key)
        context.record_evidence(key, distinct=int(row[width]), field=field, outcome=outcome)
    return keys


@register(
    "map_winrate",
    grain=AchievementGrain.user,
    description="Career winrate on a single map over a minimum sample",
    required=("op", "value"),
    optional=("map_name", "min_matches"),
    depends_on=("matches.match", "matches.statistics", "tournament.encounter"),
)
async def execute_map_winrate(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Career winrate on one map. ``value`` is a fraction 0..1.

    Without ``map_name`` the player qualifies when ANY single map with at least
    ``min_matches`` played meets the threshold; the evidence then describes the
    best such map.
    """
    op = params["op"]
    value = params["value"]
    map_filter = params.get("map_name")
    min_matches = params.get("min_matches", 5)

    op_fn = OPERATORS[op]
    played_expr = sa.func.count(sa.distinct(models.MatchStatistics.match_id))
    won_expr = sa.func.count(sa.distinct(sa.case((_PLAYER_WON_MAP, models.MatchStatistics.match_id))))
    winrate_expr = sa.cast(won_expr, sa.Float) / played_expr

    query = (
        sa.select(
            models.MatchStatistics.user_id,
            models.Map.name.label("map_name"),
            won_expr.label("wins"),
            played_expr.label("played"),
            winrate_expr.label("winrate"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Map, models.Map.id == models.Match.map_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(models.Tournament.workspace_id == context.workspace_id)
        .group_by(models.MatchStatistics.user_id, models.Map.id, models.Map.name)
        .having(played_expr >= min_matches, op_fn(winrate_expr, value))
    )

    if map_filter:
        query = query.where(models.Map.name == map_filter)

    result = await session.execute(query)
    # One player can clear the bar on several maps; the evidence shows the best.
    best: dict[tuple[int, ...], tuple[float, str, int, int]] = {}
    for row in result:
        key = (row.user_id,)
        winrate = float(row.winrate)
        current = best.get(key)
        if current is None or winrate > current[0]:
            best[key] = (winrate, row.map_name, int(row.wins), int(row.played))

    for key, (winrate, map_name, wins, played) in best.items():
        context.record_evidence(key, map=map_name, wins=wins, matches=played, winrate=round(winrate, 4))
    return set(best)
