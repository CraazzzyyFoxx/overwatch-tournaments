"""bracket_path â€” checks a team's path through the tournament bracket."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.disciplines.overwatch.achievements.duel import Duel, active_seat
from shared.disciplines.overwatch.achievements.stage_filters import (
    encounter_is_lower_bracket,
    encounter_is_upper_bracket,
    join_bracket_context,
    stage_is_completed,
)
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain

from . import ResultSet, register


def _encounter_base_query(context: EvalContext) -> sa.Select:
    query = join_bracket_context(
        sa.select(models.Encounter.tournament_id)
        .select_from(models.Encounter)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
    ).where(
        models.Encounter.status == "COMPLETED",
        sa.and_(
            models.Tournament.workspace_id == context.workspace_id, models.Tournament.discipline == context.discipline
        ),
        # A route is only known once its bracket is over: mid-stage an
        # "upper only" team may still drop, a lost round may still change.
        stage_is_completed(stage=models.Stage),
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    return query


def _team_participants_query(
    context: EvalContext,
    *,
    where_clause: sa.ColumnElement[bool],
) -> sa.Select:
    """Every team seated in a matching encounter, once per encounter it holds a seat in."""
    seat, on_seat = active_seat()
    return (
        _encounter_base_query(context)
        .join(seat, on_seat)
        .with_only_columns(
            models.Encounter.tournament_id.label("tournament_id"),
            seat.team_id.label("team_id"),
        )
        .where(where_clause, seat.team_id.is_not(None))
    )


def _decided_teams_query(
    context: EvalContext,
    *,
    where_clause: sa.ColumnElement[bool],
    winners: bool,
) -> sa.Select:
    """The winning (or losing) team of every decided duel; a drawn series has neither."""
    duel = Duel()
    return (
        duel.join(_encounter_base_query(context))
        .with_only_columns(
            models.Encounter.tournament_id.label("tournament_id"),
            (duel.winner_team_id if winners else duel.loser_team_id).label("team_id"),
        )
        .where(where_clause, duel.decided)
    )


@register(
    "bracket_path",
    grain=AchievementGrain.user_tournament,
    description="The team's route through the bracket",
    optional=("lost_in_round", "min_lower_bracket_wins", "played_lower_bracket", "played_upper_bracket"),
    depends_on=("tournament.encounter", "tournament.player", "tournament.stage", "tournament.flow_node"),
)
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
        bracket=models.BracketEncounter,
        stage=models.Stage,
        stage_item=models.StageItem,
    )
    upper_clause = encounter_is_upper_bracket(
        bracket=models.BracketEncounter,
        stage=models.Stage,
        stage_item=models.StageItem,
    )

    if lost_in_round:
        upper_clause = sa.and_(
            upper_clause,
            OPERATORS[lost_in_round["op"]](models.BracketEncounter.round, lost_in_round["value"]),
        )

    if played_lower:
        candidate_queries: list[sa.Select] = []
        if min_lb_wins:
            # Grouped over the labelled output: the seats carry a ``tournament_id`` of their own,
            # so naming the column inside the joined query is ambiguous on Postgres.
            lower_wins = _decided_teams_query(context, where_clause=lower_clause, winners=True).subquery("lower_wins")
            lower_win_counts = (
                sa.select(lower_wins.c.tournament_id, lower_wins.c.team_id)
                .group_by(lower_wins.c.tournament_id, lower_wins.c.team_id)
                .having(sa.func.count() >= min_lb_wins)
            )
            candidate_queries.append(lower_win_counts)
        else:
            candidate_queries.append(_team_participants_query(context, where_clause=lower_clause))
            candidate_queries.append(_decided_teams_query(context, where_clause=upper_clause, winners=False))

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

    result = await session.execute(players_query)
    return {(row[0], row[1]) for row in result}
