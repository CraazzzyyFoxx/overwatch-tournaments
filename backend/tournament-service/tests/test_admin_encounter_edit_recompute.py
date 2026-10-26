"""An admin encounter edit asks for a standings recompute only when it moves
something standings are computed from: the status, the bracket coordinate or
the series length. Observed on the durable request counter
(``tournament.recalculation_state.requested_generation``) on the test Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from shared.models.tournament.computation import TournamentRecalculationState
from src import schemas
from src.services.admin.encounter import encounter_service
from tests._encounter_layer import EncounterLayerCase


class EncounterEditRecomputeTests(EncounterLayerCase):
    async def _requested(self) -> int:
        async with self.Session() as s:
            generation = await s.scalar(
                sa.select(TournamentRecalculationState.requested_generation).where(
                    TournamentRecalculationState.tournament_id == self.tournament_id
                )
            )
        return generation or 0

    async def _edit(self, encounter_id: int, **fields) -> None:  # noqa: ANN003
        async with self.Session() as s:
            await encounter_service.update_encounter(s, encounter_id, schemas.EncounterUpdate(**fields))

    async def test_a_rename_or_a_reschedule_asks_for_nothing(self) -> None:
        encounter_id = await self.encounter(0, 1, best_of=3)
        before = await self._requested()

        await self._edit(encounter_id, name="Grand final")
        await self._edit(encounter_id, scheduled_at=datetime(2030, 1, 1, 18, tzinfo=UTC))

        self.assertEqual(before, await self._requested())

    async def test_resending_the_current_values_asks_for_nothing(self) -> None:
        """The admin form posts every field."""
        encounter_id = await self.encounter(0, 1, best_of=3)
        before = await self._requested()

        await self._edit(encounter_id, name="E", best_of=3, round=1, stage_id=self.stage_id)

        self.assertEqual(before, await self._requested())

    async def test_a_series_length_or_round_change_asks_once_each(self) -> None:
        encounter_id = await self.encounter(0, 1, best_of=3)
        before = await self._requested()

        await self._edit(encounter_id, best_of=5)
        self.assertEqual(before + 1, await self._requested())

        await self._edit(encounter_id, round=2)
        self.assertEqual(before + 2, await self._requested())
