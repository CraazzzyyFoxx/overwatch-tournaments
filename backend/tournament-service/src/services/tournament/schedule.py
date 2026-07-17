"""Phase-schedule management for tournaments (full-replace semantics).

The schedule (``tournament_phase_schedule`` rows) is the single home for phase
timings: ``starts_at`` drives the worker tick's forward status transitions and
``ends_at`` closes a phase's action window early. Admins replace the whole
schedule at once via ``rpc.tournament.tournament_schedule_set`` — validation of
allowed phases / ordering lives in ``TournamentScheduleSet``.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.schemas.admin import tournament as admin_schemas
from src.services.tournament.events import enqueue_tournament_changed


async def set_schedule(
    session: AsyncSession,
    tournament_id: int,
    entries: list[admin_schemas.TournamentScheduleEntryInput],
) -> models.Tournament:
    """Replace the tournament's phase schedule with ``entries`` (full replace)."""
    result = await session.execute(
        select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
    )
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    await session.execute(
        delete(models.TournamentPhaseSchedule).where(
            models.TournamentPhaseSchedule.tournament_id == tournament_id
        )
    )
    session.add_all(
        models.TournamentPhaseSchedule(
            tournament_id=tournament_id,
            status=entry.status,
            starts_at=entry.starts_at,
            ends_at=entry.ends_at,
        )
        for entry in entries
    )

    await enqueue_tournament_changed(session, tournament_id, "structure_changed")
    await session.commit()

    # Fresh read (pattern of admin transition_status); populate_existing forces
    # the eager ``phase_schedule`` relationship past the identity-map hit
    # (expire_on_commit=False) so it reflects the new rows.
    result = await session.execute(
        select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()
