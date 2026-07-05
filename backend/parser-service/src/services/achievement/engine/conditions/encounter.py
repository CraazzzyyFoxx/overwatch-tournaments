"""encounter_score / encounter_revenge â€” cross-encounter conditions."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import encounter_is_bracket


def _encounter_query_with_stage_context() -> sa.Select:
    return (
        sa.select(models.Encounter.tournament_id)
        .select_from(models.Encounter)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .outerjoin(models.Stage, models.Stage.id == models.Encounter.stage_id)
        .outerjoin(models.StageItem, models.StageItem.id == models.Encounter.stage_item_id)
        .outerjoin(
            models.TournamentGroup,
            models.TournamentGroup.id == models.Encounter.tournament_group_id,
        )
    )


@register("encounter_score")
async def execute_encounter_score(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Encounter with specific score pattern. Grain: user_tournament.

    params:
        scores: list of [home_score, away_score] pairs to match.
        round_type: "any" (default) | "final".
        side: which players to award — "winner" (default), "loser", or "both".
        winner: legacy bool alias — True → side="winner", False → side="both".
            Ignored when ``side`` is provided explicitly.
    """
    round_type = params.get("round_type", "any")
    scores = params["scores"]
    side = params.get("side")
    if side is None:
        side = "winner" if params.get("winner", True) else "both"

    score_conditions = [
        sa.and_(
            models.Encounter.home_score == home_s,
            models.Encounter.away_score == away_s,
        )
        for home_s, away_s in scores
    ]

    base_where = [
        models.Tournament.workspace_id == context.workspace_id,
        models.Encounter.status == "COMPLETED",
        sa.or_(*score_conditions),
    ]

    if context.tournament:
        base_where.append(models.Encounter.tournament_id == context.tournament.id)

    encounter_select = _encounter_query_with_stage_context()

    if round_type == "final":
        bracket_clause = encounter_is_bracket(
            encounter=models.Encounter,
            stage=models.Stage,
            stage_item=models.StageItem,
            tournament_group=models.TournamentGroup,
        )
        stage_order = sa.func.coalesce(models.Stage.order, 0)

        final_stage_sq = (
            encounter_select.with_only_columns(
                models.Encounter.tournament_id.label("tournament_id"),
                sa.func.max(stage_order).label("final_stage_order"),
            )
            .where(
                models.Encounter.status == "COMPLETED",
                models.Tournament.workspace_id == context.workspace_id,
                bracket_clause,
            )
            .group_by(models.Encounter.tournament_id)
            .subquery("final_stage")
        )

        final_round_sq = (
            _encounter_query_with_stage_context()
            .with_only_columns(
                models.Encounter.tournament_id.label("tournament_id"),
                sa.func.max(models.Encounter.round).label("final_round"),
            )
            .join(
                final_stage_sq,
                sa.and_(
                    models.Encounter.tournament_id == final_stage_sq.c.tournament_id,
                    stage_order == final_stage_sq.c.final_stage_order,
                ),
            )
            .where(
                models.Encounter.status == "COMPLETED",
                models.Tournament.workspace_id == context.workspace_id,
                bracket_clause,
            )
            .group_by(models.Encounter.tournament_id)
            .subquery("final_round")
        )

        query = (
            _encounter_query_with_stage_context()
            .with_only_columns(
                models.WorkspaceMember.player_id,
                models.Encounter.tournament_id,
            )
            .join(
                final_round_sq,
                sa.and_(
                    models.Encounter.tournament_id == final_round_sq.c.tournament_id,
                    models.Encounter.round == final_round_sq.c.final_round,
                ),
            )
        )
    else:
        query = _encounter_query_with_stage_context().with_only_columns(
            models.WorkspaceMember.player_id,
            models.Encounter.tournament_id,
        )

    if side in ("winner", "loser"):
        if side == "winner":
            target_team_id = sa.case(
                (
                    models.Encounter.home_score > models.Encounter.away_score,
                    models.Encounter.home_team_id,
                ),
                else_=models.Encounter.away_team_id,
            )
        else:  # loser
            target_team_id = sa.case(
                (
                    models.Encounter.home_score < models.Encounter.away_score,
                    models.Encounter.home_team_id,
                ),
                else_=models.Encounter.away_team_id,
            )
        query = query.join(
            models.Player,
            sa.and_(
                models.Player.team_id == target_team_id,
                models.Player.tournament_id == models.Encounter.tournament_id,
            ),
        )
    else:  # both
        query = query.join(
            models.Player,
            sa.and_(
                sa.or_(
                    models.Player.team_id == models.Encounter.home_team_id,
                    models.Player.team_id == models.Encounter.away_team_id,
                ),
                models.Player.tournament_id == models.Encounter.tournament_id,
            ),
        )

    query = query.join(
        models.WorkspaceMember,
        models.WorkspaceMember.id == models.Player.workspace_member_id,
    ).where(
        *base_where,
        models.Player.is_substitution.is_(False),
    )

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register("encounter_revenge")
async def execute_encounter_revenge(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Team that lost to opponent earlier, then won. Grain: user_tournament."""
    e1 = sa.orm.aliased(models.Encounter, name="e1")
    e2 = sa.orm.aliased(models.Encounter, name="e2")

    same_teams = sa.or_(
        sa.and_(
            e1.home_team_id == e2.home_team_id,
            e1.away_team_id == e2.away_team_id,
        ),
        sa.and_(
            e1.home_team_id == e2.away_team_id,
            e1.away_team_id == e2.home_team_id,
        ),
    )

    e1_winner = sa.case(
        (e1.home_score > e1.away_score, e1.home_team_id),
        else_=e1.away_team_id,
    )
    e2_winner = sa.case(
        (e2.home_score > e2.away_score, e2.home_team_id),
        else_=e2.away_team_id,
    )

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            e2.tournament_id,
        )
        .select_from(e1)
        .join(
            e2,
            sa.and_(
                e1.tournament_id == e2.tournament_id,
                e1.id < e2.id,
                same_teams,
                e1_winner != e2_winner,
                e1.status == "COMPLETED",
                e2.status == "COMPLETED",
            ),
        )
        .join(models.Tournament, models.Tournament.id == e2.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == e2_winner,
                models.Player.tournament_id == e2.tournament_id,
            ),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(e2.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
