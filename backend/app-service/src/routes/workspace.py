from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from loguru import logger
from redis.asyncio import Redis
from shared.clients.s3 import S3Client
from shared.clients.s3.upload import upload_avatar
from shared.rbac import assign_workspace_system_role, ensure_workspace_system_roles, get_workspace_system_role
from shared.repository import AuthUserRepository
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, config, db
from src.services.workspace import service as workspace_service


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_auth_user_repo = AuthUserRepository()


def _require_workspace_permission(
    user: models.AuthUser,
    workspace_id: int,
    resource: str,
    action: str,
) -> None:
    if not user.has_workspace_permission(workspace_id, resource, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {resource}.{action} required",
        )


async def _invalidate_auth_rbac_cache(auth_user_id: int) -> None:
    redis = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
    try:
        await redis.delete(f"rbac:user:{auth_user_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to invalidate auth RBAC cache for user {auth_user_id}: {exc}")
    finally:
        await redis.aclose()


async def _workspace_member_payload(
    session: AsyncSession,
    member: models.WorkspaceMember,
) -> schemas.WorkspaceMemberRead:
    auth_user = await _auth_user_repo.get(session, member.auth_user_id)
    roles = await workspace_service.get_member_workspace_roles(
        session,
        member.workspace_id,
        member.auth_user_id,
    )
    return schemas.WorkspaceMemberRead.model_validate(
        {
            "id": member.id,
            "created_at": member.created_at,
            "updated_at": member.updated_at,
            "workspace_id": member.workspace_id,
            "auth_user_id": member.auth_user_id,
            "role": member.role,
            "username": auth_user.username if auth_user else None,
            "email": auth_user.email if auth_user else None,
            "first_name": auth_user.first_name if auth_user else None,
            "last_name": auth_user.last_name if auth_user else None,
            "avatar_url": auth_user.avatar_url if auth_user else None,
            "rbac_roles": roles,
        }
    )


async def _resolve_role_ids(
    session: AsyncSession,
    workspace_id: int,
    *,
    role_ids: list[int] | None,
    legacy_role: str | None,
) -> list[int]:
    await ensure_workspace_system_roles(session, workspace_id)
    if role_ids is not None:
        return role_ids

    role_name = legacy_role or "member"
    role = await get_workspace_system_role(session, workspace_id, role_name)
    if role is None:
        raise HTTPException(status_code=500, detail="Workspace system role is not configured")
    return [role.id]


@router.get("", response_model=list[schemas.WorkspaceRead])
async def get_all_workspaces(
    session: AsyncSession = Depends(db.get_async_session),
):
    workspaces = await workspace_service.get_all(session)
    return [schemas.WorkspaceRead.model_validate(w, from_attributes=True) for w in workspaces]


@router.get("/{workspace_id}", response_model=schemas.WorkspaceRead)
async def get_workspace(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)


@router.post("", response_model=schemas.WorkspaceRead, status_code=201)
async def create_workspace(
    data: schemas.WorkspaceCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_superuser),
):
    existing = await workspace_service.get_by_slug(session, data.slug)
    if existing:
        raise HTTPException(status_code=400, detail="Workspace with this slug already exists")

    workspace = await workspace_service.create(session, **data.model_dump())
    await ensure_workspace_system_roles(session, workspace.id)
    await workspace_service.add_member(session, workspace.id, user.id, role="owner")
    await assign_workspace_system_role(
        session,
        user_id=user.id,
        workspace_id=workspace.id,
        role_name="owner",
    )
    await session.commit()
    await _invalidate_auth_rbac_cache(user.id)
    return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)


