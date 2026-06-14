"""Admin routes for user and identity CRUD operations"""

from fastapi import APIRouter, Depends, Request, UploadFile
from shared.clients.s3 import S3Client, upload_avatar
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db, pagination
from src.schemas.admin import user as admin_schemas
from src.schemas.admin import user_merge as merge_schemas
from src.services.admin import user as admin_service
from src.services.admin import user_merge as merge_service
from src.services.user import flows as user_flows


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3

router = APIRouter(
    prefix="/users",
    tags=["admin", "users"],
)


# ─── User CRUD ───────────────────────────────────────────────────────────────


@router.get("", response_model=pagination.Paginated[schemas.UserRead])
async def get_users(
    params: admin_schemas.UserListQueryParams = Depends(),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "read")),
):
    """Get paginated list of users (admin only)"""
    users_list = await admin_service.get_users(
        session,
        admin_schemas.UserListParams.from_query_params(params),
    )
    return users_list


@router.post("", response_model=schemas.UserRead)
async def create_user(
    data: admin_schemas.UserCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "create")),
):
    """Create a new user (admin only)"""
    created_user = await admin_service.create_user(session, data)
    return await user_flows.to_pydantic(
        session, created_user, ["discord", "battle_tag", "twitch"]
    )


@router.patch("/{user_id}", response_model=schemas.UserRead)
async def update_user(
    user_id: int,
    data: admin_schemas.UserUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    auth_user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Update user fields (admin only)"""
    updated_user = await admin_service.update_user(session, user_id, data)
    return await user_flows.to_pydantic(
        session, updated_user, ["discord", "battle_tag", "twitch"]
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "delete")),
):
    """Delete user and all identities (admin only)"""
    await admin_service.delete_user(session, user_id)


@router.post("/merge/preview", response_model=merge_schemas.UserMergePreviewResponse)
async def preview_user_merge(
    data: merge_schemas.UserMergePreviewRequest,
    session: AsyncSession = Depends(db.get_async_session),
    auth_user: models.AuthUser = Depends(auth.get_current_superuser),
):
    """Preview a source -> target player profile merge (superuser only)."""
    return await merge_service.preview_merge(session, data)


@router.post("/merge/execute", response_model=merge_schemas.UserMergeExecuteResponse)
async def execute_user_merge(
    data: merge_schemas.UserMergeExecuteRequest,
    session: AsyncSession = Depends(db.get_async_session),
    auth_user: models.AuthUser = Depends(auth.get_current_superuser),
):
    """Execute a source -> target player profile merge (superuser only)."""
    return await merge_service.execute_merge(
        session,
        data,
        operator_auth_user_id=auth_user.id,
    )


# ─── Discord Identity Management ─────────────────────────────────────────────


@router.post("/{user_id}/discord", response_model=schemas.UserDiscordRead)
async def add_discord_identity(
    user_id: int,
    data: admin_schemas.DiscordIdentityCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Add Discord identity to user (admin only)"""
    identity = await admin_service.add_discord_identity(session, user_id, data)
    return schemas.UserDiscordRead.model_validate(identity, from_attributes=True)


@router.patch("/{user_id}/discord/{identity_id}", response_model=schemas.UserDiscordRead)
async def update_discord_identity(
    user_id: int,
    identity_id: int,
    data: admin_schemas.DiscordIdentityUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Update Discord identity (admin only)"""
    identity = await admin_service.update_discord_identity(session, user_id, identity_id, data)
    return schemas.UserDiscordRead.model_validate(identity, from_attributes=True)


@router.delete("/{user_id}/discord/{identity_id}", status_code=204)
async def delete_discord_identity(
    user_id: int,
    identity_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "delete")),
):
    """Delete Discord identity (admin only)"""
    await admin_service.delete_discord_identity(session, user_id, identity_id)


# ─── BattleTag Identity Management ───────────────────────────────────────────


@router.post("/{user_id}/battle-tag", response_model=schemas.UserBattleTagRead)
async def add_battletag_identity(
    user_id: int,
    data: admin_schemas.BattleTagIdentityCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Add BattleTag identity to user (admin only)"""
    identity = await admin_service.add_battletag_identity(session, user_id, data)
    return schemas.UserBattleTagRead.model_validate(identity, from_attributes=True)


@router.patch("/{user_id}/battle-tag/{identity_id}", response_model=schemas.UserBattleTagRead)
async def update_battletag_identity(
    user_id: int,
    identity_id: int,
    data: admin_schemas.BattleTagIdentityUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Update BattleTag identity (admin only)"""
    identity = await admin_service.update_battletag_identity(session, user_id, identity_id, data)
    return schemas.UserBattleTagRead.model_validate(identity, from_attributes=True)


@router.delete("/{user_id}/battle-tag/{identity_id}", status_code=204)
async def delete_battletag_identity(
    user_id: int,
    identity_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "delete")),
):
    """Delete BattleTag identity (admin only)"""
    await admin_service.delete_battletag_identity(session, user_id, identity_id)


# ─── Twitch Identity Management ──────────────────────────────────────────────


@router.post("/{user_id}/twitch", response_model=schemas.UserTwitchRead)
async def add_twitch_identity(
    user_id: int,
    data: admin_schemas.TwitchIdentityCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Add Twitch identity to user (admin only)"""
    identity = await admin_service.add_twitch_identity(session, user_id, data)
    return schemas.UserTwitchRead.model_validate(identity, from_attributes=True)


@router.patch("/{user_id}/twitch/{identity_id}", response_model=schemas.UserTwitchRead)
async def update_twitch_identity(
    user_id: int,
    identity_id: int,
    data: admin_schemas.TwitchIdentityUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "update")),
):
    """Update Twitch identity (admin only)"""
    identity = await admin_service.update_twitch_identity(session, user_id, identity_id, data)
    return schemas.UserTwitchRead.model_validate(identity, from_attributes=True)


@router.delete("/{user_id}/twitch/{identity_id}", status_code=204)
async def delete_twitch_identity(
    user_id: int,
    identity_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_permission("user", "delete")),
):
    """Delete Twitch identity (admin only)"""
    await admin_service.delete_twitch_identity(session, user_id, identity_id)


