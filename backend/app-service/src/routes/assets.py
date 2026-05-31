from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from shared.clients.s3 import S3Client
from shared.clients.s3.upload import upload_asset
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db


router = APIRouter(prefix="/assets", tags=["assets"])


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


async def _resolve_workspace_slug(
    session: AsyncSession,
    workspace_id: int | None,
) -> str | None:
    if workspace_id is None:
        return None
    ws = await session.get(models.Workspace, workspace_id)
    return ws.slug if ws else None


@router.post("/{asset_type}/{slug}")
async def upload_asset_file(
    asset_type: Literal["achievements", "divisions"],
    slug: str,
    file: UploadFile,
    workspace_id: int | None = Query(default=None),
    user: models.AuthUser = Depends(auth.get_current_superuser),
    s3: S3Client = Depends(get_s3),
    session: AsyncSession = Depends(db.get_async_session),
):
    """Upload a static asset image (achievement icon or division image)."""
    file_data = await file.read()
    content_type = file.content_type or "application/octet-stream"
    workspace_slug = await _resolve_workspace_slug(session, workspace_id)

    result = await upload_asset(
        s3,
        asset_type=asset_type,
        slug=slug,
        file_data=file_data,
        content_type=content_type,
        workspace_slug=workspace_slug,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return {"key": result.key, "public_url": result.public_url}


@router.delete("/{asset_type}/{slug}")
async def delete_asset_file(
    asset_type: Literal["achievements", "divisions"],
    slug: str,
    workspace_id: int | None = Query(default=None),
    user: models.AuthUser = Depends(auth.get_current_superuser),
    s3: S3Client = Depends(get_s3),
    session: AsyncSession = Depends(db.get_async_session),
):
    """Delete a static asset image."""
    workspace_slug = await _resolve_workspace_slug(session, workspace_id)
    if workspace_slug:
        prefix = f"assets/{asset_type}/{workspace_slug}/{slug}."
    else:
        prefix = f"assets/{asset_type}/{slug}."
    deleted = await s3.delete_prefix(prefix)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"deleted": deleted}
