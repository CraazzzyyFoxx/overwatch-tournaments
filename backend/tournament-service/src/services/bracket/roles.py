"""Match roles that can be read from the persisted bracket graph."""

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from shared.models.tournament.encounter_link import EncounterLink


def third_place_condition(
    encounter_id: sa.SQLColumnExpression[int], round_number: sa.SQLColumnExpression[int]
) -> sa.ColumnElement[bool]:
    """A positive-round card fed only by losing places, including imported brackets."""
    link = aliased(EncounterLink)
    return (round_number > 0) & (
        sa.select(1)
        .select_from(link)
        .where(link.target_encounter_id == encounter_id)
        .group_by(link.target_encounter_id)
        .having(sa.func.min(link.source_position) > 1)
        .correlate_except(link)
        .exists()
    )
