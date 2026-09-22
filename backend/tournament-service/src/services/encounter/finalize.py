"""tournament-service binding of the shared finalization primitive.

The logic lives in :mod:`shared.services.encounter.finalize` so parser-service
runs the identical code path (previously a drifted copy of it). This module
only supplies the pieces that cannot live in ``shared``: veto-session upkeep,
which registers realtime updates through tournament-service-local plumbing, and
the lifecycle notification for a slot the bracket just filled in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import EncounterResultStatus, EncounterStatus
from shared.services.encounter.finalize import (
    FinalizedEncounterScore,
    FinalizeSource,
)
from shared.services.encounter.finalize import (
    finalize_encounter_score as _finalize_encounter_score,
)
from src import models
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.notifications.lifecycle import lifecycle_notifier

__all__ = (
    "FinalizeSource",
    "FinalizedEncounterScore",
    "FinalizeService",
    "finalize_service",
)


class FinalizeService:
    """tournament-service's binding of the shared finalization primitive.

    The only local ingredients are the two things that must happen to an
    encounter the bracket just filled in: veto-session upkeep, which registers
    realtime updates through tournament-service-local plumbing, and the
    "your match is scheduled" notification -- advancement is the path where an
    already-scheduled slot finally learns who plays in it.
    """

    async def _post_advance(self, session: AsyncSession, encounter: models.Encounter) -> None:
        await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, encounter)
        await lifecycle_notifier.on_encounter_changed(session, encounter)

    async def finalize_encounter_score(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        home_score: int,
        away_score: int,
        source: FinalizeSource,
        encounter: models.Encounter | None = None,
        status: EncounterStatus = EncounterStatus.COMPLETED,
        result_status: EncounterResultStatus | None = None,
        confirmed_at: datetime | None = None,
    ) -> FinalizedEncounterScore:
        """Finalize an encounter score, keeping affected map/hero pick-ban
        sessions in sync.

        See :func:`shared.services.encounter.finalize.finalize_encounter_score` for
        the semantics; the caller still owns commit/publish.
        """
        return await _finalize_encounter_score(
            session,
            encounter_id,
            home_score=home_score,
            away_score=away_score,
            source=source,
            encounter=encounter,
            status=status,
            result_status=result_status,
            confirmed_at=confirmed_at,
            post_advance=self._post_advance,
        )


finalize_service = FinalizeService()
