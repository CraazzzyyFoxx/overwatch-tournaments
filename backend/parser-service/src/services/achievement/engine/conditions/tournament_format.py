"""tournament_format — checks the tournament structure via stages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import StageType
from shared.models.achievements.achievement import AchievementGrain
from src import models
from src.domain.achievement_stage_filters import BRACKET_STAGE_TYPES

from ..context import EvalContext
from . import ResultSet, register


def matches_tournament_format(stage_types: Iterable[StageType], fmt: str) -> bool:
    stage_type_set = set(stage_types)
    has_double = StageType.DOUBLE_ELIMINATION in stage_type_set
    has_single = StageType.SINGLE_ELIMINATION in stage_type_set
    has_bracket = has_double or has_single

    if fmt == "double_elim":
        return has_double
    if fmt == "single_elim":
        return has_single and not has_double
    if fmt == "round_robin":
        return StageType.ROUND_ROBIN in stage_type_set
    if fmt == "has_bracket":
        return has_bracket
    return False


@register(
    "tournament_format",
    grain=AchievementGrain.user_tournament,
    description="The tournament ran in this bracket format",
    required=("format",),
    depends_on=("tournament.encounter", "tournament.player"),
)
async def execute(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Check tournament format. Grain: user_tournament."""
    fmt = params.get("format", "double_elim")

    stage_bracket_tournaments = (
        sa.select(models.Stage.tournament_id)
        .where(models.Stage.stage_type.in_(BRACKET_STAGE_TYPES))
        .group_by(models.Stage.tournament_id)
    ).subquery("stage_bracket_tournaments")

    stage_single_tournaments = (
        sa.select(models.Stage.tournament_id)
        .where(models.Stage.stage_type == StageType.SINGLE_ELIMINATION)
        .group_by(models.Stage.tournament_id)
    ).subquery("stage_single_tournaments")

    stage_double_tournaments = (
        sa.select(models.Stage.tournament_id)
        .where(models.Stage.stage_type == StageType.DOUBLE_ELIMINATION)
        .group_by(models.Stage.tournament_id)
    ).subquery("stage_double_tournaments")

    stage_round_robin_tournaments = (
        sa.select(models.Stage.tournament_id)
        .where(models.Stage.stage_type == StageType.ROUND_ROBIN)
        .group_by(models.Stage.tournament_id)
    ).subquery("stage_round_robin_tournaments")

    if fmt == "double_elim":
        tournament_filter = models.Tournament.id.in_(sa.select(stage_double_tournaments.c.tournament_id))
    elif fmt == "single_elim":
        tournament_filter = sa.and_(
            models.Tournament.id.in_(sa.select(stage_single_tournaments.c.tournament_id)),
            ~models.Tournament.id.in_(sa.select(stage_double_tournaments.c.tournament_id)),
        )
    elif fmt == "round_robin":
        tournament_filter = models.Tournament.id.in_(sa.select(stage_round_robin_tournaments.c.tournament_id))
    elif fmt == "has_bracket":
        tournament_filter = models.Tournament.id.in_(sa.select(stage_bracket_tournaments.c.tournament_id))
    else:
        return set()

    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            tournament_filter,
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(models.Player.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
