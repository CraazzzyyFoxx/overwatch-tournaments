"""tournament_format â€” checks the tournament structure via stages with legacy fallback."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import StageType
from src import models

from ..context import EvalContext
from . import ResultSet, register
from ._stage_filters import BRACKET_STAGE_TYPES


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
        return bool(stage_type_set) and not has_bracket
    if fmt == "has_bracket":
        return has_bracket
    return False


@register("tournament_format")
async def execute(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Check tournament format. Grain: user_tournament."""
    fmt = params.get("format", "double_elim")

    stage_tournaments = (
        sa.select(models.Stage.tournament_id)
        .group_by(models.Stage.tournament_id)
    ).subquery("stage_tournaments")

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

    legacy_has_lower = (
        sa.select(models.Encounter.tournament_id)
        .join(
            models.TournamentGroup,
            models.TournamentGroup.id == models.Encounter.tournament_group_id,
        )
        .where(
            models.Encounter.round < 0,
            models.TournamentGroup.is_groups.is_(False),
            models.Encounter.status == "COMPLETED",
        )
        .group_by(models.Encounter.tournament_id)
    ).subquery("legacy_has_lower")

    legacy_has_bracket = (
        sa.select(models.Encounter.tournament_id)
        .join(
            models.TournamentGroup,
            models.TournamentGroup.id == models.Encounter.tournament_group_id,
        )
        .where(
            models.TournamentGroup.is_groups.is_(False),
            models.Encounter.status == "COMPLETED",
        )
        .group_by(models.Encounter.tournament_id)
    ).subquery("legacy_has_bracket")

    has_stage_config = models.Tournament.id.in_(sa.select(stage_tournaments.c.tournament_id))
    no_stage_config = ~has_stage_config

    if fmt == "double_elim":
        tournament_filter = sa.or_(
            models.Tournament.id.in_(sa.select(stage_double_tournaments.c.tournament_id)),
            sa.and_(
                no_stage_config,
                models.Tournament.id.in_(sa.select(legacy_has_lower.c.tournament_id)),
            ),
        )
    elif fmt == "single_elim":
        tournament_filter = sa.or_(
            sa.and_(
                models.Tournament.id.in_(sa.select(stage_single_tournaments.c.tournament_id)),
                ~models.Tournament.id.in_(sa.select(stage_double_tournaments.c.tournament_id)),
            ),
            sa.and_(
                no_stage_config,
                models.Tournament.id.in_(sa.select(legacy_has_bracket.c.tournament_id)),
                ~models.Tournament.id.in_(sa.select(legacy_has_lower.c.tournament_id)),
            ),
        )
    elif fmt == "round_robin":
        tournament_filter = sa.or_(
            sa.and_(
                has_stage_config,
                ~models.Tournament.id.in_(sa.select(stage_bracket_tournaments.c.tournament_id)),
            ),
            sa.and_(
                no_stage_config,
                ~models.Tournament.id.in_(sa.select(legacy_has_bracket.c.tournament_id)),
            ),
        )
    elif fmt == "has_bracket":
        tournament_filter = sa.or_(
            models.Tournament.id.in_(sa.select(stage_bracket_tournaments.c.tournament_id)),
            sa.and_(
                no_stage_config,
                models.Tournament.id.in_(sa.select(legacy_has_bracket.c.tournament_id)),
            ),
        )
    else:
        return set()

    query = (
        sa.select(models.Player.user_id, models.Player.tournament_id)
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
