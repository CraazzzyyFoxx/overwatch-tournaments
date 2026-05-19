from fastapi import APIRouter

from src.routes.challonge import router as challonge_router
from src.routes.encounter import router as encounter_router
from src.routes.gamemode import router as gamemode_router
from src.routes.hero import router as hero_router
from src.routes.map import router as map_router
from src.routes.match_logs import router as logs_router
from src.routes.match_logs import task_router as logs_task_router
from src.routes.standing import router as standings_router
from src.routes.team import router as team_router
from src.routes.tournament import router as tournament_router
from src.routes.user import router as user_router

from .achievement import router as achievement_router
from .admin import admin_router

router = APIRouter()
router.include_router(tournament_router)
router.include_router(team_router)
router.include_router(encounter_router)
router.include_router(standings_router)
router.include_router(logs_router)
router.include_router(logs_task_router)
router.include_router(challonge_router)
router.include_router(achievement_router)
router.include_router(user_router)
router.include_router(gamemode_router)
router.include_router(hero_router)
router.include_router(map_router)
router.include_router(admin_router)

