from fastapi import APIRouter

from src.routes.analytics import router as analytics_router
from src.routes.analytics_read import router as analytics_read_router
from src.routes.v2 import router as v2_router

router = APIRouter()
router.include_router(analytics_router)
router.include_router(analytics_read_router)
router.include_router(v2_router)
