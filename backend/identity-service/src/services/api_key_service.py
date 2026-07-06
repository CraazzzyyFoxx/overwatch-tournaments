from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rbac import legacy_workspace_role_name_for_user
from shared.repository import ApiKeyRepository, WorkspaceMemberRepository, WorkspaceRepository
from src import models, schemas
from src.core import key_derivation
from src.core.config import settings
from src.services.auth_service import AuthService

# Domain-separated subkey for hashing API-key secrets (never the raw JWT secret).
_API_KEY_SECRET_KEY = key_derivation.api_key_secret_key(settings.JWT_SECRET_KEY)

API_KEY_PREFIX = "aqt_sk"
DEFAULT_API_KEY_SCOPES = ["balancer.jobs"]
DEFAULT_API_KEY_LIMITS: dict[str, int] = {
    "requests_per_minute": 60,
    "jobs_per_day": 100,
    "concurrent_jobs": 2,
    "max_upload_bytes": 10 * 1024 * 1024,
    "max_players": 500,
}
DEFAULT_API_KEY_CONFIG_POLICY: dict[str, Any] = {
    "allowed_keys": [
        "algorithm",
        "role_mask",
        "population_size",
        "generation_count",
        "use_captains",
        "max_result_variants",
    ],
    "allowed_algorithms": ["moo"],
    "max_values": {
        "population_size": 150,
        "generation_count": 500,
        "max_result_variants": 10,
    },
}

_api_key_repo = ApiKeyRepository()
_workspace_member_repo = WorkspaceMemberRepository()
_workspace_repo = WorkspaceRepository()


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_secret(secret: str) -> str:
    """Hash an API-key secret for storage (domain-separated subkey, new writes)."""
    return key_derivation.hmac_sha256_hex(_API_KEY_SECRET_KEY, secret)


def _verify_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time verify against the derived hash, then the legacy raw-secret
    hash — so API keys created before domain separation keep validating without
    a re-issue. New keys are always stored with the derived hash."""
    if hmac.compare_digest(stored_hash, _hash_secret(secret)):
        return True
    legacy = key_derivation.legacy_hmac_sha256_hex(settings.JWT_SECRET_KEY, secret)
    return hmac.compare_digest(stored_hash, legacy)


def _split_key(raw_key: str) -> tuple[str, str] | None:
    parts = raw_key.split("_")
    if len(parts) != 4 or parts[0] != "aqt" or parts[1] != "sk":
        return None
    public_id = parts[2].strip()
    secret = parts[3].strip()
    if not public_id or not secret:
        return None
    return public_id, secret


def _serialize_api_key(row: models.ApiKey) -> schemas.ApiKeyRead:
    return schemas.ApiKeyRead(
        id=row.id,
        name=row.name,
        workspace_id=row.workspace_id,
        public_id=row.public_id,
        scopes=list(row.scopes_json or []),
        limits=dict(row.limits_json or {}),
        config_policy=dict(row.config_policy_json or {}),
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="API key name is required")
    return name


def _has_permission_payload(permissions: list[dict[str, str]], resource: str, action: str) -> bool:
    for permission in permissions:
        pr = permission.get("resource")
        pa = permission.get("action")
        if (pr == resource or pr == "*") and (pa == action or pa == "*"):
            return True
    return False


async def _get_workspace_member(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> models.WorkspaceMember | None:
    return await _workspace_member_repo.get_member(
        session,
        workspace_id=workspace_id,
        auth_user_id=user_id,
    )


async def _ensure_active_workspace(session: AsyncSession, workspace_id: int) -> models.Workspace:
    workspace = await _workspace_repo.get(session, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if not workspace.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace is inactive")
    return workspace


async def _has_workspace_import_access(
    session: AsyncSession,
    *,
    user: models.AuthUser,
    workspace_id: int,
) -> bool:
    if user.is_superuser or user.has_permission("team", "import"):
        return True

    member = await _get_workspace_member(session, user_id=user.id, workspace_id=workspace_id)
    if member is None:
        return False
    # ``workspace_member`` no longer stores a denormalized ``role``; derive the
    # legacy role name from RBAC (``user_roles``, keyed on ``auth_user_id``).
    legacy_role = await legacy_workspace_role_name_for_user(session, user_id=user.id, workspace_id=workspace_id)
    if legacy_role in {"admin", "owner"}:
        return True

    workspace_rbac = await AuthService.get_workspace_roles_and_permissions_db(session, user.id, [workspace_id])
    _, permissions = workspace_rbac.get(workspace_id, ([], []))
    return _has_permission_payload(permissions, "team", "import")


async def ensure_can_manage_api_keys(
    session: AsyncSession,
    *,
    user: models.AuthUser,
    workspace_id: int,
) -> None:
    await _ensure_active_workspace(session, workspace_id)
    if not await _has_workspace_import_access(session, user=user, workspace_id=workspace_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for workspace {workspace_id}: team.import required",
        )


async def _api_key_status_counts(
    session: AsyncSession,
    *,
    auth_user_id: int,
    workspace_id: int,
) -> schemas.ApiKeyStatusCounts:
    """Workspace-wide (current user's) API-key tallies by derived status."""
    status_expr = sa.case(
        (models.ApiKey.revoked_at.isnot(None), "revoked"),
        (
            sa.and_(models.ApiKey.expires_at.isnot(None), models.ApiKey.expires_at <= _now()),
            "expired",
        ),
        else_="active",
    )
    rows = (
        await session.execute(
            sa.select(status_expr, sa.func.count(models.ApiKey.id))
            .where(
                models.ApiKey.auth_user_id == auth_user_id,
                models.ApiKey.workspace_id == workspace_id,
            )
            .group_by(status_expr)
        )
    ).all()
    tally = {str(label): int(count) for label, count in rows}
    return schemas.ApiKeyStatusCounts(
        total=sum(tally.values()),
        active=tally.get("active", 0),
        expired=tally.get("expired", 0),
        revoked=tally.get("revoked", 0),
    )


async def list_api_keys(
    session: AsyncSession,
    *,
    user: models.AuthUser,
    params: schemas.ApiKeyListParams,
) -> dict:
    """Paginated list of the current user's API keys for a workspace, plus status counts."""
    if params.workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="workspace_id is required",
        )
    await ensure_can_manage_api_keys(session, user=user, workspace_id=params.workspace_id)

    query = sa.select(models.ApiKey).where(
        models.ApiKey.auth_user_id == user.id,
        models.ApiKey.workspace_id == params.workspace_id,
    )
    count_query = sa.select(sa.func.count(models.ApiKey.id)).where(
        models.ApiKey.auth_user_id == user.id,
        models.ApiKey.workspace_id == params.workspace_id,
    )
    if params.search:
        term = f"%{params.search}%"
        query = query.where(models.ApiKey.name.ilike(term))
        count_query = count_query.where(models.ApiKey.name.ilike(term))

    query = params.apply_pagination_sort(query, models.ApiKey)
    rows = (await session.execute(query)).scalars().all()
    total = (await session.execute(count_query)).scalar_one()
    counts = await _api_key_status_counts(session, auth_user_id=user.id, workspace_id=params.workspace_id)
    return {
        "results": [_serialize_api_key(row) for row in rows],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
        "counts": counts,
    }


