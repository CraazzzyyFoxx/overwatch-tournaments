from __future__ import annotations

import sqlalchemy as sa
from shared.core.enums import StageItemType, StageType

from src import models

BRACKET_STAGE_TYPES = (
    StageType.SINGLE_ELIMINATION,
    StageType.DOUBLE_ELIMINATION,
)
GROUP_STAGE_TYPES = (
    StageType.ROUND_ROBIN,
    StageType.SWISS,
)


def encounter_is_lower_bracket(
    *,
    encounter=models.Encounter,
    stage=models.Stage,
    stage_item=models.StageItem,
    tournament_group=models.TournamentGroup,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.and_(
            stage.stage_type == StageType.DOUBLE_ELIMINATION,
            sa.or_(
                stage_item.type == StageItemType.BRACKET_LOWER,
                encounter.round < 0,
            ),
        ),
        sa.and_(
            stage.id.is_(None),
            tournament_group.id.is_not(None),
            tournament_group.is_groups.is_(False),
            encounter.round < 0,
        ),
    )


def encounter_is_upper_bracket(
    *,
    encounter=models.Encounter,
    stage=models.Stage,
    stage_item=models.StageItem,
    tournament_group=models.TournamentGroup,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.and_(
            stage.stage_type == StageType.SINGLE_ELIMINATION,
            sa.or_(
                stage_item.type.in_(
                    (StageItemType.SINGLE_BRACKET, StageItemType.BRACKET_UPPER)
                ),
                stage_item.id.is_(None),
            ),
        ),
        sa.and_(
            stage.stage_type == StageType.DOUBLE_ELIMINATION,
            sa.or_(
                stage_item.type == StageItemType.BRACKET_UPPER,
                encounter.round > 0,
            ),
        ),
        sa.and_(
            stage.id.is_(None),
            tournament_group.id.is_not(None),
            tournament_group.is_groups.is_(False),
            encounter.round > 0,
        ),
    )


def encounter_is_bracket(
    *,
    encounter=models.Encounter,
    stage=models.Stage,
    stage_item=models.StageItem,
    tournament_group=models.TournamentGroup,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        encounter_is_upper_bracket(
            encounter=encounter,
            stage=stage,
            stage_item=stage_item,
            tournament_group=tournament_group,
        ),
        encounter_is_lower_bracket(
            encounter=encounter,
            stage=stage,
            stage_item=stage_item,
            tournament_group=tournament_group,
        ),
    )


def standing_is_elimination(
    *,
    standing=models.Standing,
    stage=models.Stage,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        stage.stage_type.in_(BRACKET_STAGE_TYPES),
        sa.and_(
            stage.id.is_(None),
            standing.buchholz.is_(None),
        ),
    )


def standing_is_groups(
    *,
    standing=models.Standing,
    stage=models.Stage,
) -> sa.ColumnElement[bool]:
    """Explicit dual of ``standing_is_elimination``.

    Matches group-stage standings: a round-robin/swiss stage, or a legacy
    standing with no stage but a non-null buchholz score. Written explicitly
    (rather than negating ``standing_is_elimination``) because NULL stage rows
    make boolean negation unreliable for legacy data.
    """
    return sa.or_(
        stage.stage_type.in_(GROUP_STAGE_TYPES),
        sa.and_(
            stage.id.is_(None),
            standing.buchholz.is_not(None),
        ),
    )
