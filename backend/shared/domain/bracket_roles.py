"""Match roles that can be read from the persisted bracket graph."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.models.tournament.bracket_encounter import BracketEncounter
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


async def is_third_place(session: AsyncSession, encounter_id: int) -> bool:
    """Whether this encounter is a bracket's bronze card; ``False`` without a bracket position (scrim, mix)."""
    return bool(
        await session.scalar(
            sa.select(third_place_condition(BracketEncounter.encounter_id, BracketEncounter.round)).where(
                BracketEncounter.encounter_id == encounter_id
            )
        )
    )
