from fastapi import APIRouter, Depends

from src.core import auth, db, enums
from src.services.map import flows as map_flows

router = APIRouter(
    prefix="/maps",
    tags=[enums.RouteTag.MAP],
    dependencies=[Depends(auth.require_permission("map", "sync"))],
)


@router.post(path="/update")
async def update_maps(session=Depends(db.get_async_session)):
    await map_flows.initial_create(session)
    return {"success": True}
