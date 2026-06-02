"""Admin routes for global Settings (superuser only)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin import settings as admin_schemas
from src.services.admin import settings as admin_service

router = APIRouter(
    prefix="/settings",
    tags=["admin", "settings"],
)


@router.get("", response_model=list[admin_schemas.SettingRead])
async def list_settings(
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_superuser),
):
    """List all global settings (superuser only)."""
    rows = await admin_service.list_settings(session)
    return [admin_schemas.SettingRead.model_validate(row) for row in rows]


@router.get("/{key}", response_model=admin_schemas.SettingRead)
async def get_setting(
    key: str,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_superuser),
):
    """Fetch one settings key (superuser only)."""
    setting = await admin_service.get_setting(session, key)
    return admin_schemas.SettingRead.model_validate(setting)


@router.put("/{key}", response_model=admin_schemas.SettingRead)
async def upsert_setting(
    key: str,
    data: admin_schemas.SettingUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_superuser),
):
    """Create or replace a settings key's value (superuser only).

    The value is validated against the per-key schema before persisting.
    """
    setting = await admin_service.upsert_setting(
        session,
        key,
        data.value,
        description=data.description,
        updated_by=user.id,
    )
    return admin_schemas.SettingRead.model_validate(setting)
