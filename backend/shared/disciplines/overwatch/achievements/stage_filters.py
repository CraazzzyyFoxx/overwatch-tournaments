"""Stage/bracket column-expression filters for achievement conditions.

Pure SQLAlchemy column-expression builders (zero ``AsyncSession``/``await``) —
used by the ``@register`` leaf conditions in ``conditions/*.py`` to identify bracket vs.
group-stage rows.
"""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.core.enums import FlowNodeStatus, StageItemType, StageType
from shared.services.flow_queries import stage_node_status

BRACKET_STAGE_TYPES = (
    StageType.SINGLE_ELIMINATION,
    StageType.DOUBLE_ELIMINATION,
)
GROUP_STAGE_TYPES = (
    StageType.ROUND_ROBIN,
    StageType.SWISS,
)


def join_bracket_context(query: sa.Select, *, encounter=models.Encounter) -> sa.Select:
    """Left-join an encounter's bracket coordinate, stage and stage item.

    The match layer owns no tournament structure: where an encounter sits is
    ``tournament.bracket_encounter``, and an encounter with no row (a scrim)
    simply has no stage and no round.
    """
    return (
        query.outerjoin(models.BracketEncounter, models.BracketEncounter.encounter_id == encounter.id)
        .outerjoin(models.Stage, models.Stage.id == models.BracketEncounter.stage_id)
        .outerjoin(models.StageItem, models.StageItem.id == models.BracketEncounter.stage_item_id)
    )


def encounter_is_lower_bracket(
    *,
    bracket=models.BracketEncounter,
    stage=models.Stage,
    stage_item=models.StageItem,
) -> sa.ColumnElement[bool]:
    return sa.and_(
        stage.stage_type == StageType.DOUBLE_ELIMINATION,
        sa.or_(
            stage_item.type == StageItemType.BRACKET_LOWER,
            bracket.round < 0,
        ),
    )


def encounter_is_upper_bracket(
    *,
    bracket=models.BracketEncounter,
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
                bracket.round > 0,
            ),
        ),
    )


def encounter_is_bracket(
    *,
    bracket=models.BracketEncounter,
    stage=models.Stage,
    stage_item=models.StageItem,
) -> sa.ColumnElement[bool]:
    return sa.or_(
        encounter_is_upper_bracket(
            bracket=bracket,
            stage=stage,
            stage_item=stage_item,
        ),
        encounter_is_lower_bracket(
            bracket=bracket,
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
    """The row's stage has finished (its flow node is ``completed``, moved by the standings worker).

    A row with no stage at all (legacy, pre-stage-system data) passes: those
    tournaments were imported finished, and dropping them here would revoke
    achievements nobody could ever re-earn.
    """
    return sa.or_(stage.id.is_(None), stage_node_status(stage.id) == FlowNodeStatus.COMPLETED)
