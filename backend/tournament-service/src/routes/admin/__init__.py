from fastapi import APIRouter, Depends

from src.core import auth

from .challonge import router as challonge_router
from .encounter import router as encounter_router
from .player_sub_role import router as player_sub_role_router
from .registration import router as registration_router
from .registration_sheet import router as registration_sheet_router
from .registration_status import router as registration_status_router
from .stage import router as stage_router
from .standing import router as standing_router
from .team import player_router
from .team import router as team_router
from .tournament import router as tournament_router

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)

admin_router.include_router(tournament_router)
admin_router.include_router(stage_router)
admin_router.include_router(team_router)
admin_router.include_router(player_router)
admin_router.include_router(encounter_router)
admin_router.include_router(standing_router)
admin_router.include_router(player_sub_role_router)
admin_router.include_router(challonge_router)
admin_router.include_router(registration_router)
admin_router.include_router(registration_status_router)
admin_router.include_router(registration_sheet_router)