# ─── Avatar Management ──────────────────────────────────────────────────────


@router.post("/{user_id}/avatar", response_model=schemas.UserRead)
async def upload_user_avatar(
    user_id: int,
    file: UploadFile,
    session: AsyncSession = Depends(db.get_async_session),
    auth_user: models.AuthUser = Depends(auth.require_permission("user", "update")),
    s3: S3Client = Depends(get_s3),
):
    """Upload or replace avatar for a player user (admin only)"""
    player_user = await admin_service.get_user_or_404(session, user_id)
    file_data = await file.read()
    result = await upload_avatar(
        s3,
        entity_type="players",
        entity_id=user_id,
        file_data=file_data,
        content_type=file.content_type or "application/octet-stream",
    )
    if not result.success:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error)

    player_user.avatar_url = result.public_url
    await session.commit()
    player_user = await admin_service.get_user_or_404(session, user_id)
    return await user_flows.to_pydantic(
        session, player_user, ["discord", "battle_tag", "twitch"]
    )


@router.delete("/{user_id}/avatar", response_model=schemas.UserRead)
async def delete_user_avatar(
    user_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    auth_user: models.AuthUser = Depends(auth.require_permission("user", "update")),
    s3: S3Client = Depends(get_s3),
):
    """Delete avatar for a player user (admin only)"""
    player_user = await admin_service.get_user_or_404(session, user_id)
    await s3.delete_prefix(f"avatars/players/{user_id}/")
    player_user.avatar_url = None
    await session.commit()
    player_user = await admin_service.get_user_or_404(session, user_id)
    return await user_flows.to_pydantic(
        session, player_user, ["discord", "battle_tag", "twitch"]
    )
