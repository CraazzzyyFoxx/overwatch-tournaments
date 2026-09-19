"""team_players_match / captain_property — team composition conditions.

Grain: user_tournament.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HeroClass
from shared.models.achievements.achievement import AchievementGrain
from src import models

from ..context import EvalContext
from . import LeafSpec, ResultSet, register, register_spec

register_spec(
    LeafSpec(
        name="player_role",
        grain=AchievementGrain.user_tournament,
        description="Team-mate plays this role",
        required=("role",),
        depends_on=("tournament.player",),
        subcondition_only=True,
        subcondition_ok=True,
    )
)
register_spec(
    LeafSpec(
        name="player_div",
        grain=AchievementGrain.user_tournament,
        description="Team-mate's division compared against a value",
        required=("op", "value"),
        depends_on=("analytics.player_shift", "tournament.player"),
        subcondition_only=True,
        subcondition_ok=True,
    )
)


def _build_player_filter(
    condition: dict[str, Any],
) -> list:
    """Build SQLAlchemy WHERE clauses from a sub-condition tree for Player."""
    if "AND" in condition:
        clauses = []
        for child in condition["AND"]:
            clauses.extend(_build_player_filter(child))
        return clauses

    if "OR" in condition:
        or_groups = []
        for child in condition["OR"]:
            child_clauses = _build_player_filter(child)
            if not child_clauses:
                # A SQL-inexpressible child (player_div) must not drop that
                # branch; force the Python path for the whole OR.
                return []
            or_groups.append(sa.and_(*child_clauses) if len(child_clauses) > 1 else child_clauses[0])
        return [sa.or_(*or_groups)] if or_groups else []

    ctype = condition.get("type")
    params = condition.get("params", {})

    if ctype == "player_role":
        return [models.Player.role == HeroClass(params["role"])]
    if ctype == "player_div":
        # Division filter handled post-query since it needs grid
        return []
    if ctype == "is_newcomer":
        return [models.Player.is_newcomer.is_(True)]

    return []


def _needs_grid_check(condition: dict[str, Any]) -> bool:
    """Check if the sub-condition tree contains player_div."""
    if "AND" in condition:
        return any(_needs_grid_check(c) for c in condition["AND"])
    if "OR" in condition:
        return any(_needs_grid_check(c) for c in condition["OR"])
    return condition.get("type") == "player_div"


def _player_matches_div_condition(
    context: EvalContext,
    rank: int,
    source_version_id: int | None,
    condition: dict[str, Any],
) -> bool:
    """Check if a player's rank satisfies the player_div sub-condition."""
    from .stat_threshold import OPERATORS

    if "AND" in condition:
        return all(_player_matches_div_condition(context, rank, source_version_id, c) for c in condition["AND"])
    if "OR" in condition:
        return any(_player_matches_div_condition(context, rank, source_version_id, c) for c in condition["OR"])

    if condition.get("type") != "player_div":
        return True  # non-div conditions already filtered in SQL

    params = condition.get("params", {})
    if rank is None:
        return False
    div = context.resolve_division(rank, source_version_id=source_version_id)
    if not div:
        return False
    return OPERATORS[params["op"]](div.number, params["value"])


def _player_matches_condition(
    context: EvalContext,
    player: Any,
    condition: dict[str, Any],
) -> bool:
    if "AND" in condition:
        return all(_player_matches_condition(context, player, child) for child in condition["AND"])
    if "OR" in condition:
        return any(_player_matches_condition(context, player, child) for child in condition["OR"])

    ctype = condition.get("type")
    params = condition.get("params", {})

    if ctype == "player_role":
        return player.role == HeroClass(params["role"])
    if ctype == "player_div":
        return _player_matches_div_condition(
            context,
            player.rank,
            getattr(player, "division_grid_version_id", None),
            condition,
        )
    if ctype == "is_newcomer":
        return bool(player.is_newcomer)
    return True


