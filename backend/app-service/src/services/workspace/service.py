import secrets
import typing
from datetime import UTC, datetime

import dns.asyncresolver
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.rpc import request_rpc
from shared.models.identity.auth_user import AuthUser
from shared.rbac import (
    assign_default_member_role_if_roleless,
    assign_workspace_system_role,
    ensure_workspace_system_roles,
    get_workspace_system_role,
    replace_user_workspace_roles,
    user_has_only_workspace_owner_role,
)
from shared.repository import (
    AuthUserRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
    get_or_create_workspace_member,
)
from shared.services.audit import record_audit
from shared.services.division_grid.access import get_default_division_grid_version_id
from shared.services.settings_provider import get_workspace_creation_config
from shared.services.workspace_tier import is_verified_or_trusted
from shared.tenancy.hostnames import RESERVED_SUBDOMAINS, normalize_custom_domain
from src import models

__all__ = ["MEMBERS_SORT_FIELDS", "RESERVED_SLUGS", "WorkspaceService", "reject_reserved_slug", "workspaces"]

# Prefix for the generated per-workspace DNS verification token (the required
# TXT value at ``_owt-verify.<custom_domain>``). Namespaced so the string is
# unambiguous if it ever leaks into logs or support tickets.
_CUSTOM_DOMAIN_TOKEN_PREFIX = "owt-verify-"

_DOMAIN_CONFLICT_MESSAGE = "This custom domain is already claimed by another workspace"
_GUILD_CONFLICT_MESSAGE = "This Discord guild is already claimed by another workspace"
# Internal, service-to-service subject -- no gateway route, no shared
# RabbitQueue constant (workspace self-service design §4.1/§4.6): every other
# rpc.identity.* subject is called the same way, by its bare subject string,
# because the caller has always been the Go gateway until now. This is the
# first Python-to-Python call to it; the bare string still routes correctly
# because @broker.subscriber("rpc.identity.oauth_discord_guilds") declares a
# same-named queue on the default exchange.
_DISCORD_GUILDS_SUBJECT = "rpc.identity.oauth_discord_guilds"
# Discord-guild list/verify fail closed on an unreachable identity-service
# and say so identically -- one is the picker for the other. Clear does not
# talk to Discord at all.
_GUILD_UNREACHABLE_MESSAGE = "Could not reach Discord for guild verification"

MEMBERS_SORT_FIELDS = ("username", "role")

# Slugs the platform keeps for itself, rejected by self-service create (design
# §4.4). Built on the reserved subdomain labels because a slug is the natural
# candidate for a workspace's ``subdomain``, plus the platform's own top-level
# route names. Superusers are not exempt: the collision is with the platform,
# not with a permission.
RESERVED_SLUGS = RESERVED_SUBDOMAINS | {"docs", "status", "support"}


def reject_reserved_slug(slug: str) -> None:
    if slug.strip().lower() in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="slug_reserved")


def _iso(value: datetime | None) -> str | None:
    """JSONB-safe timestamp for an audit before/after snapshot."""
    return value.isoformat() if value else None


def _is_listed(workspace: models.Workspace) -> bool:
    """The public-directory bar: not hidden, and past the ``unverified`` tier."""
    return not workspace.is_hidden and is_verified_or_trusted(workspace)