async def create_api_key(
    session: AsyncSession,
    *,
    user: models.AuthUser,
    payload: schemas.ApiKeyCreate,
) -> schemas.ApiKeyCreateResponse:
    await ensure_can_manage_api_keys(session, user=user, workspace_id=payload.workspace_id)

    public_id = secrets.token_hex(8)
    secret = secrets.token_hex(32)
    full_key = f"{API_KEY_PREFIX}_{public_id}_{secret}"
    row = models.ApiKey(
        auth_user_id=user.id,
        workspace_id=payload.workspace_id,
        public_id=public_id,
        secret_hash=_hash_secret(secret),
        name=_clean_name(payload.name),
        scopes_json=list(DEFAULT_API_KEY_SCOPES),
        limits_json=dict(DEFAULT_API_KEY_LIMITS),
        config_policy_json=dict(DEFAULT_API_KEY_CONFIG_POLICY),
        expires_at=payload.expires_at,
    )
    await _api_key_repo.create(session, row)
    await session.commit()
    await session.refresh(row)
    return schemas.ApiKeyCreateResponse(api_key=_serialize_api_key(row), key=full_key)


async def update_api_key(
    session: AsyncSession,
    *,
    user: models.AuthUser,
    api_key_id: int,
    payload: schemas.ApiKeyUpdate,
) -> schemas.ApiKeyRead:
    row = await _api_key_repo.get(session, api_key_id)
    if row is None or row.auth_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await ensure_can_manage_api_keys(session, user=user, workspace_id=row.workspace_id)
    row.name = _clean_name(payload.name)
    await session.commit()
    await session.refresh(row)
    return _serialize_api_key(row)


async def revoke_api_key(
    session: AsyncSession,
    *,
    user: models.AuthUser,
    api_key_id: int,
) -> None:
    row = await _api_key_repo.get(session, api_key_id)
    if row is None or row.auth_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await ensure_can_manage_api_keys(session, user=user, workspace_id=row.workspace_id)
    if row.revoked_at is None:
        row.revoked_at = _now()
        await session.commit()


async def validate_api_key(session: AsyncSession, raw_key: str) -> schemas.TokenPayload | None:
    parsed = _split_key(raw_key)
    if parsed is None:
        return None

    public_id, secret = parsed
    api_key = await _api_key_repo.get_by_public_id(session, public_id)
    if api_key is None:
        return None
    if not _verify_secret(secret, api_key.secret_hash):
        return None
    if api_key.revoked_at is not None:
        return None
    if api_key.expires_at is not None and api_key.expires_at <= _now():
        return None
    if api_key.user is None or not api_key.user.is_active:
        return None
    if api_key.workspace is None or not api_key.workspace.is_active:
        return None
    if not await _has_workspace_import_access(session, user=api_key.user, workspace_id=api_key.workspace_id):
        return None

    api_key.last_used_at = _now()
    await session.commit()

    scopes = list(api_key.scopes_json or [])
    limits = dict(api_key.limits_json or {})
    config_policy = dict(api_key.config_policy_json or {})
    return schemas.TokenPayload(
        sub=api_key.user.id,
        email=api_key.user.email,
        username=api_key.user.username,
        is_superuser=False,
        roles=[],
        permissions=[],
        workspaces=[
            schemas.WorkspaceMembership(
                workspace_id=api_key.workspace_id,
                slug=api_key.workspace.slug,
                role="api_key",
                rbac_roles=[],
                rbac_permissions=[{"resource": "team", "action": "import"}],
            )
        ],
        credential_type="api_key",
        api_key=schemas.TokenApiKeyInfo(
            id=api_key.id,
            public_id=api_key.public_id,
            workspace_id=api_key.workspace_id,
            scopes=scopes,
            limits=limits,
            config_policy=config_policy,
        ),
    )
