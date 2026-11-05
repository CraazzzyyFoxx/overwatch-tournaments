"""encounter_score / encounter_revenge â€” cross-encounter conditions."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.disciplines.overwatch.achievements.duel import Duel
from shared.disciplines.overwatch.achievements.stage_filters import (
    encounter_is_bracket,
    join_bracket_context,
    stage_is_completed,
)
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain

from . import ResultSet, register


def _encounter_query_with_stage_context() -> sa.Select:
    return join_bracket_context(
        sa.select(models.Encounter.tournament_id)
        .select_from(models.Encounter)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
    )


def join_final_encounters(query: sa.Select, workspace_id: int) -> sa.Select:
    """Narrow a query already joined to ``Encounter``/``BracketEncounter``/``Stage``/``StageItem`` to each tournament's final.

    Stage identity matters: the highest round number alone would let an earlier
    stage's round of the same number pass as the final, so the last bracket
    stage is picked first and the last round is taken *within* that stage --
    and only once that stage is completed: mid-stage its last round played so
    far is not the final, and a double elimination may still add a reset.
    """
    bracket_clause = encounter_is_bracket(
        bracket=models.BracketEncounter,
        stage=models.Stage,
        stage_item=models.StageItem,
    )
    stage_order = sa.func.coalesce(models.Stage.order, 0)

    final_stage_sq = (
        _encounter_query_with_stage_context()
        .with_only_columns(
            models.Encounter.tournament_id.label("tournament_id"),
            sa.func.max(stage_order).label("final_stage_order"),
        )
        .where(
            models.Encounter.status == "COMPLETED",
            models.Tournament.workspace_id == workspace_id,
            bracket_clause,
        )
        .group_by(models.Encounter.tournament_id)
        .subquery("final_stage")
    )

    final_round_sq = (
        _encounter_query_with_stage_context()
        .with_only_columns(
            models.Encounter.tournament_id.label("tournament_id"),
            stage_order.label("final_stage_order"),
            sa.func.max(models.BracketEncounter.round).label("final_round"),
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
            models.Tournament.workspace_id == workspace_id,
            bracket_clause,
            stage_is_completed(stage=models.Stage),
        )
        .group_by(models.Encounter.tournament_id, stage_order)
        .subquery("final_round")
    )

    return query.join(
        final_round_sq,
        sa.and_(
            models.Encounter.tournament_id == final_round_sq.c.tournament_id,
            stage_order == final_round_sq.c.final_stage_order,
            models.BracketEncounter.round == final_round_sq.c.final_round,
        ),
    )


@register(
    "encounter_score",
    grain=AchievementGrain.user_tournament,
    description="A series ended with one of the listed scorelines",
    required=("scores",),
    optional=("round_type", "side", "winner"),
    depends_on=("tournament.encounter", "tournament.player", "tournament.stage", "tournament.flow_node"),
)
async def execute_encounter_score(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Encounter with specific score pattern. Grain: user_tournament.

    params:
        scores: list of [slot 1 score, slot 2 score] pairs to match.
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

    duel = Duel()
    score_conditions = [
        sa.and_(duel.first.score == first_s, duel.second.score == second_s) for first_s, second_s in scores
    ]

    base_where = [
        sa.and_(
            models.Tournament.workspace_id == context.workspace_id, models.Tournament.discipline == context.discipline
        ),
        models.Encounter.status == "COMPLETED",
        sa.or_(*score_conditions),
    ]

    if context.tournament:
        base_where.append(models.Encounter.tournament_id == context.tournament.id)

    query = duel.join(
        _encounter_query_with_stage_context().with_only_columns(
            models.WorkspaceMember.player_id,
            models.Encounter.tournament_id,
        )
    )

    if round_type == "final":
        query = join_final_encounters(query, context.workspace_id)

    if side == "winner":
        target_team = models.Player.team_id == duel.winner_team_id
        base_where.append(duel.decided)
    elif side == "loser":
        target_team = models.Player.team_id == duel.loser_team_id
        base_where.append(duel.decided)
    else:  # both
        target_team = models.Player.team_id.in_((duel.first.team_id, duel.second.team_id))

    query = (
        query.join(
            models.Player,
            sa.and_(target_team, models.Player.tournament_id == models.Encounter.tournament_id),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(
            *base_where,
            models.Player.is_substitution.is_(False),
        )
    )

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}


@register(
    "encounter_revenge",
    grain=AchievementGrain.user_tournament,
    description="Beat a team that had beaten them earlier",
    depends_on=("tournament.encounter", "tournament.player"),
)
async def execute_encounter_revenge(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Team that lost to opponent earlier, then won. Grain: user_tournament."""
    e1 = sa.orm.aliased(models.Encounter, name="e1")
    e2 = sa.orm.aliased(models.Encounter, name="e2")
    d1 = Duel(e1, name="d1")
    d2 = Duel(e2, name="d2")

    same_teams = sa.or_(
        sa.and_(
            d1.first.team_id == d2.first.team_id,
            d1.second.team_id == d2.second.team_id,
        ),
        sa.and_(
            d1.first.team_id == d2.second.team_id,
            d1.second.team_id == d2.first.team_id,
        ),
    )

    query = sa.select(
        models.WorkspaceMember.player_id,
        e2.tournament_id,
    ).select_from(e1)
    query = d1.join(query).join(
        e2,
        sa.and_(
            e1.tournament_id == e2.tournament_id,
            e1.id < e2.id,
            e1.status == "COMPLETED",
            e2.status == "COMPLETED",
        ),
    )
    query = (
        d2.join(query)
        .join(models.Tournament, models.Tournament.id == e2.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == d2.winner_team_id,
                models.Player.tournament_id == e2.tournament_id,
            ),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(
            same_teams,
            d1.decided,
            d2.decided,
            d1.winner_team_id != d2.winner_team_id,
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(e2.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
