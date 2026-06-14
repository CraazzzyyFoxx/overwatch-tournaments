from fastapi import APIRouter, Depends

from src.core import auth, db, enums
from src.services.gamemode import flows as gamemode_flows

router = APIRouter(
    prefix="/gamemodes",
    tags=[enums.RouteTag.GAMEMODE],
    dependencies=[Depends(auth.require_permission("gamemode", "sync"))],
)


@router.post(path="/update")
async def update_gamemodes(session=Depends(db.get_async_session)):
    await gamemode_flows.initial_create(session)
    return {"success": True}
