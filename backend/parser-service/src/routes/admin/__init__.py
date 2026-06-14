from fastapi import APIRouter, Depends

from src.core import auth

from .achievement_rule import library_router as achievement_library_router
from .achievement_rule import override_router as achievement_override_router
from .achievement_rule import router as achievement_rule_router
from .discord_channel import router as discord_channel_router
from .gamemode import router as gamemode_router
from .hero import router as hero_router
from .logs import router as logs_router
from .map import router as map_router
from .rank_collection import router as rank_collection_router
from .settings import router as settings_router
from .team import player_router
from .user import router as user_router

# Admin router - aggregates admin CRUD endpoints.

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)

admin_router.include_router(player_router)
admin_router.include_router(user_router)
admin_router.include_router(hero_router)
admin_router.include_router(gamemode_router)
admin_router.include_router(map_router)
admin_router.include_router(logs_router)
admin_router.include_router(achievement_rule_router)
admin_router.include_router(achievement_library_router)
admin_router.include_router(achievement_override_router)
admin_router.include_router(settings_router)
admin_router.include_router(rank_collection_router)
admin_router.include_router(discord_channel_router)
