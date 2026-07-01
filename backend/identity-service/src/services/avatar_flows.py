"""RPC-callable avatar flows for the current user (no FastAPI Request/Depends).

Faithful ports of POST/DELETE ``/me/avatar`` in ``src/routes/auth.py``. The
gateway base64-encodes the multipart upload into the RPC body; the handler
decodes it and reuses the shared S3 upload helper. ``fastapi.HTTPException``
remains the error vehicle the RPC envelope maps; a later phase removes it.
"""

from __future__ import annotations

from shared.core.errors import BaseAPIException as HTTPException
from loguru import logger
from shared.clients.s3 import S3Client
from shared.clients.s3.upload import upload_avatar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models


async def _propagate_to_player(session: AsyncSession, auth_user_id: int, avatar_url: str | None) -> None:
    """Mirror the avatar onto the user's linked player (``players.user``)
    so it shows on ``users/[slug]`` (which renders the player, not the auth user)."""
    player = await session.scalar(select(models.User).where(models.User.auth_user_id == auth_user_id))
    if player is not None:
        player.avatar_url = avatar_url


async def set_avatar(
    session: AsyncSession,
    current_user: models.AuthUser,
    s3: S3Client,
    file_data: bytes,
    content_type: str,
) -> models.AuthUser:
    """Upload or replace the current user's avatar image."""
    result = await upload_avatar(
        s3,
        entity_type="users",
        entity_id=current_user.id,
        file_data=file_data,
        content_type=content_type or "application/octet-stream",
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    current_user.avatar_url = result.public_url
    await _propagate_to_player(session, current_user.id, result.public_url)
    await session.commit()
    await session.refresh(current_user)

    logger.bind(user_id=str(current_user.id)).info("Avatar updated")
    return current_user


async def delete_avatar(
    session: AsyncSession,
    current_user: models.AuthUser,
    s3: S3Client,
) -> models.AuthUser:
    """Delete the current user's avatar."""
    await s3.delete_prefix(f"avatars/users/{current_user.id}/")
    current_user.avatar_url = None
    await _propagate_to_player(session, current_user.id, None)
    await session.commit()
    await session.refresh(current_user)

    logger.bind(user_id=str(current_user.id)).info("Avatar deleted")
    return current_user