class WorkspaceService:
    """Workspace + membership orchestration: repository-backed CRUD, the
    custom-domain (white-label) lifecycle, and the RBAC member queries."""

    def __init__(
        self,
        *,
        role_repo: RoleRepository = RoleRepository(),
        member_repo: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
        user_repo: UserRepository = UserRepository(),
        user_role_repo: UserRoleRepository = UserRoleRepository(),
        auth_user_repo: AuthUserRepository = AuthUserRepository(),
    ) -> None:
        self.role_repo = role_repo
        self.member_repo = member_repo
        self.workspace_repo = workspace_repo
        self.user_repo = user_repo
        self.user_role_repo = user_role_repo
        self.auth_user_repo = auth_user_repo

    # --- reads --------------------------------------------------------------

    async def get_by_id(self, session: AsyncSession, workspace_id: int) -> models.Workspace | None:
        return await self.workspace_repo.get_with_default_grid(session, workspace_id)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.Workspace | None:
        return await self.workspace_repo.get_by_slug(session, slug)

    async def get_by_subdomain(self, session: AsyncSession, subdomain: str) -> models.Workspace | None:
        return await self.workspace_repo.get_by_subdomain(session, subdomain)

    async def get_by_custom_domain(self, session: AsyncSession, domain: str) -> models.Workspace | None:
        """Resolve a verified custom domain to its workspace (Phase 2 of ``by_host``).

        Delegates to the verified-only repo query — an unverified ``custom_domain``
        never resolves here.
        """
        return await self.workspace_repo.get_by_verified_custom_domain(session, domain)

    async def get_all(
        self,
        session: AsyncSession,
        *,
        user: AuthUser | None = None,
        scope: typing.Literal["public", "admin", "all"] = "public",
    ) -> typing.Sequence[models.Workspace]:
        """Workspaces the caller is entitled to see under ``scope``.

        ``public`` (the default, and what the home-page directory asks for) is
        the strict directory: ``not is_hidden`` AND a trust tier past
        ``unverified`` (design §4.5). It has NO bypasses -- membership does not
        lift it and neither does ``is_superuser``, because the directory is one
        shared public surface and an operator browsing the home page must see
        exactly what a visitor sees (revised 2026-09-07).

        ``admin`` is the management list: everything for a superuser, otherwise
        only the caller's own workspaces at any tier (the admin table narrows
        that further to the ones they actually administer, which is a
        permission question this layer does not answer).

        ``all`` is ``admin`` unioned with the public directory -- the workspace
        switcher and slug resolution, where a member must reach their own
        brand-new ``unverified`` workspace while still being able to browse
        every listed one.

        Direct lookups (``get_by_id``, ``get_by_slug``, ``get_by_subdomain``,
        ``get_by_custom_domain``) are untouched by all of this: a fresh
        ``unverified`` workspace is fully reachable and usable by slug,
        subdomain or verified custom domain the moment it is created, it just
        does not appear in the public directory until a superuser marks it
        ``verified``.
        """
        workspaces = await self.workspace_repo.list_ordered(session)
        if scope == "public":
            return [w for w in workspaces if _is_listed(w)]
        if user is None:
            return [] if scope == "admin" else [w for w in workspaces if _is_listed(w)]
        if user.is_superuser:
            return workspaces
        member_ids = set(user.get_workspace_ids())
        if scope == "admin":
            return [w for w in workspaces if w.id in member_ids]
        return [w for w in workspaces if w.id in member_ids or _is_listed(w)]

    # --- custom domain (white-label Phase 2) --------------------------------

    async def _dns_txt_contains(self, name: str, expected: str) -> bool:
        """True iff a TXT record at ``name`` has a string that exactly equals ``expected``.

        Any DNS failure (NXDOMAIN, timeout, no-answer, malformed name, resolver
        misconfiguration, ...) resolves to ``False`` rather than raising —
        verification is meant to fail closed (``verify_custom_domain`` reports
        "not found yet"), never 500.
        """
        try:
            answers = await dns.asyncresolver.resolve(name, "TXT")
        except Exception:  # noqa: BLE001 -- any DNS failure means "not verified yet"
            return False
        for rdata in answers:
            txt = b"".join(rdata.strings).decode("utf-8", "ignore")
            if txt.strip() == expected:
                return True
        return False

    async def set_custom_domain(
        self, session: AsyncSession, workspace: models.Workspace, domain: str
    ) -> models.Workspace:
        """Store a normalized custom domain plus a fresh verification token, unverified.

        Re-pointing an already-verified domain (or setting a new one) always resets
        ``custom_domain_verified_at`` — the resolver (``get_by_custom_domain``) must
        never serve a domain whose ownership hasn't been (re-)proven via DNS TXT.

        Raises ``ValueError`` (mapped to 400 by the RPC caller) if ``domain`` fails
        ``normalize_custom_domain`` (empty, not a valid FQDN, or under the platform
        zone).

        Raises ``HTTPException(409)`` if another workspace already claims this
        domain (verified or not — the unique index ``ix_workspace_custom_domain``
        doesn't care either way). This is checked twice: a best-effort read
        up front (cheap, gives a clean error in the common case) AND the
        authoritative catch of the index's ``IntegrityError`` on write, since the
        read has a TOCTOU gap under a concurrent claim of the same domain.
        """
        normalized = normalize_custom_domain(domain)
        existing = await self.workspace_repo.get_by_custom_domain_any(session, normalized)
        if existing is not None and existing.id != workspace.id:
            raise HTTPException(status_code=409, detail=_DOMAIN_CONFLICT_MESSAGE)

        token = _CUSTOM_DOMAIN_TOKEN_PREFIX + secrets.token_urlsafe(24)
        try:
            await self.workspace_repo.update_fields(
                session,
                workspace,
                {
                    "custom_domain": normalized,
                    "custom_domain_verification_token": token,
                    "custom_domain_verified_at": None,
                },
            )
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail=_DOMAIN_CONFLICT_MESSAGE) from exc
        return workspace

    async def clear_custom_domain(self, session: AsyncSession, workspace: models.Workspace) -> models.Workspace:
        """Remove the custom domain (and its token/verification state) entirely."""
        await self.workspace_repo.update_fields(
            session,
            workspace,
            {
                "custom_domain": None,
                "custom_domain_verification_token": None,
                "custom_domain_verified_at": None,
            },
        )
        return workspace

    async def verify_custom_domain(self, session: AsyncSession, workspace: models.Workspace) -> models.Workspace:
        """DNS-verify ``workspace.custom_domain`` and stamp ``custom_domain_verified_at``.

        Ownership proof is a TXT record at ``_owt-verify.<custom_domain>`` whose value
        equals the stored ``custom_domain_verification_token``. Raises 400 if no
        domain/token is set, or if the record doesn't (yet) match.

        The DNS TXT lookup is network I/O and must not run while pinning a pooled
        DB connection. By the time this is called, the caller's earlier read
        (``get_by_id``) has already opened an ambient transaction on ``session``
        — with nothing written yet, so committing it here is a plain read-only
        commit that only releases the connection. The lookup then runs with no
        session held, and the DB is only touched again (a fresh, short
        transaction) for the final ``custom_domain_verified_at`` write. This is
        safe against SQLAlchemy's attribute-expiry-on-commit: ``async_session_maker``
        is built with ``expire_on_commit=False`` (``backend/shared/core/db.py``),
        so this early commit never invalidates ``workspace``'s already-loaded
        attributes.
        """
        if not workspace.custom_domain or not workspace.custom_domain_verification_token:
            raise HTTPException(status_code=400, detail="No custom domain to verify")

        domain = workspace.custom_domain
        token = workspace.custom_domain_verification_token
        await session.commit()

        ok = await self._dns_txt_contains(f"_owt-verify.{domain}", token)
        if not ok:
            raise HTTPException(status_code=400, detail="Verification TXT record not found yet")
        await self.workspace_repo.update_fields(session, workspace, {"custom_domain_verified_at": datetime.now(UTC)})
        return workspace

    # --- writes -------------------------------------------------------------

    async def validate_default_division_grid_version(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None,
        version_id: int,
    ) -> None:
        owner_id = await session.scalar(
            sa.select(sa.func.coalesce(models.DivisionGrid.workspace_id, -1))
            .join(
                models.DivisionGridVersion,
                models.DivisionGridVersion.grid_id == models.DivisionGrid.id,
            )
            .where(models.DivisionGridVersion.id == version_id)
        )
        if owner_id is None:
            raise HTTPException(status_code=404, detail="Division grid version not found")
        if owner_id != -1 and owner_id != workspace_id:
            raise HTTPException(
                status_code=400,
                detail="Default division grid version must belong to the workspace or be global",
            )

    async def _resolve_default_division_grid_version_id(
        self,
        session: AsyncSession,
        version_id: int | None,
        *,
        workspace_id: int | None = None,
    ) -> int:
        if version_id is not None:
            await self.validate_default_division_grid_version(
                session,
                workspace_id=workspace_id,
                version_id=version_id,
            )
            return version_id

        resolved_version_id = await get_default_division_grid_version_id(session)
        if resolved_version_id is None:
            raise RuntimeError("System default division grid version is not configured")
        return resolved_version_id

    async def create(self, session: AsyncSession, **kwargs) -> models.Workspace:
        payload = dict(kwargs)
        payload["default_division_grid_version_id"] = await self._resolve_default_division_grid_version_id(
            session,
            payload.get("default_division_grid_version_id"),
        )

        workspace = models.Workspace(**payload)
        return await self.workspace_repo.create(session, workspace)

    async def update(self, session: AsyncSession, workspace: models.Workspace, data: dict) -> models.Workspace:
        if "default_division_grid_version_id" in data:
            raise HTTPException(
                status_code=400,
                detail="Activate division grid versions through the division-grid activation endpoint",
            )
        await self.workspace_repo.update_fields(session, workspace, dict(data))
        return workspace

    async def delete(self, session: AsyncSession, workspace: models.Workspace) -> None:
        await self.workspace_repo.delete(session, workspace)

    # --- members ------------------------------------------------------------

    async def get_members(self, session: AsyncSession, workspace_id: int) -> typing.Sequence[models.WorkspaceMember]:
        return await self.member_repo.list_by_workspace(session, workspace_id)

    async def list_members_page(
        self,
        session: AsyncSession,
        workspace_id: int,
        *,
        page: int,
        per_page: int,
        search: str | None,
        role_id: int | None = None,
        sort: str = "username",
        order: str = "asc",
    ) -> tuple[int, list[tuple[models.WorkspaceMember, models.AuthUser, list[models.Role]]]]:
        """Paginated + searchable + role-filterable/sortable RBAC members.

        Returns ``(total, [(member, auth_user, workspace_roles)])``. Thin
        translation of the service's ``order: str`` into the repository's
        ``descending: bool``; the three-statement query (count + page + one
        batched role fetch) lives in ``WorkspaceMemberRepository.list_page``.
        ``per_page == -1`` returns all members (capped) for selector/combobox
        callers. ``sort`` is one of ``username`` / ``role`` (primary system-role
        rank); ``order`` is ``asc`` / ``desc``.
        """
        return await self.member_repo.list_page(
            session,
            workspace_id=workspace_id,
            page=page,
            per_page=per_page,
            search=search,
            role_id=role_id,
            sort=sort,
            descending=order == "desc",
        )

    async def autofill_member_roles(self, session: AsyncSession, workspace_id: int) -> int:
        """Grant the baseline ``member`` role to every auth-linked member of
        ``workspace_id`` whose auth user currently holds no role there.

        Set-based and idempotent (the ``NOT EXISTS`` guard only touches role-less
        members, so re-running assigns nothing and never duplicates). Ensures the
        workspace system roles exist first so the ``member`` role is guaranteed
        present. Returns the number of grants inserted.
        """
        await ensure_workspace_system_roles(session, workspace_id)
        return await self.user_role_repo.grant_missing_workspace_member_role(session, workspace_id)

    async def get_member(
        self, session: AsyncSession, workspace_id: int, auth_user_id: int
    ) -> models.WorkspaceMember | None:
        return await self.member_repo.get_member(
            session,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
        )

    async def _resolve_player_id_for_auth_user(self, session: AsyncSession, auth_user_id: int) -> int:
        """Resolve the ``players.user.id`` linked to ``auth_user_id``, provisioning a
        bare player if none exists.

        ``workspace_member`` is anchored on ``player_id``, so adding a member needs
        the auth user to have a linked ``players.user``. Post-Phase-A signups get one
        automatically, but legacy accounts (registered before that provisioning) have
        none — and Add Member explicitly targets staff who never played. Rather than
        500 on such users, provision the identity backbone on demand (mirrors
        ``ensure_player_for_auth_user``); the auth user's existence is validated by
        the caller (member_add) before we get here.
        """
        auth_user = await self.auth_user_repo.get(session, auth_user_id)
        name_hint = (auth_user.username or auth_user.email) if auth_user is not None else None
        player = await self.user_repo.ensure_for_auth_user(session, auth_user_id=auth_user_id, name_hint=name_hint)
        return player.id

    async def add_member(self, session: AsyncSession, workspace_id: int, auth_user_id: int) -> models.WorkspaceMember:
        """Create (or fetch) the membership row for the player linked to ``auth_user_id``.

        Callers keep passing ``auth_user_id`` (unchanged signature); internally we
        resolve the ``player_id`` the ``workspace_member`` row is actually
        anchored on. No longer accepts/writes a ``role`` — the column was dropped;
        RBAC (``user_roles``, keyed on ``auth_user_id``) is the source of truth.
        """
        await ensure_workspace_system_roles(session, workspace_id)
        player_id = await self._resolve_player_id_for_auth_user(session, auth_user_id)
        return await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)

    async def add_member_with_roles(
        self,
        session: AsyncSession,
        workspace_id: int,
        auth_user_id: int,
        *,
        role_ids: list[int],
    ) -> models.WorkspaceMember:
        member = await self.add_member(session, workspace_id, auth_user_id)
        await replace_user_workspace_roles(
            session,
            user_id=auth_user_id,
            workspace_id=workspace_id,
            role_ids=role_ids,
        )
        await session.flush()
        # ``updated_at`` (onupdate=func.now()) is server-computed and gets expired by
        # the flush; refresh inside the async context so callers can read it without
        # triggering a lazy load outside the greenlet (sqlalchemy.exc.MissingGreenlet).
        await session.refresh(member)
        return member

    async def _workspace_roles_from_ids(
        self,
        session: AsyncSession,
        workspace_id: int,
        role_ids: list[int],
    ) -> list[models.Role]:
        if not role_ids:
            return []
        roles = await self.role_repo.bulk_get(
            session,
            role_ids,
        )
        roles = [role for role in roles if role.workspace_id == workspace_id]
        if len({role.id for role in roles}) != len(set(role_ids)):
            raise ValueError("All role_ids must refer to roles in the target workspace")
        return roles

    async def get_member_auth_user_id(self, session: AsyncSession, member: models.WorkspaceMember) -> int:
        """Resolve the RBAC (``auth.user.id``) identity behind a membership row.

        ``workspace_member`` is anchored on ``player_id``; RBAC (``user_roles``,
        role assignment, ownership checks) stays keyed on ``auth_user_id``. This
        is the bridge between the two for code that only has the member row.
        """
        player = await self.user_repo.get(session, member.player_id)
        if player is None or player.auth_user_id is None:
            raise HTTPException(
                status_code=500,
                detail=f"workspace_member {member.id} has no linked auth user (player_id={member.player_id})",
            )
        return player.auth_user_id

    async def update_member_roles(
        self,
        session: AsyncSession,
        member: models.WorkspaceMember,
        *,
        role_ids: list[int],
    ) -> models.WorkspaceMember:
        auth_user_id = await self.get_member_auth_user_id(session, member)
        if await user_has_only_workspace_owner_role(
            session,
            user_id=auth_user_id,
            workspace_id=member.workspace_id,
        ):
            roles = await self._workspace_roles_from_ids(session, member.workspace_id, role_ids)
            if all(role.name != "owner" for role in roles):
                raise ValueError("Cannot remove the last workspace owner")

        await replace_user_workspace_roles(
            session,
            user_id=auth_user_id,
            workspace_id=member.workspace_id,
            role_ids=role_ids,
        )
        await session.flush()
        # ``updated_at`` (onupdate=func.now()) is server-computed and gets expired by
        # the flush; refresh inside the async context so callers can read it without
        # triggering a lazy load outside the greenlet (sqlalchemy.exc.MissingGreenlet).
        await session.refresh(member)
        return member

    async def get_member_workspace_roles(
        self,
        session: AsyncSession,
        workspace_id: int,
        auth_user_id: int,
    ) -> list[models.Role]:
        return await self.role_repo.list_for_user_workspace(
            session,
            user_id=auth_user_id,
            workspace_id=workspace_id,
        )

    async def can_remove_member(self, session: AsyncSession, member: models.WorkspaceMember) -> bool:
        auth_user_id = await self.get_member_auth_user_id(session, member)
        return not await user_has_only_workspace_owner_role(
            session,
            user_id=auth_user_id,
            workspace_id=member.workspace_id,
        )

    async def remove_member(self, session: AsyncSession, member: models.WorkspaceMember) -> None:
        auth_user_id = await self.get_member_auth_user_id(session, member)
        await self.user_role_repo.revoke_workspace_roles(
            session, user_id=auth_user_id, workspace_id=member.workspace_id
        )
        await self.member_repo.delete(session, member)

    # --- ownership cap guard (design §4.4) ----------------------------------

    async def ensure_create_limit(
        self,
        session: AsyncSession,
        user: typing.Any,
        *,
        detail: str = "workspace_create_limit_reached",
    ) -> None:
        """403 unless ``user`` may be accountable for one more workspace.

        Superusers short-circuit before any query. Everyone else has their own
        ``auth.user`` row locked ``FOR UPDATE`` first: without it two concurrent
        creates from one actor both read ``count == 0`` and both succeed,
        breaching a cap whose whole point is "at most one". The lock is held
        until ``provision`` commits -- the guard and the write share one
        transaction on purpose.

        Counted over ``Workspace.owner_id``, never over the RBAC ``owner`` role:
        see ``WorkspaceRepository.count_by_owner``.

        ``user`` is whoever is about to become accountable, not necessarily the
        actor: ``owner_transfer`` runs this against the *recipient* (with its own
        ``detail``), because transferring away frees the sender's slot -- without
        that check one account could create, hand off and create again forever,
        which is the exact spam vector the cap exists to close.
        """
        if user.is_superuser:
            return
        await session.scalar(sa.select(AuthUser.id).where(AuthUser.id == user.id).with_for_update())
        limit = (await get_workspace_creation_config(session)).max_owned_per_user
        if await self.workspace_repo.count_by_owner(session, owner_id=user.id) >= limit:
            raise HTTPException(status_code=403, detail=detail)

    # --- transactional operations -------------------------------------------
    # Everything below owns a ``session.commit()``: the transport layer never
    # closes a transaction it did not open. The primitives above stay
    # commit-free so they compose (and so the DB integration tests can roll
    # their whole fixture back).

    async def provision(
        self,
        session: AsyncSession,
        *,
        payload: dict,
        owner_auth_user_id: int,
    ) -> models.Workspace:
        """Create a workspace with its system roles and its first owner.

        ``owner_id`` (accountability, for the self-service create cap) and the
        RBAC ``owner`` role grant below (permission) are two distinct writes for
        two distinct concerns, in one transaction -- neither replaces the other,
        and no actor is special-cased: a superuser-created workspace is owned by
        that superuser. ``verification_status`` is left to the column's
        ``server_default`` (``unverified``).
        """
        slug = payload.get("slug")
        if slug is not None and await self.get_by_slug(session, slug):
            raise HTTPException(status_code=400, detail="Workspace with this slug already exists")
        workspace = await self.create(session, owner_id=owner_auth_user_id, **payload)
        await ensure_workspace_system_roles(session, workspace.id)
        await self.add_member(session, workspace.id, owner_auth_user_id)
        await assign_workspace_system_role(
            session, user_id=owner_auth_user_id, workspace_id=workspace.id, role_name="owner"
        )
        await session.commit()
        # The workspace was built in Python and only flushed, so its
        # ``default_division_grid_version`` was never loaded -- ``selectin`` is
        # a query-time strategy and does not run for an instance that never
        # went through a SELECT. Reading it below would then lazy-load from
        # sync Pydantic code (MissingGreenlet) whenever the create body named
        # a version. Awaited here, it is ordinary IO.
        await session.refresh(workspace, ["default_division_grid_version"])
        return workspace

    async def backfill_member_roles(self, session: AsyncSession, workspace_id: int) -> int:
        assigned = await self.autofill_member_roles(session, workspace_id)
        await session.commit()
        return assigned

    async def resolve_member_role_ids(
        self,
        session: AsyncSession,
        workspace_id: int,
        *,
        role_ids: list[int] | None,
        role_name: str | None,
    ) -> list[int]:
        """Explicit ``role_ids`` win; otherwise the named workspace system role."""
        await ensure_workspace_system_roles(session, workspace_id)
        if role_ids is not None:
            return role_ids
        role = await get_workspace_system_role(session, workspace_id, role_name or "member")
        if role is None:
            raise HTTPException(status_code=500, detail="Workspace system role is not configured")
        return [role.id]

    async def invite_member(
        self,
        session: AsyncSession,
        workspace_id: int,
        auth_user_id: int,
        *,
        role_ids: list[int],
    ) -> models.WorkspaceMember:
        if await self.get_member(session, workspace_id, auth_user_id):
            raise HTTPException(status_code=400, detail="User is already a member")
        member = await self.add_member_with_roles(session, workspace_id, auth_user_id, role_ids=role_ids)
        await session.commit()
        return member

    async def change_member_roles(
        self,
        session: AsyncSession,
        member: models.WorkspaceMember,
        *,
        role_ids: list[int],
    ) -> models.WorkspaceMember:
        member = await self.update_member_roles(session, member, role_ids=role_ids)
        await session.commit()
        return member

    async def revoke_member(self, session: AsyncSession, member: models.WorkspaceMember) -> None:
        await self.remove_member(session, member)
        await session.commit()

    async def _record_domain_change(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        *,
        action: str,
        actor: typing.Any,
        workspace_id: int,
        before: dict,
        after: dict,
    ) -> None:
        """One ``audit_log`` row for a custom-domain change, staged inside the
        mutation's own transaction.

        ``workspace_id`` is the caller's authorization scope, passed in rather
        than read off ``workspace``: the audit scope must be the scope the
        permission check ran against.

        The ``custom_domain_verification_token`` is deliberately absent from
        both sides. It is not a platform secret (the organizer publishes it as a
        public DNS TXT record), but the journal is append-only and never purged,
        so every rotated challenge would pile up there forever while answering
        nothing an auditor asks -- "who re-pointed our domain" is answered by
        the domain itself.
        """
        await record_audit(
            session,
            action=action,
            source="admin",
            actor=actor,
            actor_label=actor.username,
            workspace_id=workspace_id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before=before,
            after=after,
        )

    async def apply_custom_domain(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        domain: str,
        *,
        actor: typing.Any,
        workspace_id: int,
    ) -> models.Workspace:
        domain_before = workspace.custom_domain
        verified_before = workspace.custom_domain_verified_at
        workspace = await self.set_custom_domain(session, workspace, domain)
        await self._record_domain_change(
            session,
            workspace,
            action="workspace.domain_set",
            actor=actor,
            workspace_id=workspace_id,
            before={"custom_domain": domain_before, "custom_domain_verified_at": _iso(verified_before)},
            # Re-pointing always resets verification, so the after side is known.
            after={"custom_domain": workspace.custom_domain, "custom_domain_verified_at": None},
        )
        await session.commit()
        return workspace

    async def confirm_custom_domain(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        *,
        actor: typing.Any,
        workspace_id: int,
    ) -> models.Workspace:
        verified_before = workspace.custom_domain_verified_at
        workspace = await self.verify_custom_domain(session, workspace)
        # Recorded after the mutation, not before it: ``verify_custom_domain``
        # commits once to release the connection across the DNS lookup, so a row
        # added earlier would survive a failed verification.
        #
        # ``custom_domain`` is unchanged and sits on both sides on purpose --
        # without it the row says a domain was verified without saying which one.
        await self._record_domain_change(
            session,
            workspace,
            action="workspace.domain_verified",
            actor=actor,
            workspace_id=workspace_id,
            before={"custom_domain": workspace.custom_domain, "custom_domain_verified_at": _iso(verified_before)},
            after={
                "custom_domain": workspace.custom_domain,
                "custom_domain_verified_at": _iso(workspace.custom_domain_verified_at),
            },
        )
        await session.commit()
        return workspace

    async def drop_custom_domain(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        *,
        actor: typing.Any,
        workspace_id: int,
    ) -> models.Workspace:
        domain_before = workspace.custom_domain
        verified_before = workspace.custom_domain_verified_at
        workspace = await self.clear_custom_domain(session, workspace)
        # Token value omitted for the reason given in _record_domain_change; that
        # it was dropped follows from the domain going away.
        await self._record_domain_change(
            session,
            workspace,
            action="workspace.domain_clear",
            actor=actor,
            workspace_id=workspace_id,
            before={"custom_domain": domain_before, "custom_domain_verified_at": _iso(verified_before)},
            after={"custom_domain": None, "custom_domain_verified_at": None},
        )
        await session.commit()
        return workspace

    # --- Discord guild verification (self-service design §4.1) -------------

    async def verify_discord_guild(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        guild_id: str,
        *,
        actor: typing.Any,
        broker: typing.Any,
    ) -> models.Workspace:
        """Bind ``guild_id`` to ``workspace`` after proving ``actor`` administers
        it on Discord.

        Fails **closed**: an identity-service outage or an unusable reply
        rejects the bind with 503, it never silently skips the ownership check.
        This is the opposite direction from the Boosty subscription resolver
        (which fails open on a missing/unreachable guild config) -- there, a
        missing answer only widens who can register for a tournament; here, it
        would let an unproven claim permanently attach to a workspace's
        identity. See the design's Risks section.

        Raises ``HTTPException(403)`` if ``actor`` does not administer
        ``guild_id`` on Discord (owner or ``MANAGE_GUILD``, per
        ``rpc.identity.oauth_discord_guilds``).

        Raises ``HTTPException(409)`` if another workspace already claims this
        guild -- the ``uq_workspace_discord_guild_id`` unique constraint is the
        authoritative check (no separate pre-check like the custom-domain flow
        has: a guild-id collision is rare enough that a TOCTOU-safe
        ``IntegrityError`` catch alone is proportionate).
        """
        try:
            reply = await request_rpc(broker, {"auth_user_id": actor.id}, _DISCORD_GUILDS_SUBJECT, timeout=5.0)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=_GUILD_UNREACHABLE_MESSAGE) from exc
        if reply is None or not reply.ok:
            raise HTTPException(status_code=503, detail=_GUILD_UNREACHABLE_MESSAGE)

        payload = reply.data if isinstance(reply.data, dict) else {}
        guilds = payload.get("guilds") or []
        administered = {g["guild_id"] for g in guilds if g.get("can_manage")}
        if guild_id not in administered:
            raise HTTPException(status_code=403, detail="You do not administer this Discord guild")

        guild_id_before = workspace.discord_guild_id
        verified_at_before = workspace.discord_guild_verified_at
        try:
            await self.workspace_repo.update_fields(
                session,
                workspace,
                {
                    "discord_guild_id": guild_id,
                    "discord_guild_verified_at": datetime.now(UTC),
                    "discord_guild_verified_by_auth_user_id": actor.id,
                },
            )
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail=_GUILD_CONFLICT_MESSAGE) from exc

        await record_audit(
            session,
            action="workspace.discord_guild_verified",
            source="admin",
            actor=actor,
            actor_label=actor.username,
            workspace_id=workspace.id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before={"discord_guild_id": guild_id_before, "discord_guild_verified_at": _iso(verified_at_before)},
            after={
                "discord_guild_id": workspace.discord_guild_id,
                "discord_guild_verified_at": _iso(workspace.discord_guild_verified_at),
            },
        )
        await session.commit()
        return workspace

    async def clear_discord_guild(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        *,
        actor: typing.Any,
    ) -> models.Workspace:
        """Unbind the Discord guild from ``workspace``.

        Workspace.update is enough: this is the admin override that lets an
        organiser leave a server they can no longer prove they administer, or
        free the unique guild-id so another workspace can claim it. Discord is
        not re-asked -- the bind already proved ownership, and requiring it
        again would strand a workspace whose bot was kicked.

        Idempotent: clearing an already-unbound workspace is a no-op with no
        extra audit row.
        """
        guild_id_before = workspace.discord_guild_id
        verified_at_before = workspace.discord_guild_verified_at
        if guild_id_before is None and verified_at_before is None:
            return workspace

        await self.workspace_repo.update_fields(
            session,
            workspace,
            {
                "discord_guild_id": None,
                "discord_guild_verified_at": None,
                "discord_guild_verified_by_auth_user_id": None,
            },
        )
        await record_audit(
            session,
            action="workspace.discord_guild_cleared",
            source="admin",
            actor=actor,
            actor_label=actor.username,
            workspace_id=workspace.id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before={"discord_guild_id": guild_id_before, "discord_guild_verified_at": _iso(verified_at_before)},
            after={"discord_guild_id": None, "discord_guild_verified_at": None},
        )
        await session.commit()
        return workspace

    async def list_actor_discord_guilds(self, *, auth_user_id: int, broker: typing.Any) -> dict:
        """The guilds ``auth_user_id`` administers, straight from identity-service.

        Exists so the browser can render a guild picker before calling
        ``verify_discord_guild`` -- the frontend cannot reach ``rpc.identity.*``
        itself. Same subject, same timeout and the same fail-closed 503 as the
        verification call it feeds: an empty list would read as "you administer
        nothing", which is a different (and misleading) answer from "we could
        not ask".
        """
        try:
            reply = await request_rpc(broker, {"auth_user_id": auth_user_id}, _DISCORD_GUILDS_SUBJECT, timeout=5.0)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=_GUILD_UNREACHABLE_MESSAGE) from exc
        if reply is None or not reply.ok or not isinstance(reply.data, dict):
            raise HTTPException(status_code=503, detail=_GUILD_UNREACHABLE_MESSAGE)
        return {"guilds": reply.data.get("guilds") or []}

    # --- verification tier (design §4.3) -----------------------------------

    async def set_verification_status(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        status: str,
        *,
        actor: typing.Any,
    ) -> models.Workspace:
        """Superuser-only tier move; the caller owns the permission gate.

        Audited unconditionally, including a no-op set to the status the
        workspace already has: this is the single switch that unblocks GPU
        compute and public listing, so "a superuser looked at this and
        re-affirmed it" is exactly the kind of trail worth keeping (same
        posture as the custom-domain edits above).
        """
        status_before = workspace.verification_status
        await self.workspace_repo.update_fields(session, workspace, {"verification_status": status})
        await record_audit(
            session,
            action="workspace.verification_status_set",
            source="admin",
            actor=actor,
            actor_label=actor.username,
            workspace_id=workspace.id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before={"verification_status": status_before},
            after={"verification_status": workspace.verification_status},
        )
        await session.commit()
        return workspace

    # --- owner (accountability) ---------------------------------------------

    async def set_owner(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        owner_id: int | None,
        *,
        actor: typing.Any,
    ) -> models.Workspace:
        """Superuser-only owner reassignment; the caller owns the permission gate
        and has already proven ``owner_id`` names a real ``auth.user`` row.

        Two things this deliberately does NOT do. It does not touch RBAC: the
        stamp and the ``owner`` role are decoupled by design (§4.4), so who may
        administer the workspace stays a ``member_update`` decision. And it does
        not re-check ``max_owned_per_user`` -- that cap gates self-service
        creation, and a superuser assignment is exactly the override for it; the
        new owner is simply counted from here on.

        Audited unconditionally, a no-op set included: this moves who answers for
        a workspace, same posture as ``set_verification_status``.
        """
        owner_before = workspace.owner_id
        await self.workspace_repo.update_fields(session, workspace, {"owner_id": owner_id})
        await record_audit(
            session,
            action="workspace.owner_set",
            source="admin",
            actor=actor,
            actor_label=actor.username,
            workspace_id=workspace.id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before={"owner_id": owner_before},
            after={"owner_id": workspace.owner_id},
        )
        await session.commit()
        return workspace

    async def transfer_ownership(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        new_owner_auth_user_id: int,
        *,
        actor: typing.Any,
    ) -> models.Workspace:
        """Hand a workspace over: the accountability stamp AND the ``owner`` role.

        This is the difference from ``set_owner``. That one is a superuser fixing
        a stamp; this is the workspace changing hands, so the RBAC side has to
        move too or the new owner would answer for a workspace they cannot
        administer. The caller owns the permission gate (current owner or
        superuser), the recipient's ownership cap and the ``auth.user`` existence
        check.

        Order is load-bearing. The recipient is granted ``owner`` *before* the
        outgoing owner loses it, so the "last owner" invariant
        (``user_has_only_workspace_owner_role``, enforced on the members screen)
        is never momentarily violated -- there are two owners in between, never
        zero.

        The outgoing owner keeps their membership and every other role they hold;
        only ``owner`` is taken, and ``member`` steps in if that leaves them with
        nothing. Losing the workspace is not the same as being thrown out of it.
        """
        owner_before = workspace.owner_id

        await self.add_member(session, workspace.id, new_owner_auth_user_id)
        await assign_workspace_system_role(
            session, user_id=new_owner_auth_user_id, workspace_id=workspace.id, role_name="owner"
        )

        if owner_before is not None and owner_before != new_owner_auth_user_id:
            kept = [
                role.id
                for role in await self.get_member_workspace_roles(session, workspace.id, owner_before)
                if role.name != "owner"
            ]
            await replace_user_workspace_roles(session, user_id=owner_before, workspace_id=workspace.id, role_ids=kept)
            await assign_default_member_role_if_roleless(session, user_id=owner_before, workspace_id=workspace.id)

        await self.workspace_repo.update_fields(session, workspace, {"owner_id": new_owner_auth_user_id})
        await record_audit(
            session,
            action="workspace.ownership_transferred",
            source="admin",
            actor=actor,
            actor_label=actor.username,
            workspace_id=workspace.id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before={"owner_id": owner_before},
            after={"owner_id": workspace.owner_id},
        )
        await session.commit()
        return workspace


workspaces = WorkspaceService()
