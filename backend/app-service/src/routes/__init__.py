from fastapi import APIRouter

from src.routes.achievements import router as achievements_router
from src.routes.assets import router as assets_router
from src.routes.gamemode import router as gamemode_router
from src.routes.hero import router as hero_router
from src.routes.map import router as map_router
from src.routes.match import router as match_router
from src.routes.statistics import router as statistics_router
from src.routes.user import router as user_router
from src.routes.workspace import router as workspace_router

# Tournament-flow routes (tournament, encounter, match, team, registration,
# division_grid) moved to tournament-service. The gateway routes /api/v1/* paths
# for those resources to tournament-service. See P3-A spec:
# backend/docs/architecture/specs/2026-05-24-p3a-tournament-flow-extraction-design.md
router = APIRouter()
router.include_router(workspace_router)
router.include_router(assets_router)
router.include_router(user_router)
router.include_router(statistics_router)
router.include_router(hero_router)
router.include_router(gamemode_router)
router.include_router(map_router)
router.include_router(match_router)
router.include_router(achievements_router)