@router.patch("/{workspace_id}", response_model=schemas.WorkspaceRead)
async def update_workspace(
    workspace_id: int,
    data: schemas.WorkspaceUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    _require_workspace_permission(user, workspace_id, "workspace", "update")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    update_data = data.model_dump(exclude_unset=True)
    workspace = await workspace_service.update(session, workspace, update_data)
    await session.commit()
    return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    _require_workspace_permission(user, workspace_id, "workspace", "delete")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    await workspace_service.delete(session, workspace)
    await session.commit()


@router.post("/{workspace_id}/icon", response_model=schemas.WorkspaceRead)
async def upload_workspace_icon(
    workspace_id: int,
    file: UploadFile,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
    s3: S3Client = Depends(get_s3),
):
    _require_workspace_permission(user, workspace_id, "workspace", "update")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    file_data = await file.read()
    content_type = file.content_type or "application/octet-stream"

    result = await upload_avatar(
        s3,
        entity_type="workspaces",
        entity_id=workspace_id,
        file_data=file_data,
        content_type=content_type,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    workspace = await workspace_service.update(session, workspace, {"icon_url": result.public_url})
    await session.commit()
    return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)


@router.delete("/{workspace_id}/icon", response_model=schemas.WorkspaceRead)
async def delete_workspace_icon(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
    s3: S3Client = Depends(get_s3),
):
    _require_workspace_permission(user, workspace_id, "workspace", "update")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    await s3.delete_prefix(f"avatars/workspaces/{workspace_id}/")
    workspace = await workspace_service.update(session, workspace, {"icon_url": None})
    await session.commit()
    return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)


@router.get("/{workspace_id}/members", response_model=list[schemas.WorkspaceMemberRead])
async def get_workspace_members(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    _require_workspace_permission(user, workspace_id, "workspace_member", "read")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    members = await workspace_service.get_members(session, workspace_id)
    return [await _workspace_member_payload(session, member) for member in members]


@router.post("/{workspace_id}/members", response_model=schemas.WorkspaceMemberRead, status_code=201)
async def add_workspace_member(
    workspace_id: int,
    data: schemas.WorkspaceMemberCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    _require_workspace_permission(user, workspace_id, "workspace_member", "create")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    target_user = await _auth_user_repo.get(session, data.auth_user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="Auth user not found")

    existing = await workspace_service.get_member(session, workspace_id, data.auth_user_id)
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")

    role_ids = await _resolve_role_ids(
        session,
        workspace_id,
        role_ids=data.role_ids,
        legacy_role=data.role,
    )
    try:
        member = await workspace_service.add_member_with_roles(
            session,
            workspace_id,
            data.auth_user_id,
            role_ids=role_ids,
            legacy_role=data.role or "member",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = await _workspace_member_payload(session, member)
    await session.commit()
    await _invalidate_auth_rbac_cache(data.auth_user_id)
    return payload


@router.patch("/{workspace_id}/members/{auth_user_id}", response_model=schemas.WorkspaceMemberRead)
async def update_workspace_member(
    workspace_id: int,
    auth_user_id: int,
    data: schemas.WorkspaceMemberUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    _require_workspace_permission(user, workspace_id, "workspace_member", "update")
    member = await workspace_service.get_member(session, workspace_id, auth_user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if data.role_ids is None and data.role is None:
        raise HTTPException(status_code=400, detail="role_ids or role is required")

    role_ids = await _resolve_role_ids(
        session,
        workspace_id,
        role_ids=data.role_ids,
        legacy_role=data.role,
    )
    try:
        member = await workspace_service.update_member_roles(session, member, role_ids=role_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = await _workspace_member_payload(session, member)
    await session.commit()
    await _invalidate_auth_rbac_cache(auth_user_id)
    return payload


@router.delete("/{workspace_id}/members/{auth_user_id}", status_code=204)
async def remove_workspace_member(
    workspace_id: int,
    auth_user_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    _require_workspace_permission(user, workspace_id, "workspace_member", "delete")
    member = await workspace_service.get_member(session, workspace_id, auth_user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if not await workspace_service.can_remove_member(session, member):
        raise HTTPException(status_code=400, detail="Cannot remove the last workspace owner")

    await workspace_service.remove_member(session, member)
    await session.commit()
    await _invalidate_auth_rbac_cache(auth_user_id)
