import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin.computation import TournamentComputationJobRead
from src.services.computation import jobs

router = APIRouter(
    prefix="/tournament-jobs",
    tags=["admin", "tournament-jobs"],
)


@router.get("/{job_id}", response_model=TournamentComputationJobRead)
async def get_tournament_job(
    job_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
) -> models.TournamentComputationJob:
    job = await jobs.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament job not found")
    await auth.require_tournament_id_permission(
        session,
        user,
        tournament_id=job.tournament_id,
        resource="standing" if job.kind == "standings" else "stage",
        action="recalculate" if job.kind == "standings" else "update",
    )
    return job


@router.get("", response_model=list[TournamentComputationJobRead])
async def list_tournament_jobs(
    tournament_id: int | None = None,
    stage_id: int | None = None,
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
) -> list[models.TournamentComputationJob]:
    scoped_tournament_id = tournament_id
    if scoped_tournament_id is None and stage_id is not None:
        scoped_tournament_id = await session.scalar(
            sa.select(models.Stage.tournament_id).where(models.Stage.id == stage_id)
        )
        if scoped_tournament_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    if scoped_tournament_id is None and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tournament_id or stage_id is required",
        )
    if scoped_tournament_id is not None:
        await auth.require_tournament_id_permission(
            session,
            user,
            tournament_id=scoped_tournament_id,
            resource="stage",
            action="read",
        )
    return await jobs.list_jobs(
        session,
        tournament_id=scoped_tournament_id,
        stage_id=stage_id,
        active_only=active_only,
        limit=limit,
    )
