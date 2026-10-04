"""Stage/bracket column-expression filters for achievement conditions.

Pure SQLAlchemy column-expression builders (zero ``AsyncSession``/``await``) —
moved here from ``engine/conditions/_stage_filters.py`` per the parser-service
OOP refactor. Used by the ``@register`` leaf-condition plugins in
``src/services/achievement/engine/conditions/*.py`` to identify bracket vs.
group-stage rows.
"""

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
) -> sa.ColumnElement[bool]:
    return sa.and_(
        stage.stage_type == StageType.DOUBLE_ELIMINATION,
        sa.or_(
            stage_item.type == StageItemType.BRACKET_LOWER,
            encounter.round < 0,
        ),
    )


def encounter_is_upper_bracket(
    *,
    encounter=models.Encounter,
    stage=models.Stage,
    stage_item=models.StageItem,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.and_(
            stage.stage_type == StageType.SINGLE_ELIMINATION,
            sa.or_(
                stage_item.type.in_((StageItemType.SINGLE_BRACKET, StageItemType.BRACKET_UPPER)),
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
    )


def encounter_is_bracket(
    *,
    encounter=models.Encounter,
    stage=models.Stage,
    stage_item=models.StageItem,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        encounter_is_upper_bracket(
            encounter=encounter,
            stage=stage,
            stage_item=stage_item,
        ),
        encounter_is_lower_bracket(
            encounter=encounter,
            stage=stage,
            stage_item=stage_item,
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


def stage_is_completed(*, stage=models.Stage) -> sa.ColumnElement[bool]:
    """The row's stage has finished (``Stage.is_completed``, kept by the standings recalc).

    A row with no stage at all (legacy, pre-stage-system data) passes: those
    tournaments were imported finished, and dropping them here would revoke
    achievements nobody could ever re-earn.
    """
    return sa.or_(stage.id.is_(None), stage.is_completed.is_(True))
