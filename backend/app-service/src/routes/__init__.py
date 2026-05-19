from fastapi import APIRouter

from src.routes.achievements import router as achievements_router
from src.routes.encounter import router as encounter_router
from src.routes.match import router as match_router
from src.routes.gamemode import router as gamemode_router
from src.routes.hero import router as hero_router
from src.routes.map import router as map_router
from src.routes.statistics import router as statistics_router
from src.routes.team import router as team_router
from src.routes.tournament import router as tournament_router
from src.routes.user import router as user_router
from src.routes.utils import router as utils_router
from src.routes.division_grid import router as division_grid_router
from src.routes.workspace import router as workspace_router
from src.routes.assets import router as assets_router
from src.routes.registration import router as registration_router

router = APIRouter()
router.include_router(workspace_router)
router.include_router(division_grid_router)
router.include_router(assets_router)
router.include_router(registration_router)
router.include_router(user_router)
router.include_router(tournament_router)
router.include_router(team_router)
router.include_router(encounter_router)
router.include_router(match_router)
router.include_router(statistics_router)
router.include_router(hero_router)
router.include_router(gamemode_router)
router.include_router(map_router)
router.include_router(achievements_router)
router.include_router(utils_router)
