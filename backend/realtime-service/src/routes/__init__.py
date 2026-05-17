from fastapi import APIRouter

from src.routes.ws import router as ws_router

router = APIRouter()
router.include_router(ws_router)
