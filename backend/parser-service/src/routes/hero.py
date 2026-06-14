from fastapi import APIRouter, Depends

from src.core import auth, db, enums
from src.services.hero import flows as hero_flows

router = APIRouter(
    prefix="/heroes",
    tags=[enums.RouteTag.HERO],
    dependencies=[Depends(auth.require_permission("hero", "sync"))],
)


@router.post(path="/update")
async def update_heroes(session=Depends(db.get_async_session)):
    await hero_flows.initial_create(session)
    return {"success": True}
