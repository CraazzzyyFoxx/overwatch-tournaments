from fastapi import APIRouter, Depends
from sqlalchemy import select

from src import models
from src.core import auth, db, enums
from src.services.standings import recalculation

router = APIRouter(
    prefix="/standing",
    tags=[enums.RouteTag.STANDINGS],
    dependencies=[Depends(auth.require_role("admin"))],
)


@router.post(path="/create", status_code=202)
async def create_from_tournament(
    tournament_id: int,
    rewrite: bool = False,
    session=Depends(db.get_async_session),
):
    del rewrite, session
    await recalculation.enqueue_tournament_recalculation(tournament_id)
    return {"scheduled": True, "tournament_id": tournament_id}


@router.post(path="/create/bulk", status_code=202)
async def bulk_create_from_tournament(session=Depends(db.get_async_session)):
    tournament_ids = list(await session.scalars(select(models.Tournament.id)))
    for tournament_id in tournament_ids:
        await recalculation.enqueue_tournament_recalculation(tournament_id)
    return {"scheduled": len(tournament_ids)}
