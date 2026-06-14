from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from shared.core.enums import EncounterResultStatus, EncounterStatus
from shared.services.bracket import advancement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

FinalizeSource = Literal["captain", "admin", "challonge", "log"]


@dataclass(frozen=True)
class FinalizedEncounterScore:
    encounter: models.Encounter
    advanced_encounters: Sequence[models.Encounter]


async def finalize_encounter_score(
    session: AsyncSession,
    encounter_id: int,
    *,
    home_score: int,
    away_score: int,
    source: FinalizeSource,
    encounter: models.Encounter | None = None,
    status: EncounterStatus = EncounterStatus.COMPLETED,
    result_status: EncounterResultStatus | None = None,
    confirmed_by_id: int | None = None,
    confirmed_at: datetime | None = None,
) -> FinalizedEncounterScore:
    """Finalize an encounter score and propagate bracket advancement.

    The caller owns commit/publish boundaries. This keeps the source encounter
    update and all target-slot updates in the caller's existing transaction.
    """
    del source

    locked_encounter = encounter or await _load_encounter_for_update(session, encounter_id)
    if locked_encounter.id != encounter_id:
        raise ValueError(
            f"Encounter id mismatch: expected {encounter_id}, got {locked_encounter.id}"
        )

    locked_encounter.home_score = home_score
    locked_encounter.away_score = away_score
    locked_encounter.status = status

    if result_status is not None:
        locked_encounter.result_status = result_status

    if confirmed_by_id is not None or confirmed_at is not None:
        locked_encounter.confirmed_by_id = confirmed_by_id
        locked_encounter.confirmed_at = confirmed_at or datetime.now(UTC)

    advanced_encounters = await advancement.advance_winner(session, locked_encounter)
    return FinalizedEncounterScore(
        encounter=locked_encounter,
        advanced_encounters=advanced_encounters,
    )


async def _load_encounter_for_update(
    session: AsyncSession,
    encounter_id: int,
) -> models.Encounter:
    result = await session.execute(
        select(models.Encounter)
        .where(models.Encounter.id == encounter_id)
        .with_for_update(nowait=False)
    )
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise ValueError(f"Encounter {encounter_id} not found")
    return encounter