@register(
    "team_players_match",
    grain=AchievementGrain.user_tournament,
    description="Team-mates matching a player sub-condition",
    required=("mode", "condition"),
    optional=("count_op", "count_value"),
    depends_on=("tournament.player", "tournament.team"),
)
async def execute_team_players_match(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Unified team condition: all/any/count players matching sub-condition.

    Awards ALL players on qualifying teams.
    Grain: user_tournament.
    """
    mode = params["mode"]  # "all", "any", "count"
    count_op = params.get("count_op", ">=")
    count_value = params.get("count_value", 1)
    sub_condition = params["condition"]

    from .stat_threshold import OPERATORS

    # Build SQL filters from sub-condition (except player_div which needs grid)
    sql_filters = _build_player_filter(sub_condition)
    needs_grid = _needs_grid_check(sub_condition)

    # Query: count matching players per team per tournament
    matching_query = (
        sa.select(
            models.Player.team_id,
            models.Player.tournament_id,
            sa.func.count().label("matching_count"),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
            *sql_filters,
        )
        .group_by(models.Player.team_id, models.Player.tournament_id)
    )

    if context.tournament:
        matching_query = matching_query.where(models.Player.tournament_id == context.tournament.id)

    # Total players per team
    total_query = (
        sa.select(
            models.Player.team_id,
            models.Player.tournament_id,
            sa.func.count().label("total_count"),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
        .group_by(models.Player.team_id, models.Player.tournament_id)
    )

    if context.tournament:
        total_query = total_query.where(models.Player.tournament_id == context.tournament.id)

    matching_sq = matching_query.subquery("matching")
    total_sq = total_query.subquery("total")

    # Find qualifying teams
    join_cond = sa.and_(
        matching_sq.c.team_id == total_sq.c.team_id,
        matching_sq.c.tournament_id == total_sq.c.tournament_id,
    )

    if mode == "all":
        team_query = (
            sa.select(matching_sq.c.team_id, matching_sq.c.tournament_id)
            .join(total_sq, join_cond)
            .where(matching_sq.c.matching_count == total_sq.c.total_count)
        )
    elif mode == "any":
        team_query = sa.select(matching_sq.c.team_id, matching_sq.c.tournament_id).where(
            matching_sq.c.matching_count >= 1
        )
    else:  # count
        op_fn = OPERATORS[count_op]
        team_query = (
            sa.select(total_sq.c.team_id, total_sq.c.tournament_id)
            .select_from(total_sq)
            .outerjoin(matching_sq, join_cond)
            .where(op_fn(sa.func.coalesce(matching_sq.c.matching_count, 0), count_value))
        )

    # Get all players on qualifying teams
    team_sq = team_query.subquery("qualifying_teams")

    players_query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(
            team_sq,
            sa.and_(
                models.Player.team_id == team_sq.c.team_id,
                models.Player.tournament_id == team_sq.c.tournament_id,
            ),
        )
        .where(models.Player.is_substitution.is_(False))
    )

    if not (needs_grid and (context.grid is not None or context.normalizer is not None)):
        result = await session.execute(players_query)
        return {(row[0], row[1]) for row in result}

    team_players_query = (
        sa.select(
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.team_id,
            models.Player.tournament_id,
            models.Player.role,
            models.Player.sub_role,
            models.Player.is_newcomer,
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

    if context.tournament:
        team_players_query = team_players_query.where(models.Player.tournament_id == context.tournament.id)

    team_players_result = await session.execute(team_players_query)
    grouped_players: dict[tuple[int, int], list[Any]] = {}
    for row in team_players_result:
        grouped_players.setdefault((row.team_id, row.tournament_id), []).append(row)

    qualifying_teams: set[tuple[int, int]] = set()
    for team_key, team_players in grouped_players.items():
        matching_count = sum(1 for player in team_players if _player_matches_condition(context, player, sub_condition))
        total_count = len(team_players)
        if mode == "all" and matching_count == total_count:
            qualifying_teams.add(team_key)
        elif mode == "any" and matching_count >= 1:
            qualifying_teams.add(team_key)
        elif mode == "count" and OPERATORS[count_op](matching_count, count_value):
            qualifying_teams.add(team_key)

    return {
        (player.user_id, player.tournament_id)
        for team_key, team_players in grouped_players.items()
        if team_key in qualifying_teams
        for player in team_players
    }


@register(
    "captain_property",
    grain=AchievementGrain.user_tournament,
    description="The team captain matches a player sub-condition",
    required=("condition",),
    depends_on=("tournament.player", "tournament.team"),
)
async def execute_captain_property(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Teammates of captain matching sub-condition. Grain: user_tournament.

    Awards teammates (NOT the captain) when the captain matches the sub-condition.
    """
    sub_condition = params["condition"]
    sql_filters = _build_player_filter(sub_condition)
    needs_grid = _needs_grid_check(sub_condition)

    # Find captains matching the sub-condition
    captain_query = (
        sa.select(
            models.WorkspaceMember.player_id.label("captain_user_id"),
            models.Player.team_id,
            models.Player.tournament_id,
            models.Player.role,
            models.Player.sub_role,
            models.Player.is_newcomer,
            models.Player.rank,
            models.Tournament.division_grid_version_id,
        )
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Team.captain_id == models.WorkspaceMember.player_id,
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
            *sql_filters,
        )
    )

    if context.tournament:
        captain_query = captain_query.where(models.Player.tournament_id == context.tournament.id)

    if needs_grid and (context.grid is not None or context.normalizer is not None):
        qualifying_captains: list[tuple[int, int, int]] = []
        captain_result = await session.execute(captain_query)
        for row in captain_result:
            if _player_matches_condition(context, row, sub_condition):
                qualifying_captains.append((row.captain_user_id, row.team_id, row.tournament_id))
        if not qualifying_captains:
            return set()

        captain_sq = (
            sa.values(
                sa.column("captain_user_id", sa.Integer),
                sa.column("team_id", sa.Integer),
                sa.column("tournament_id", sa.Integer),
                name="captains",
            )
            .data(qualifying_captains)
            .alias("captains")
        )
    else:
        captain_sq = captain_query.subquery("captains")

    # Get teammates (excluding captain)
    teammates_query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(
            captain_sq,
            sa.and_(
                models.Player.team_id == captain_sq.c.team_id,
                models.Player.tournament_id == captain_sq.c.tournament_id,
            ),
        )
        .where(
            models.WorkspaceMember.player_id != captain_sq.c.captain_user_id,
            models.Player.is_substitution.is_(False),
        )
    )

    result = await session.execute(teammates_query)
    return {(row[0], row[1]) for row in result}
