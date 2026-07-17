from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status
from shared.core.enums import EncounterResultStatus, EncounterStatus, StageType
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.bracket import advancement
from src import models

FinalizeSource = Literal["captain", "admin", "challonge", "log"]

# Stage types where a match MUST produce a winner: a drawn score would leave
# the advancement edges unfired and the bracket silently stuck.
_NO_DRAW_STAGE_TYPES = {StageType.SINGLE_ELIMINATION, StageType.DOUBLE_ELIMINATION}


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
        raise ValueError(f"Encounter id mismatch: expected {encounter_id}, got {locked_encounter.id}")

    if home_score == away_score and status == EncounterStatus.COMPLETED:
        stage_type = await _load_stage_type(session, locked_encounter.stage_id)
        if stage_type in _NO_DRAW_STAGE_TYPES:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    "An elimination-bracket match cannot be completed with a drawn score — "
                    "a winner is required to advance the bracket"
                ),
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
        select(models.Encounter).where(models.Encounter.id == encounter_id).with_for_update(nowait=False)
    )
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise ValueError(f"Encounter {encounter_id} not found")
    return encounter


async def _load_stage_type(
    session: AsyncSession,
    stage_id: int | None,
) -> StageType | None:
    if stage_id is None:
        return None
    return await session.scalar(select(models.Stage.stage_type).where(models.Stage.id == stage_id))
