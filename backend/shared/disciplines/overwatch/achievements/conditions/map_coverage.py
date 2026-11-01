"""map_coverage / map_winrate — which maps and gamemodes a player actually played.

Participation is telemetry, not a roster: a player counts for a map when they
have a round-0 ``HeroTimePlayed`` row on it, so substitutes who never played are
absent by construction and no ``is_substitution`` filter is needed.

Participation reads only whole-match playtime facts, not every statistic.
Wins compare the participant's observed score with its opponent, not the
official game result.

Grains: ``map_coverage`` is user (user_tournament with ``scope="tournament"``),
``map_winrate`` is user.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import player_facts

from . import ResultSet, register
from .match_win import winning_teams

OPERATORS = {
    "==": lambda col, val: col == val,
    "!=": lambda col, val: col != val,
    ">=": lambda col, val: col >= val,
    ">": lambda col, val: col > val,
    "<=": lambda col, val: col <= val,
    "<": lambda col, val: col < val,
}

_FACTS = player_facts(discipline="overwatch")
_WINNERS = winning_teams()
_PLAYER_WON_MAP = sa.exists(
    sa.select(1)
    .select_from(_WINNERS)
    .where(
        _WINNERS.c.match_id == _FACTS.c.match_id,
        _WINNERS.c.encounter_team_id == _FACTS.c.encounter_team_id,
    )
    .correlate(_FACTS)
)
# Mix stats live only inside the mix (mix encounters have no tournament).
_PLAYED_MAP = sa.and_(
    _FACTS.c.segment == 0, _FACTS.c.stat_code == "hero_time_played", _FACTS.c.tournament_id.is_not(None)
)


@register(
    "map_coverage",
    grain=AchievementGrain.user,
    description="Distinct maps or gamemodes the player has played or won on",
    required=("field", "op", "value"),
    optional=("gamemode", "outcome", "scope"),
    depends_on=("stats.match", "stats.fact", "tournament.encounter"),
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
        distinct_col = _FACTS.c.map_entity_id
    elif field == "gamemode":
        # The match's own mode, not the map's catalog parent.
        distinct_col = _FACTS.c.mode_entity_id
    else:
        raise ValueError(f"Unsupported map_coverage field: {field!r}")

    if outcome not in ("played", "won"):
        raise ValueError(f"Unsupported map_coverage outcome: {outcome!r}")

    op_fn = OPERATORS[op]
    count_expr = sa.func.count(sa.distinct(distinct_col))

    group_cols: list[Any] = [_FACTS.c.player_id]
    if scope == "tournament":
        group_cols.append(_FACTS.c.tournament_id)

    query = (
        sa.select(*group_cols, count_expr.label("measured"))
        .select_from(_FACTS)
        .join(models.CatalogEntity, models.CatalogEntity.id == _FACTS.c.map_entity_id)
        .where(
            _FACTS.c.workspace_id == context.workspace_id,
            models.CatalogEntity.kind == "map",
            models.CatalogEntity.discipline == "overwatch",
            _PLAYED_MAP,
        )
        .group_by(*group_cols)
        .having(op_fn(count_expr, value))
    )

    if outcome == "won":
        query = query.where(_PLAYER_WON_MAP)

    if gamemode:
        mode = aliased(models.CatalogEntity, name="mode")
        query = query.join(mode, mode.id == _FACTS.c.mode_entity_id).where(
            mode.name == gamemode, mode.kind == "mode", mode.discipline == "overwatch"
        )

    if context.tournament and scope == "tournament":
        query = query.where(_FACTS.c.tournament_id == context.tournament.id)

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
    depends_on=("stats.match", "stats.fact", "tournament.encounter"),
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
    played_expr = sa.func.count(sa.distinct(_FACTS.c.match_id))
    won_expr = sa.func.count(sa.distinct(sa.case((_PLAYER_WON_MAP, _FACTS.c.match_id))))
    winrate_expr = sa.cast(won_expr, sa.Float) / played_expr

    query = (
        sa.select(
            _FACTS.c.player_id.label("user_id"),
            models.CatalogEntity.name.label("map_name"),
            won_expr.label("wins"),
            played_expr.label("played"),
            winrate_expr.label("winrate"),
        )
        .select_from(_FACTS)
        .join(models.CatalogEntity, models.CatalogEntity.id == _FACTS.c.map_entity_id)
        .where(
            _FACTS.c.workspace_id == context.workspace_id,
            models.CatalogEntity.kind == "map",
            models.CatalogEntity.discipline == "overwatch",
            _PLAYED_MAP,
        )
        .group_by(_FACTS.c.player_id, models.CatalogEntity.id, models.CatalogEntity.name)
        .having(played_expr >= min_matches, op_fn(winrate_expr, value))
    )

    if map_filter:
        query = query.where(models.CatalogEntity.name == map_filter)

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
