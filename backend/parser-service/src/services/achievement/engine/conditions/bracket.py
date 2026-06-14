"""bracket_path â€” checks a team's path through the tournament bracket."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import encounter_is_lower_bracket, encounter_is_upper_bracket


def _encounter_base_query(context: EvalContext) -> sa.Select:
    query = (
        sa.select(models.Encounter.tournament_id)
        .select_from(models.Encounter)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .outerjoin(models.Stage, models.Stage.id == models.Encounter.stage_id)
        .outerjoin(models.StageItem, models.StageItem.id == models.Encounter.stage_item_id)
        .outerjoin(
            models.TournamentGroup,
            models.TournamentGroup.id == models.Encounter.tournament_group_id,
        )
        .where(
            models.Encounter.status == "COMPLETED",
            models.Tournament.workspace_id == context.workspace_id,
        )
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    return query


def _team_participants_query(
    context: EvalContext,
    *,
    where_clause: sa.ColumnElement[bool],
) -> sa.Select:
    base_query = _encounter_base_query(context).where(where_clause)
    home_query = base_query.with_only_columns(
        models.Encounter.tournament_id.label("tournament_id"),
        models.Encounter.home_team_id.label("team_id"),
    ).where(models.Encounter.home_team_id.is_not(None))
    away_query = base_query.with_only_columns(
        models.Encounter.tournament_id.label("tournament_id"),
        models.Encounter.away_team_id.label("team_id"),
    ).where(models.Encounter.away_team_id.is_not(None))
    return sa.union_all(home_query, away_query)


def _winner_teams_query(
    context: EvalContext,
    *,
    where_clause: sa.ColumnElement[bool],
) -> sa.Select:
    winning_team_id = sa.case(
        (
            models.Encounter.home_score > models.Encounter.away_score,
            models.Encounter.home_team_id,
        ),
        else_=models.Encounter.away_team_id,
    )
    return (
        _encounter_base_query(context)
        .with_only_columns(
            models.Encounter.tournament_id.label("tournament_id"),
            winning_team_id.label("team_id"),
        )
        .where(
            where_clause,
            models.Encounter.home_score != models.Encounter.away_score,
        )
    )


def _loser_teams_query(
    context: EvalContext,
    *,
    where_clause: sa.ColumnElement[bool],
) -> sa.Select:
    losing_team_id = sa.case(
        (
            models.Encounter.home_score < models.Encounter.away_score,
            models.Encounter.home_team_id,
        ),
        else_=models.Encounter.away_team_id,
    )
    return (
        _encounter_base_query(context)
        .with_only_columns(
            models.Encounter.tournament_id.label("tournament_id"),
            losing_team_id.label("team_id"),
        )
        .where(
            where_clause,
            models.Encounter.home_score != models.Encounter.away_score,
        )
    )


@register("bracket_path")
async def execute_bracket_path(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Check team's bracket path in tournament. Grain: user_tournament."""
    played_lower = params.get("played_lower_bracket", True)
    played_upper = params.get("played_upper_bracket")
    min_lb_wins = params.get("min_lower_bracket_wins")
    lost_in_round = params.get("lost_in_round")

    from .stat_threshold import OPERATORS

    lower_clause = encounter_is_lower_bracket(
        encounter=models.Encounter,
        stage=models.Stage,
        stage_item=models.StageItem,
        tournament_group=models.TournamentGroup,
    )
    upper_clause = encounter_is_upper_bracket(
        encounter=models.Encounter,
        stage=models.Stage,
        stage_item=models.StageItem,
        tournament_group=models.TournamentGroup,
    )

    if lost_in_round:
        upper_clause = sa.and_(
            upper_clause,
            OPERATORS[lost_in_round["op"]](models.Encounter.round, lost_in_round["value"]),
        )

    if played_lower:
        candidate_queries: list[sa.Select] = []
        if min_lb_wins:
            lower_win_counts = (
                _winner_teams_query(context, where_clause=lower_clause)
                .group_by(sa.text("tournament_id"), sa.text("team_id"))
                .having(sa.func.count() >= min_lb_wins)
            )
            candidate_queries.append(lower_win_counts)
        else:
            candidate_queries.append(_team_participants_query(context, where_clause=lower_clause))
            candidate_queries.append(_loser_teams_query(context, where_clause=upper_clause))

        team_union = sa.union_all(*candidate_queries).subquery("candidate_bracket_teams")
        team_query = sa.select(
            team_union.c.team_id,
            team_union.c.tournament_id,
        ).group_by(
            team_union.c.team_id,
            team_union.c.tournament_id,
        )
    elif played_upper is True:
        upper_teams = _team_participants_query(context, where_clause=upper_clause).subquery("upper_teams")
        lower_teams = _team_participants_query(context, where_clause=lower_clause).subquery("lower_teams")

        team_query = (
            sa.select(upper_teams.c.team_id, upper_teams.c.tournament_id)
            .outerjoin(
                lower_teams,
                sa.and_(
                    lower_teams.c.team_id == upper_teams.c.team_id,
                    lower_teams.c.tournament_id == upper_teams.c.tournament_id,
                ),
            )
            .where(lower_teams.c.team_id.is_(None))
            .group_by(upper_teams.c.team_id, upper_teams.c.tournament_id)
        )
    else:
        return set()

    team_sq = team_query.subquery("qualifying_teams")

    players_query = (
        sa.select(models.Player.user_id, models.Player.tournament_id)
        .join(
            team_sq,
            sa.and_(
                models.Player.team_id == team_sq.c.team_id,
                models.Player.tournament_id == team_sq.c.tournament_id,
            ),
        )
        .where(models.Player.is_substitution.is_(False))
    )

    result = await session.execute(players_query)
    return {(row[0], row[1]) for row in result}
