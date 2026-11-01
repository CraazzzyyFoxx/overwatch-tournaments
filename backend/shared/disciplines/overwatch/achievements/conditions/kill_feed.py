"""Kill conditions over native events.

Actor/target workspace members are resolved to global result keys explicitly.
A fight is ``(match_id, segment, data.fight)``; event multiplicity is preserved.

Grains: ``fight_multikill`` is user_match; ``duel_dominance`` is user, or
user_tournament when ``scope="tournament"``.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain
from shared.repository.stats_queries import match_context

from . import ResultSet, register
from .stat_threshold import OPERATORS

_MATCHES = match_context(discipline="overwatch")
_ACTOR = sa.orm.aliased(models.WorkspaceMember, name="kill_actor")
_TARGET = sa.orm.aliased(models.WorkspaceMember, name="kill_target")


def _scoped_kills(
    context: EvalContext,
    *columns: Any,
    narrow_to_tournament: bool,
) -> sa.Select:
    """Kill-feed rows joined up to the tournament, workspace-filtered.

    Self-kills (environmental suicides land in the feed with the victim as
    their own killer) are never "an enemy" and are excluded everywhere.
    """
    query = (
        sa.select(*columns)
        .select_from(models.StatsEvent)
        .join(_MATCHES, _MATCHES.c.id == models.StatsEvent.match_id)
        .join(
            models.EventType,
            sa.and_(
                models.EventType.id == models.StatsEvent.type_id,
                models.EventType.discipline == _MATCHES.c.discipline,
            ),
        )
        .join(
            _ACTOR,
            sa.and_(
                _ACTOR.id == models.StatsEvent.actor_member_id,
                _ACTOR.workspace_id == _MATCHES.c.workspace_id,
            ),
        )
        .join(
            _TARGET,
            sa.and_(
                _TARGET.id == models.StatsEvent.target_member_id,
                _TARGET.workspace_id == _MATCHES.c.workspace_id,
            ),
        )
        .where(
            _MATCHES.c.workspace_id == context.workspace_id,
            # Mix stats live only inside the mix (mix encounters have no tournament).
            _MATCHES.c.tournament_id.is_not(None),
            models.EventType.code == "kill",
            models.StatsEvent.actor_member_id != models.StatsEvent.target_member_id,
        )
    )
    if narrow_to_tournament and context.tournament:
        query = query.where(_MATCHES.c.tournament_id == context.tournament.id)
    return query


@register(
    "fight_multikill",
    grain=AchievementGrain.user_match,
    description="Killed several enemies inside a single fight",
    optional=("min_kills", "op", "value"),
    depends_on=("stats.event", "stats.match", "tournament.encounter"),
)
async def execute_fight_multikill(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count fights on one map where the player got ``min_kills`` kills. Grain: user_match."""
    min_kills = int(params.get("min_kills", 3))
    op = params.get("op", ">=")
    value = params.get("value", 1)
    op_fn = OPERATORS[op]

    per_fight = (
        _scoped_kills(
            context,
            _ACTOR.player_id.label("user_id"),
            models.StatsEvent.match_id,
            _MATCHES.c.tournament_id,
            sa.func.count().label("kills"),
            narrow_to_tournament=True,
        )
        .group_by(
            _ACTOR.player_id,
            models.StatsEvent.match_id,
            _MATCHES.c.tournament_id,
            models.StatsEvent.segment,
            models.StatsEvent.data["fight"].as_integer(),
        )
        .subquery()
    )

    fights = sa.func.sum(sa.case((per_fight.c.kills >= min_kills, 1), else_=0))
    query = (
        sa.select(
            per_fight.c.user_id,
            per_fight.c.tournament_id,
            per_fight.c.match_id,
            fights.label("fights"),
            sa.func.max(per_fight.c.kills).label("best_fight_kills"),
        )
        .group_by(per_fight.c.user_id, per_fight.c.tournament_id, per_fight.c.match_id)
        .having(op_fn(fights, value))
    )

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = (row.user_id, row.tournament_id, row.match_id)
        keys.add(key)
        context.record_evidence(
            key,
            fights=int(row.fights),
            min_kills=min_kills,
            best_fight_kills=int(row.best_fight_kills),
        )
    return keys


@register(
    "duel_dominance",
    grain=AchievementGrain.user,
    description="Dominated one specific opponent across their meetings",
    optional=("min_diff", "min_kills", "op", "scope", "value"),
    depends_on=("stats.event", "stats.match", "tournament.encounter"),
    grain_for=lambda params: (
        AchievementGrain.user_tournament if params.get("scope") == "tournament" else AchievementGrain.user
    ),
)
async def execute_duel_dominance(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Count opponents the player out-killed by a margin. Grain: user or user_tournament."""
    scope = params.get("scope", "global")
    min_kills = int(params.get("min_kills", 10))
    min_diff = params.get("min_diff")
    op = params.get("op", ">=")
    value = params.get("value", 1)
    op_fn = OPERATORS[op]
    per_tournament = scope == "tournament"

    pair_cols = [
        _ACTOR.player_id.label("user_id"),
        _TARGET.player_id.label("opponent_id"),
    ]
    if per_tournament:
        pair_cols.append(_MATCHES.c.tournament_id)

    pairs = (
        _scoped_kills(
            context,
            *pair_cols,
            sa.func.count().label("kills"),
            narrow_to_tournament=per_tournament,
        )
        .group_by(*pair_cols)
        .subquery()
    )
    reverse = pairs.alias("reverse_pairs")

    join_on = sa.and_(
        reverse.c.user_id == pairs.c.opponent_id,
        reverse.c.opponent_id == pairs.c.user_id,
    )
    if per_tournament:
        join_on = sa.and_(join_on, reverse.c.tournament_id == pairs.c.tournament_id)

    deaths = sa.func.coalesce(reverse.c.kills, 0)
    select_cols = [pairs.c.user_id]
    if per_tournament:
        select_cols.append(pairs.c.tournament_id)
    select_cols += [pairs.c.opponent_id, pairs.c.kills, deaths.label("deaths")]

    query = sa.select(*select_cols).select_from(pairs).outerjoin(reverse, join_on).where(pairs.c.kills >= min_kills)

    result = await session.execute(query)

    # Dominated pairings only — a handful of rows, so the per-player rollup
    # (count plus the single best pairing) is cheaper to do here than as a
    # second aggregate over the same subquery.
    dominated: dict[tuple[int, ...], list[tuple[int, int, int]]] = {}
    for row in result:
        kills = int(row.kills)
        deaths_count = int(row.deaths)
        if min_diff is not None and kills - deaths_count < min_diff:
            continue
        key = (row.user_id, row.tournament_id) if per_tournament else (row.user_id,)
        dominated.setdefault(key, []).append((kills, deaths_count, row.opponent_id))

    keys: ResultSet = set()
    for key, pairings in dominated.items():
        if not op_fn(len(pairings), value):
            continue
        best_kills, best_deaths, best_opponent = max(pairings, key=lambda pair: (pair[0] - pair[1], pair[0]))
        keys.add(key)
        context.record_evidence(
            key,
            opponents=len(pairings),
            opponent_id=best_opponent,
            kills=best_kills,
            deaths=best_deaths,
        )
    return keys
