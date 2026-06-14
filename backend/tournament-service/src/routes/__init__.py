from fastapi import APIRouter

from src.routes.admin import admin_router
from src.routes.captain import router as captain_router
from src.routes.division_grid import router as division_grid_router
from src.routes.encounter import router as encounter_router
from src.routes.match import router as match_router
from src.routes.registration import router as registration_router
from src.routes.team import router as team_router
from src.routes.tournament import router as tournament_router

router = APIRouter()
router.include_router(tournament_router)
router.include_router(encounter_router)
router.include_router(match_router)
router.include_router(team_router)
router.include_router(captain_router)
router.include_router(admin_router)
router.include_router(registration_router)
router.include_router(division_grid_router)
