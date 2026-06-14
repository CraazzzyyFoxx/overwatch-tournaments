from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import db
from src.services import api_key_service, auth_service

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


@router.get("", response_model=list[schemas.ApiKeyRead])
async def list_api_keys(
    workspace_id: Annotated[int, Query(gt=0)],
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
) -> list[schemas.ApiKeyRead]:
    return await api_key_service.list_api_keys(session, user=current_user, workspace_id=workspace_id)


@router.post("", response_model=schemas.ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: schemas.ApiKeyCreate,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
) -> schemas.ApiKeyCreateResponse:
    return await api_key_service.create_api_key(session, user=current_user, payload=payload)


@router.patch("/{api_key_id}", response_model=schemas.ApiKeyRead)
async def update_api_key(
    api_key_id: int,
    payload: schemas.ApiKeyUpdate,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
) -> schemas.ApiKeyRead:
    return await api_key_service.update_api_key(session, user=current_user, api_key_id=api_key_id, payload=payload)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: int,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
) -> None:
    await api_key_service.revoke_api_key(session, user=current_user, api_key_id=api_key_id)
