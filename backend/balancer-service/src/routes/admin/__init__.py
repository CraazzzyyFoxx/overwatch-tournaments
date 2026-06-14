from fastapi import APIRouter

from src.routes.admin.balancer import router as balancer_router
from src.routes.admin.draft import router as draft_router

router = APIRouter()
router.include_router(balancer_router)
router.include_router(draft_router)
