"""Admin service for global Settings CRUD (superuser only)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError
from shared.repository import SettingsRepository
from shared.schemas.settings import SETTINGS_SCHEMAS
from shared.services import settings_provider
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import errors

_repo = SettingsRepository()


async def list_settings(session: AsyncSession) -> Sequence[models.Settings]:
    rows, _ = await _repo.list(session)
    return rows


async def get_setting(session: AsyncSession, key: str) -> models.Settings:
    setting = await _repo.get_by_key(session, key)
    if setting is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg=f"Setting '{key}' not found")],
        )
    return setting


def _validate_value(key: str, value: dict) -> None:
    model = SETTINGS_SCHEMAS.get(key)
    if model is None:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="unknown_setting", msg=f"Unknown settings key '{key}'")],
        )
    try:
        model.model_validate(value)
    except ValidationError as exc:
        raise errors.ApiHTTPException(
            status_code=422,
            detail=[errors.ApiExc(code="invalid_setting", msg=str(exc))],
        )


async def upsert_setting(
    session: AsyncSession,
    key: str,
    value: dict,
    *,
    description: str | None,
    updated_by: int | None,
) -> models.Settings:
    """Validate against the per-key schema, persist, and invalidate the cache."""
    _validate_value(key, value)
    setting = await _repo.upsert(
        session, key, value, description=description, updated_by=updated_by
    )
    await session.commit()
    await settings_provider.invalidate_setting(key)
    return setting
