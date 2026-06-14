from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import auth, db, enums
from src.services.encounter import flows as encounter_flows

router = APIRouter(
    prefix="/encounter",
    tags=[enums.RouteTag.ENCOUNTER],
    dependencies=[Depends(auth.require_role("admin"))],
)


@router.post(path="/bulk")
async def bulk_create_from_challonge(
    session: AsyncSession = Depends(db.get_async_session),
):
    return await encounter_flows.bulk_create_for_from_challonge(session)


@router.post(path="/challonge")
async def create_from_challonge(
    tournament_id: int,
    skip_finals: bool = False,  # Thanks 4 tournament
    session: AsyncSession = Depends(db.get_async_session),
):
    return await encounter_flows.bulk_create_for_tournament_from_challonge(
        session,
        tournament_id,
        skip_finals=skip_finals,
    )
