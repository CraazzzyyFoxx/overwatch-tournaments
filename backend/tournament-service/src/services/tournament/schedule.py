"""Phase-schedule management for tournaments (full-replace semantics).

The schedule (``tournament_phase_schedule`` rows) is the single home for phase
timings: ``starts_at`` drives the worker tick's forward status transitions and
``ends_at`` closes a phase's action window early. Admins replace the whole
schedule at once via ``rpc.tournament.tournament_schedule_set`` — validation of
allowed phases / ordering lives in ``TournamentScheduleSet``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import TournamentPhaseScheduleRepository, TournamentRepository
from src import models, schemas
from src.services.tournament.events import STRUCTURE_RESOURCES, publish_tournament_invalidation

_TOURNAMENT_LOAD = (
    selectinload(models.Tournament.stages).selectinload(models.Stage.items).selectinload(models.StageItem.inputs),
)


class TournamentScheduleService:
    def __init__(
        self,
        *,
        tournament_repo: TournamentRepository = TournamentRepository(),
        schedule_repo: TournamentPhaseScheduleRepository = TournamentPhaseScheduleRepository(),
    ) -> None:
        self.tournament_repo = tournament_repo
        self.schedule_repo = schedule_repo

    async def set_schedule(
        self,
        session: AsyncSession,
        tournament_id: int,
        entries: list[schemas.TournamentScheduleEntryInput],
    ) -> models.Tournament:
        """Replace the tournament's phase schedule with ``entries`` (full replace)."""
        tournament = await self.tournament_repo.get(session, tournament_id, options=_TOURNAMENT_LOAD)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        await self.schedule_repo.delete_for_tournament(session, tournament_id)
        await self.schedule_repo.create_many(
            session,
            [
                models.TournamentPhaseSchedule(
                    tournament_id=tournament_id,
                    status=entry.status,
                    starts_at=entry.starts_at,
                    ends_at=entry.ends_at,
                )
                for entry in entries
            ],
        )

        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await session.commit()

        # Fresh read (pattern of admin transition_status); populate_existing forces
        # the eager ``phase_schedule`` relationship past the identity-map hit
        # (expire_on_commit=False) so it reflects the new rows.
        refreshed = await self.tournament_repo.get(
            session, tournament_id, options=_TOURNAMENT_LOAD, populate_existing=True
        )
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        return refreshed


schedule_service = TournamentScheduleService()
