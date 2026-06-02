"""Admin routes for OverFast rank collection: status + manual trigger."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import auth, db
from src.schemas.admin import rank_collection as schemas
from src.services.overwatch_rank import admin as rank_admin

router = APIRouter(
    prefix="/rank",
    tags=["admin", "rank"],
    dependencies=[Depends(auth.require_role("admin"))],
)


@router.get("/users/{user_id}/collection", response_model=list[schemas.CollectionStatusRead])
async def get_collection_status(
    user_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    """Per-battle-tag collection status/history for a user (admin only)."""
    rows = await rank_admin.get_user_collection_status(session, user_id)
    return [schemas.CollectionStatusRead(**row) for row in rows]


@router.post("/collect", response_model=schemas.CollectTriggerResponse)
async def trigger_collection(
    data: schemas.CollectTriggerRequest,
    session: AsyncSession = Depends(db.get_async_session),
):
    """Force a rank fetch for a user's tags (all) or specific battle tags."""
    enqueued = await rank_admin.trigger_collection(
        session,
        user_id=data.user_id,
        battle_tag_ids=data.battle_tag_ids,
    )
    return schemas.CollectTriggerResponse(enqueued=enqueued)
