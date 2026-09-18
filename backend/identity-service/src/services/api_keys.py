"""Workspace-scoped API keys: issue, list, rename, revoke, validate.

A key is a delegated credential, not an identity of its own: its authority is
the owner's RBAC narrowed to the scopes it was granted (see ``validate``). Every
authorization question about a key is therefore answered by the same predicate
that answers it for a session, and no service needs api-key-specific code.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import quota
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import paginated_dict
from shared.models import QuotaApiKeyLimit
from shared.quota import admin as quota_admin
from shared.rbac import SCOPE_PAIRS, normalize_scopes, scope_pairs, unknown_scopes
from shared.repository import ApiKeyRepository, RoleRepository, WorkspaceMemberRepository, WorkspaceRepository
from shared.rpc.identity import rehydrate_user
from shared.schemas.quota import QuotaLimitsPayload, QuotaScopePolicy, QuotaUsageRead
from shared.services.audit import record_audit
from src import models, schemas
from src.core import key_derivation
from src.core.config import settings
from src.services.token_payload import TokenPayloadBuilder, token_payloads

__all__ = ("ApiKeyService", "api_keys")


def _now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime | None) -> str | None:
    """Render a timestamp for a JSONB audit snapshot (``json.dumps`` cannot)."""
    return value.isoformat() if value is not None else None


def _scope_names(row: models.ApiKey) -> list[str]:
    return [item.scope for item in row.scopes]


def _owner_username(row: models.ApiKey, owner: models.AuthUser | None = None) -> str:
    person = owner if owner is not None else getattr(row, "user", None)
    return person.username if person is not None else ""


class ApiKeyService:
    PREFIX = "owt_sk"
    # Keys minted before the owt rebrand still carry this prefix; validation
    # must keep accepting them until every holder rotates.
    _LEGACY_PREFIXES = ("aqt_sk",)

    def __init__(
        self,
        *,
        keys: ApiKeyRepository = ApiKeyRepository(),
        workspaces: WorkspaceRepository = WorkspaceRepository(),
        members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        roles: RoleRepository = RoleRepository(),
        payloads: TokenPayloadBuilder = token_payloads,
        config: Any = settings,
    ) -> None:
        self.keys = keys
        self.workspaces = workspaces
        self.members = members
        self.roles = roles
        self.payloads = payloads
        self.config = config
        # Domain-separated subkey for hashing API-key secrets (never the raw JWT secret).
        self._secret_key = key_derivation.api_key_secret_key(config.JWT_SECRET_KEY)

    # -- key material ------------------------------------------------------

    def is_api_key(self, raw_token: str) -> bool:
        return raw_token.startswith(f"{self.PREFIX}_") or any(
            raw_token.startswith(f"{prefix}_") for prefix in self._LEGACY_PREFIXES
        )

    def _hash_secret(self, secret: str) -> str:
        """Hash an API-key secret for storage (domain-separated subkey, new writes)."""
        return key_derivation.hmac_sha256_hex(self._secret_key, secret)

    def _verify_secret(self, secret: str, stored_hash: str) -> bool:
        """Constant-time verify against the derived hash, then the legacy raw-secret
        hash — so API keys created before domain separation keep validating without
        a re-issue. New keys are always stored with the derived hash."""
        if hmac.compare_digest(stored_hash, self._hash_secret(secret)):
            return True
        legacy = key_derivation.legacy_hmac_sha256_hex(self.config.JWT_SECRET_KEY, secret)
        return hmac.compare_digest(stored_hash, legacy)

    @staticmethod
    def _split_key(raw_key: str) -> tuple[str, str] | None:
        parts = raw_key.split("_")
        if len(parts) != 4 or parts[1] != "sk" or parts[0] not in ("owt", "aqt"):
            return None
        public_id = parts[2].strip()
        secret = parts[3].strip()
        if not public_id or not secret:
            return None
        return public_id, secret

    # -- serialization -----------------------------------------------------

    @staticmethod
    def describe(row: models.ApiKey, *, owner: models.AuthUser | None = None) -> schemas.ApiKeyRead:
        return schemas.ApiKeyRead(
            id=row.id,
            name=row.name,
            workspace_id=row.workspace_id,
            public_id=row.public_id,
            owner_id=row.auth_user_id,
            owner_username=_owner_username(row, owner),
            scopes=_scope_names(row),
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _clean_name(value: str) -> str:
        name = value.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="API key name is required")
        return name

    # -- authorization -----------------------------------------------------

    @staticmethod
    def _has_permission_payload(permissions: list[dict[str, str]], resource: str, action: str) -> bool:
        for permission in permissions:
            pr = permission.get("resource")
            pa = permission.get("action")
            if (pr == resource or pr == "*") and (pa == action or pa == "*"):
                return True
        return False

    async def _ensure_active_workspace(self, session: AsyncSession, workspace_id: int) -> models.Workspace:
        workspace = await self.workspaces.get(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if not workspace.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace is inactive")
        return workspace

    async def _has_workspace_import_access(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        workspace_id: int,
    ) -> bool:
        if user.is_superuser or user.has_permission("team", "create"):
            return True

        member = await self.members.get_member(session, workspace_id=workspace_id, auth_user_id=user.id)
        if member is None:
            return False
        # No legacy role-name shortcut here: it bypassed RBAC entirely, so a
        # workspace role narrowed to exclude ``team.create`` would still have
        # passed on the strength of its name alone. Owner is covered below by the
        # wildcard ``*``/``*`` grant behind ``admin.*``.
        workspace_rbac = await self.roles.workspace_rbac_for_user(session, user.id, [workspace_id])
        _, permissions = workspace_rbac.get(workspace_id, ([], []))
        return self._has_permission_payload(permissions, "team", "create")

    async def ensure_can_manage(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        workspace_id: int,
    ) -> None:
        await self._ensure_active_workspace(session, workspace_id)
        if not await self._has_workspace_import_access(session, user=user, workspace_id=workspace_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for workspace {workspace_id}: team.create required",
            )

    async def _owner_authority(
        self,
        session: AsyncSession,
        user: models.AuthUser,
    ) -> tuple[schemas.TokenPayload, models.AuthUser]:
        """The owner's full RBAC, as both the payload and a queryable AuthUser.

        ``rehydrate_user`` is the very function every worker applies to the
        gateway-injected identity, so a permission question answered here gets
        the identical answer it would get downstream. Built from the payload
        rather than from ``user``'s ORM relationships on purpose: on a warm RBAC
        cache the row is loaded without its role collections, and touching
        ``AuthUser.roles`` then would lazy-load outside the async greenlet.
        """
        payload = await self.payloads.build(session, user)
        return payload, rehydrate_user(payload.model_dump(mode="json"))

    async def grantable_scopes(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        workspace_id: int,
    ) -> frozenset[str]:
        """Catalog scopes ``user`` may delegate to a key in this workspace.

        Delegation only ever narrows: nobody can mint a key that does what they
        cannot do themselves. Decided with the same predicate ``validate`` uses,
        so the create form and the token path can never disagree about a scope.

        Note the self-service capabilities (``account.*``,
        ``registration.self_register``) fall out of this set by construction:
        they are allow-by-default and deny-only, never workspace grants, so no
        member "holds" them in the RBAC sense and no key can carry them.
        """
        _, owner = await self._owner_authority(session, user)
        return frozenset(
            name
            for name, (resource, action) in SCOPE_PAIRS.items()
            if owner.has_workspace_permission(workspace_id, resource, action)
        )

    # -- read --------------------------------------------------------------

    async def _status_counts(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
    ) -> schemas.ApiKeyStatusCounts:
        tally = await self.keys.status_counts(
            session,
            workspace_id=workspace_id,
            now=_now(),
        )
        return schemas.ApiKeyStatusCounts(
            total=sum(tally.values()),
            active=tally.get("active", 0),
            expired=tally.get("expired", 0),
            revoked=tally.get("revoked", 0),
        )

    async def list(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        params: schemas.ApiKeyListParams,
    ) -> dict:
        """Paginated list of every API key in a workspace, plus status counts."""
        if params.workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="workspace_id is required",
            )
        await self.ensure_can_manage(session, user=user, workspace_id=params.workspace_id)

        rows, total = await self.keys.list_page(
            session,
            params,
            workspace_id=params.workspace_id,
            search=params.search,
        )
        counts = await self._status_counts(session, workspace_id=params.workspace_id)
        available = await self.grantable_scopes(session, user=user, workspace_id=params.workspace_id)
        return {
            **paginated_dict([self.describe(row) for row in rows], total, params),
            "counts": counts,
            "available_scopes": sorted(available),
        }

    async def describe_self(self, session: AsyncSession, *, api_key_id: int) -> schemas.ApiKeyRead:
        """The calling key's own descriptor.

        No ownership check: the id arrives from a credential this service has
        already verified, so the caller is the key by definition.
        """
        row = await self.keys.get_with_owner(session, api_key_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        return self.describe(row)

    # -- write -------------------------------------------------------------

    async def create(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        payload: schemas.ApiKeyCreate,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> schemas.ApiKeyCreateResponse:
        await self.ensure_can_manage(session, user=user, workspace_id=payload.workspace_id)

        unknown = unknown_scopes(payload.scopes)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown scopes: {', '.join(sorted(unknown))}",
            )
        scopes = normalize_scopes(payload.scopes)
        if scopes:
            grantable = await self.grantable_scopes(session, user=user, workspace_id=payload.workspace_id)
            ungrantable = sorted(scope for scope in scopes if scope not in grantable)
            if ungrantable:
                # Refused here rather than silently dropped: a key that quietly
                # does less than it was asked to fails in production, not at
                # issue time.
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Cannot grant scopes you do not hold: {', '.join(ungrantable)}",
                )

        public_id = secrets.token_hex(8)
        secret = secrets.token_hex(32)
        full_key = f"{self.PREFIX}_{public_id}_{secret}"
        row = models.ApiKey(
            auth_user_id=user.id,
            workspace_id=payload.workspace_id,
            public_id=public_id,
            secret_hash=self._hash_secret(secret),
            name=self._clean_name(payload.name),
            scopes=[models.ApiKeyScope(scope=name) for name in scopes],
            expires_at=payload.expires_at,
        )
        await self.keys.create(session, row)
        # Never the secret, its hash, or the public id: an API key is identified in
        # the journal by its row id and human name, and by nothing that authenticates.
        await record_audit(
            session,
            action="api_key.create",
            source="admin",
            actor=user,
            actor_label=user.username or user.email,
            workspace_id=row.workspace_id,
            entity_type="api_key",
            entity_id=row.id,
            entity_label=row.name,
            after={
                "name": row.name,
                "scopes": list(scopes),
                "expires_at": _isoformat(row.expires_at),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await session.refresh(row)
        return schemas.ApiKeyCreateResponse(api_key=self.describe(row, owner=user), key=full_key)

    async def update(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        api_key_id: int,
        payload: schemas.ApiKeyUpdate,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> schemas.ApiKeyRead:
        row = await self.keys.get_with_owner(session, api_key_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        await self.ensure_can_manage(session, user=user, workspace_id=row.workspace_id)
        before_name = row.name
        row.name = self._clean_name(payload.name)
        await record_audit(
            session,
            action="api_key.update",
            source="admin",
            actor=user,
            actor_label=user.username or user.email,
            workspace_id=row.workspace_id,
            entity_type="api_key",
            entity_id=row.id,
            entity_label=row.name,
            before={"name": before_name},
            after={"name": row.name},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        await session.refresh(row)
        return self.describe(row)

    async def revoke(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        api_key_id: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        row = await self.keys.get_with_owner(session, api_key_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        await self.ensure_can_manage(session, user=user, workspace_id=row.workspace_id)
        if row.revoked_at is None:
            row.revoked_at = _now()
            # Inside the branch: revoking an already-revoked key changes nothing and
            # must not add a second "revoked" row to the journal.
            await record_audit(
                session,
                action="api_key.revoke",
                source="admin",
                actor=user,
                actor_label=user.username or user.email,
                workspace_id=row.workspace_id,
                entity_type="api_key",
                entity_id=row.id,
                entity_label=row.name,
                before={"revoked_at": None},
                after={"revoked_at": _isoformat(row.revoked_at)},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await session.commit()

    # -- quota -------------------------------------------------------------

    async def _manageable_key(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        api_key_id: int,
    ) -> models.ApiKey:
        """The key row, once the caller has proved they may administer it.

        Always resolved against the key's OWN workspace and never a caller-supplied
        one: the same gate as rename and revoke, so a quota write cannot reach a
        key the caller could not already rename.
        """
        row = await self.keys.get_with_owner(session, api_key_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        await self.ensure_can_manage(session, user=user, workspace_id=row.workspace_id)
        return row

    @staticmethod
    async def _quota_override(session: AsyncSession, api_key_id: int) -> dict[str, int | None]:
        """The override row as a flat dimension map, all-``None`` when absent."""
        row = (
            await session.execute(select(QuotaApiKeyLimit).where(QuotaApiKeyLimit.api_key_id == api_key_id))
        ).scalar_one_or_none()
        return {name: (getattr(row, name) if row is not None else None) for name in quota_admin.DIMENSIONS}

    async def _quota_usage(self, session: AsyncSession, row: models.ApiKey) -> QuotaUsageRead:
        report = await quota.usage(
            principal_kind="api_key",
            principal_id=row.id,
            workspace_id=row.workspace_id,
        )
        return QuotaUsageRead(
            plan_slug=await quota_admin.plan_slug_for_workspace(session, row.workspace_id),
            **report,
            # The key's own row and the bound ``set_quota`` holds it to (plan
            # narrowed by the workspace's key override). Without the row an
            # editor cannot show what it is about to replace, and without the
            # bound it cannot say which edits are superuser-only.
            policy=[
                QuotaScopePolicy(
                    scope="key",
                    override=QuotaLimitsPayload(**await self._quota_override(session, row.id)),
                    inherited=QuotaLimitsPayload(
                        **await quota_admin.inherited_limits(session, workspace_id=row.workspace_id, scope="key")
                    ),
                )
            ],
        )

    async def set_quota(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        api_key_id: int,
        limits: QuotaLimitsPayload,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> QuotaLimitsPayload:
        """Override one key's limits; an all-null payload drops the override."""
        row = await self._manageable_key(session, user=user, api_key_id=api_key_id)
        before = await self._quota_override(session, api_key_id)
        values = limits.as_dict()
        await quota_admin.apply_api_key_limits(
            session,
            api_key_id=api_key_id,
            workspace_id=row.workspace_id,
            values=values,
            updated_by=user.id,
            # A superuser retunes in either direction; a workspace manager may
            # only tighten, since raising past the plan would be self-service
            # capacity.
            allow_raise=user.is_superuser,
        )
        await record_audit(
            session,
            action="api_key.quota_update",
            source="admin",
            actor=user,
            actor_label=user.username or user.email,
            workspace_id=row.workspace_id,
            entity_type="api_key",
            entity_id=row.id,
            entity_label=row.name,
            before=before,
            after=values,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        # Resolved policy is cached per process; without this the write is
        # invisible here until the TTL lapses. Other workers still wait it out.
        quota.invalidate_policy()
        return limits

    async def quota_usage(
        self,
        session: AsyncSession,
        *,
        user: models.AuthUser,
        api_key_id: int,
    ) -> QuotaUsageRead:
        """An administrator's view of one key's budget."""
        row = await self._manageable_key(session, user=user, api_key_id=api_key_id)
        return await self._quota_usage(session, row)

    async def self_quota_usage(self, session: AsyncSession, *, api_key_id: int) -> QuotaUsageRead:
        """The calling key's own budget.

        No ownership check, for the reason ``describe_self`` has none: the id
        came off a credential this service already verified.
        """
        row = await self.keys.get_with_owner(session, api_key_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        return await self._quota_usage(session, row)

    # -- validation --------------------------------------------------------

    async def validate(self, session: AsyncSession, raw_key: str) -> schemas.TokenPayload | None:
        """Resolve a raw key to RBAC: the owner's authority, narrowed to its scopes.

        The narrowing is a filter over the owner's own payload, never a
        hand-assembled grant list: each candidate scope is put to
        ``AuthUser.has_workspace_permission``, the same predicate every service
        gate uses. That is what makes it structurally impossible for a key to
        outrank its owner, and it keeps this function free of RBAC precedence
        rules (deny overlay, superuser, workspace-admin carve-outs) that would
        rot out of sync with the model the moment either side changed.

        ``None`` for every unusable credential: the caller turns that into a 401
        without disclosing which check failed.
        """
        parsed = self._split_key(raw_key)
        if parsed is None:
            return None

        public_id, secret = parsed
        api_key = await self.keys.get_by_public_id(session, public_id)
        if api_key is None:
            return None
        if not self._verify_secret(secret, api_key.secret_hash):
            return None
        if api_key.revoked_at is not None:
            return None
        if api_key.expires_at is not None and api_key.expires_at <= _now():
            return None
        if api_key.user is None or not api_key.user.is_active:
            return None
        if api_key.workspace is None or not api_key.workspace.is_active:
            return None

        owner_payload, owner = await self._owner_authority(session, api_key.user)
        # A key must not outlive its owner's membership: losing the workspace
        # kills every key scoped to it without waiting for anyone to revoke.
        if not owner.is_workspace_member(api_key.workspace_id):
            return None

        scopes = normalize_scopes(_scope_names(api_key))
        granted = [
            {"resource": resource, "action": action}
            for resource, action in scope_pairs(scopes)
            if owner.has_workspace_permission(api_key.workspace_id, resource, action)
        ]

        api_key.last_used_at = _now()
        await session.commit()

        return schemas.TokenPayload(
            sub=api_key.user.id,
            email=api_key.user.email,
            username=api_key.user.username,
            # Never a superuser and never carrying role NAMES: both are blanket
            # bypasses in AuthUser (is_superuser, _has_admin_equivalent_role,
            # _has_admin_panel_role), and a delegated credential must be fully
            # described by the permission list below.
            is_superuser=False,
            roles=[],
            # Global permissions stay empty by construction: the key is scoped to
            # one workspace, and a global grant would reach every other one.
            permissions=[],
            # The deny overlay rides along. A deny outranks every allow, so
            # omitting it -- as this used to -- let a key do precisely what its
            # owner had been explicitly forbidden.
            denies=owner_payload.denies,
            workspaces=[
                schemas.WorkspaceMembership(
                    workspace_id=api_key.workspace_id,
                    slug=api_key.workspace.slug,
                    rbac_roles=[],
                    rbac_permissions=granted,
                )
            ],
            credential_type="api_key",
            api_key=schemas.TokenApiKeyInfo(
                id=api_key.id,
                public_id=api_key.public_id,
                workspace_id=api_key.workspace_id,
                scopes=list(scopes),
            ),
        )


api_keys = ApiKeyService()
