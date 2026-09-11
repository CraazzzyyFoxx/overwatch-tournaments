"""Workspace typed-RPC subscribers: public reads + create + member management.

Reads (list/get) are public. create is open to any ACTIVE authenticated user,
capped per account (``ensure_create_limit``) and slug-filtered against the
platform's reserved slugs; the tier RPC that lifts a new workspace out of
``unverified`` (``verification_set``) is the superuser-only half. Member ops are
workspace-scoped (workspace_member.{read,create,update,delete}). workspace
update/delete go through the shared CRUD engine (see services/workspace/registry.py
+ rpc/admin_crud.py). The custom-domain set/verify/clear trio (white-label Phase
2) is bespoke too — like member ops, gated on the workspace-scoped
``workspace.update`` permission — since verification has a side effect (a DNS
lookup) the generic CRUD engine has no hook for.

This module is pure transport: it decodes params, runs the permission gate and
calls one ``WorkspaceService`` operation. The service owns the transaction and
the ``audit_log`` row for each bespoke mutation, so the trail lives or dies with
the write. The workspace's own field updates are NOT audited from here at all:
they go through the shared CRUD engine, which records them at its single hook.

The member-payload / RBAC-cache-bust helpers stay here so the headless worker
never depends on route internals. Role resolution lives on ``WorkspaceService``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from faststream.rabbit import RabbitMessage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import Paginated
from shared.rbac import RBAC_USER_KEY_PREFIX
from shared.repository import AuthUserRepository
from shared.rpc.identity import ensure_workspace_permission, rehydrate_user_optional
from shared.services.audit import record_admin_audit
from shared.services.discord_client import DiscordClient
from shared.services.subscriptions.providers.discord_role import DiscordError
from shared.tenancy.hostnames import normalize_custom_domain, subdomain_from_host
from src import models, schemas
from src.core import config, db
from src.rpc import _common as c
from src.services.workspace.service import MEMBERS_SORT_FIELDS, reject_reserved_slug
from src.services.workspace.service import workspaces as workspace_service

_SF = db.async_session_maker
_auth_user_repo = AuthUserRepository()
# The three shapes `workspaces.list` serves; anything else is a 422 rather
# than a silent fallback to the widest one (see `_list`).
_LIST_SCOPES = ("public", "admin", "all")


def _path_int(data: dict[str, Any], key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} is required") from exc


async def _invalidate_auth_rbac_cache(auth_user_id: int, logger: Any) -> None:
    redis = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
    try:
        await redis.delete(f"{RBAC_USER_KEY_PREFIX}{auth_user_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to invalidate auth RBAC cache for user %s: %s", auth_user_id, exc)
    finally:
        await redis.aclose()


async def _member_payload(session: AsyncSession, member: models.WorkspaceMember) -> schemas.WorkspaceMemberRead:
    auth_user_id = await workspace_service.get_member_auth_user_id(session, member)
    auth_user = await _auth_user_repo.get(session, auth_user_id)
    roles = await workspace_service.get_member_workspace_roles(session, member.workspace_id, auth_user_id)
    return schemas.WorkspaceMemberRead.model_validate(
        {
            "id": member.id,
            "created_at": member.created_at,
            "updated_at": member.updated_at,
            "workspace_id": member.workspace_id,
            "auth_user_id": auth_user_id,
            "username": auth_user.username if auth_user else None,
            "email": auth_user.email if auth_user else None,
            "first_name": auth_user.first_name if auth_user else None,
            "last_name": auth_user.last_name if auth_user else None,
            "avatar_url": auth_user.avatar_url if auth_user else None,
            "rbac_roles": roles,
        }
    )


def _member_read(
    member: models.WorkspaceMember,
    auth_user: models.AuthUser,
    roles: list[models.Role],
) -> schemas.WorkspaceMemberRead:
    """Build a member payload from already-loaded rows (no queries) — the batched
    counterpart of ``_member_payload``. ``rbac_roles`` are Role ORM objects that
    Pydantic validates via ``from_attributes`` (incl. ``is_system``); system
    roles sort before custom, then by name."""
    return schemas.WorkspaceMemberRead.model_validate(
        {
            "id": member.id,
            "created_at": member.created_at,
            "updated_at": member.updated_at,
            "workspace_id": member.workspace_id,
            "auth_user_id": auth_user.id,
            "username": auth_user.username,
            "email": auth_user.email,
            "first_name": auth_user.first_name,
            "last_name": auth_user.last_name,
            "avatar_url": auth_user.avatar_url,
            "rbac_roles": sorted(roles, key=lambda role: (not role.is_system, role.name)),
        }
    )


async def _owner_payload(session: AsyncSession, workspace: models.Workspace) -> schemas.WorkspaceOwnerRead | None:
    """``Workspace.owner_id`` resolved to a person, or ``None`` when unstamped.

    Same transport-level enrichment as ``_member_payload``: one auth-user read
    keyed by an id the workspace row already carries. ``owner_id`` is nullable
    by design (workspaces predating self-service, and the FK is ``SET NULL``),
    and so is the answer -- "nobody is on the hook for this one" is a fact the
    admin screens have to be able to render.
    """
    owner_id = workspace.owner_id
    if owner_id is None:
        return None
    auth_user = await _auth_user_repo.get(session, owner_id)
    return schemas.WorkspaceOwnerRead(
        auth_user_id=owner_id,
        username=auth_user.username if auth_user else None,
        email=auth_user.email if auth_user else None,
        first_name=auth_user.first_name if auth_user else None,
        last_name=auth_user.last_name if auth_user else None,
        avatar_url=auth_user.avatar_url if auth_user else None,
    )


async def _discord_lookup(
    broker: Any,
    logger: Any,
    session: AsyncSession,
    data: dict[str, Any],
    *,
    label: str,
    read: Callable[[DiscordClient, str], Awaitable[Any]],
    key: str | None,
    empty: dict[str, Any],
    degraded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One gated read of an organizer's Discord guild, shared by the three
    ``discord_*`` subscribers.

    ``read`` is the ``DiscordClient`` method to call (discord-service first,
    Discord REST when it is down); ``key`` wraps a list result under that name.
    ``empty`` is the body returned when no guild is linked; ``degraded``
    (defaulting to ``empty``) is the body carrying the ``error`` when both
    transports fail. A settings picker with no options is the right answer for
    an unreachable bot — a 500 would take the whole settings page down with it.
    """
    workspace_id = _path_int(data, "workspace_id")
    user = c.actor(data)
    c.require_active(user)
    ensure_workspace_permission(user, workspace_id, "workspace", "update")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    guild_id = workspace.discord_guild_id
    if not guild_id:
        return {"guild_id": None, **empty}

    discord = DiscordClient(
        broker=broker, bot_token=config.settings.discord_token, proxy=config.settings.proxy_url
    )
    try:
        result = await read(discord, guild_id)
    except DiscordError as exc:  # the pickers degrade, they never 500
        logger.warning(f"{label} lookup failed for workspace {workspace_id}: {exc}")
        return {"guild_id": guild_id, **(degraded if degraded is not None else empty), "error": str(exc)}
    body = {key: result} if key is not None else dict(result)
    body.setdefault("guild_id", guild_id)
    return body


def register(broker: Any, logger: Any) -> None:
    # --- public reads -------------------------------------------------------
    @broker.subscriber("rpc.app.workspaces.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        """``?scope=public|admin|all`` (default ``public``).

        ``public`` is the directory the home page renders and is identical for
        every caller, superusers included: hidden and ``unverified``
        workspaces are absent, full stop. ``admin`` is the management list
        (superuser: everything; otherwise the caller's own workspaces at any
        tier) and ``all`` is that unioned with the public directory, for the
        workspace switcher.
        """

        async def op(session: Any) -> Any:
            scope = c.q1(data, "scope", str, "public")
            if scope not in _LIST_SCOPES:
                raise HTTPException(status_code=422, detail="scope must be one of public, admin, all")
            viewer = rehydrate_user_optional(data.get("identity"))
            workspaces = await workspace_service.get_all(session, user=viewer, scope=scope)
            return [schemas.WorkspaceRead.model_validate(w, from_attributes=True) for w in workspaces]

        return await c.envelope(logger, "workspaces.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await workspace_service.get_by_id(session, c.require_id(data))
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.by_host")
    async def by_host(data: dict, msg: RabbitMessage) -> dict:
        """Resolve a request host to its workspace: ``{workspace_id, slug}``.

        Public (no auth). Matches either a platform-zone subdomain
        (``subdomain_from_host`` against ``Workspace.subdomain``) or, for any
        other host, a VERIFIED custom domain (``normalize_custom_domain``
        against ``Workspace.custom_domain`` + ``custom_domain_verified_at``).
        Returns ``data: None`` when the host is missing, invalid, or matches
        no workspace — an unverified custom domain never resolves (fail-closed).
        """

        async def op(session: Any) -> Any:
            host = c.q1(data, "host", str, None)
            if not host:
                return None
            label = subdomain_from_host(host)
            if label is not None:
                workspace = await workspace_service.get_by_subdomain(session, label)
            else:
                try:
                    domain = normalize_custom_domain(host)
                except ValueError:
                    return None
                workspace = await workspace_service.get_by_custom_domain(session, domain)
            if workspace is None:
                return None
            return {"workspace_id": workspace.id, "slug": workspace.slug}

        return await c.envelope(logger, "workspaces.by_host", op, session_factory=_SF)

    # --- create (any active user with the capability, capped) ---------------
    @broker.subscriber("rpc.app.workspaces.create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            # Allow-by-default capability, revocable per account through the
            # negative-RBAC deny list (same shape as ``account.social`` and
            # ``registration.self_register``). Checked before the cap because a
            # revoked account has no business learning how full it is.
            if not user.can_capability("workspace", "self_create"):
                raise HTTPException(status_code=403, detail="You are not allowed to create workspaces")
            await workspace_service.ensure_create_limit(session, user)
            body = schemas.WorkspaceCreate.model_validate(c.payload(data))
            reject_reserved_slug(body.slug)
            workspace = await workspace_service.provision(
                session, payload=body.model_dump(), owner_auth_user_id=user.id
            )
            # provision already committed; this row is a second transaction so it
            # can name the new id. A crash between the two loses the trail, never
            # the workspace — same ceiling as CRUD service_create.
            await record_admin_audit(
                session,
                action="workspace.create",
                actor=user,
                data=data,
                workspace_id=workspace.id,
                entity_type="workspace",
                entity_id=workspace.id,
                entity_label=workspace.name,
                after={"name": body.name, "slug": body.slug},
            )
            await session.commit()
            await _invalidate_auth_rbac_cache(int(user.id), logger)
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.create", op, session_factory=_SF)

    # --- members ------------------------------------------------------------
    @broker.subscriber("rpc.app.workspaces.members_list")
    async def _members_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "read")
            if not await workspace_service.get_by_id(session, workspace_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            page = max(c.q1(data, "page", int, 1) or 1, 1)
            per_page = c.q1(data, "per_page", int, 20)
            if per_page != -1:
                per_page = min(max(per_page, 1), 100)
            search = c.q1(data, "search", str, None)
            role_id = c.q1(data, "role_id", int, None)
            sort = c.q1(data, "sort", str, "username")
            if sort not in MEMBERS_SORT_FIELDS:
                sort = "username"
            order = "desc" if c.q1(data, "order", str, "asc") == "desc" else "asc"
            total, rows = await workspace_service.list_members_page(
                session,
                workspace_id,
                page=page,
                per_page=per_page,
                search=search,
                role_id=role_id,
                sort=sort,
                order=order,
            )
            return Paginated(
                page=page,
                per_page=per_page,
                total=total,
                results=[_member_read(member, auth_user, roles) for (member, auth_user, roles) in rows],
            )

        return await c.envelope(logger, "workspaces.members_list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.members_autofill_roles")
    async def _members_autofill_roles(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "update")
            if not await workspace_service.get_by_id(session, workspace_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            # ``backfill_member_roles`` commits, so ``assigned`` is only known
            # after the row would have to be written -- action and scope only.
            await record_admin_audit(
                session,
                action="workspace.member_roles_backfill",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="workspace",
                entity_id=workspace_id,
            )
            assigned = await workspace_service.backfill_member_roles(session, workspace_id)
            return {"assigned": assigned}

        return await c.envelope(logger, "workspaces.members_autofill_roles", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.member_add")
    async def _member_add(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "create")
            if not await workspace_service.get_by_id(session, workspace_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            body = schemas.WorkspaceMemberCreate.model_validate(c.payload(data))
            if await _auth_user_repo.get(session, body.auth_user_id) is None:
                raise HTTPException(status_code=404, detail="Auth user not found")
            role_ids = await workspace_service.resolve_member_role_ids(
                session, workspace_id, role_ids=body.role_ids, role_name=body.role
            )
            await record_admin_audit(
                session,
                action="workspace.member_add",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="workspace",
                entity_id=workspace_id,
                after={"auth_user_id": body.auth_user_id, "role_ids": role_ids},
            )
            try:
                member = await workspace_service.invite_member(
                    session, workspace_id, body.auth_user_id, role_ids=role_ids
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload = await _member_payload(session, member)
            await _invalidate_auth_rbac_cache(body.auth_user_id, logger)
            return payload

        return await c.envelope(logger, "workspaces.member_add", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.member_update")
    async def _member_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            auth_user_id = _path_int(data, "auth_user_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "update")
            member = await workspace_service.get_member(session, workspace_id, auth_user_id)
            if not member:
                raise HTTPException(status_code=404, detail="Member not found")
            body = schemas.WorkspaceMemberUpdate.model_validate(c.payload(data))
            if body.role_ids is None and body.role is None:
                raise HTTPException(status_code=400, detail="role_ids or role is required")
            role_ids = await workspace_service.resolve_member_role_ids(
                session, workspace_id, role_ids=body.role_ids, role_name=body.role
            )
            await record_admin_audit(
                session,
                action="workspace.member_update",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="workspace",
                entity_id=workspace_id,
                after={"auth_user_id": auth_user_id, "role_ids": role_ids},
            )
            try:
                member = await workspace_service.change_member_roles(session, member, role_ids=role_ids)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload = await _member_payload(session, member)
            await _invalidate_auth_rbac_cache(auth_user_id, logger)
            return payload

        return await c.envelope(logger, "workspaces.member_update", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.member_remove")
    async def _member_remove(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            auth_user_id = _path_int(data, "auth_user_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace_member", "delete")
            member = await workspace_service.get_member(session, workspace_id, auth_user_id)
            if not member:
                raise HTTPException(status_code=404, detail="Member not found")
            if not await workspace_service.can_remove_member(session, member):
                raise HTTPException(status_code=400, detail="Cannot remove the last workspace owner")
            await record_admin_audit(
                session,
                action="workspace.member_remove",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="workspace",
                entity_id=workspace_id,
                after={"auth_user_id": auth_user_id},
            )
            await workspace_service.revoke_member(session, member)
            await _invalidate_auth_rbac_cache(auth_user_id, logger)
            return None

        return await c.envelope(logger, "workspaces.member_remove", op, session_factory=_SF)

    # --- custom domain (white-label Phase 2) --------------------------------
    @broker.subscriber("rpc.app.workspaces.set_custom_domain")
    async def _set_custom_domain(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            body = schemas.WorkspaceCustomDomainSet.model_validate(c.payload(data))
            try:
                workspace = await workspace_service.apply_custom_domain(
                    session, workspace, body.custom_domain, actor=user, workspace_id=workspace_id
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.set_custom_domain", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.verify_custom_domain")
    async def _verify_custom_domain(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            workspace = await workspace_service.confirm_custom_domain(
                session, workspace, actor=user, workspace_id=workspace_id
            )
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.verify_custom_domain", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.clear_custom_domain")
    async def _clear_custom_domain(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            workspace = await workspace_service.drop_custom_domain(
                session, workspace, actor=user, workspace_id=workspace_id
            )
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.clear_custom_domain", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.discord_guild_verify")
    async def _discord_guild_verify(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            body = schemas.WorkspaceDiscordGuildVerify.model_validate(c.payload(data))
            workspace = await workspace_service.verify_discord_guild(
                session, workspace, body.guild_id, actor=user, broker=broker
            )
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.discord_guild_verify", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.discord_guild_clear")
    async def _discord_guild_clear(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            workspace = await workspace_service.clear_discord_guild(session, workspace, actor=user)
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.discord_guild_clear", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.my_discord_guilds")
    async def _my_discord_guilds(data: dict, msg: RabbitMessage) -> dict:
        """The caller's own administered guilds — actor-scoped, no workspace.

        Thin passthrough to identity-service so the guild picker in front of
        ``discord_guild_verify`` has something to render. No session work at
        all, but it still runs inside the standard envelope/session factory:
        the transport shape is what every other subscriber here shares.
        """

        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            return await workspace_service.list_actor_discord_guilds(auth_user_id=user.id, broker=broker)

        return await c.envelope(logger, "workspaces.my_discord_guilds", op, session_factory=_SF)

    # --- verification tier (superuser) --------------------------------------
    @broker.subscriber("rpc.app.workspaces.verification_set")
    async def _verification_set(data: dict, msg: RabbitMessage) -> dict:
        """Superuser-only, deliberately stricter than ``workspace.update``:
        being an owner of a workspace must not let you self-certify it."""

        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_superuser(user)
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            body = schemas.WorkspaceVerificationSet.model_validate(c.payload(data))
            workspace = await workspace_service.set_verification_status(
                session, workspace, body.verification_status, actor=user
            )
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.verification_set", op, session_factory=_SF)

    # --- owner (accountability) ---------------------------------------------
    @broker.subscriber("rpc.app.workspaces.owner_get")
    async def _owner_get(data: dict, msg: RabbitMessage) -> dict:
        """Who is accountable for this workspace.

        ``workspace.update``-gated for the same reason the ``discord_*`` reads
        are: this resolves an internal ``auth_user_id`` to a name and an email,
        which the public ``WorkspaceRead`` deliberately refuses to publish.
        """

        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            return await _owner_payload(session, workspace)

        return await c.envelope(logger, "workspaces.owner_get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.owner_set")
    async def _owner_set(data: dict, msg: RabbitMessage) -> dict:
        """Assign or clear the accountable owner.

        Superuser-only, deliberately stricter than the ``workspace.update`` gate
        on the read next to it: ``owner_id`` is what the per-account create cap
        is counted over, so an organizer who could reassign it could hand their
        own cap away — or appoint an account that never agreed to answer for
        anything. The target account is resolved here rather than left to the FK,
        so an unknown id is a 404 instead of an integrity error.
        """

        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_superuser(user)
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            body = schemas.WorkspaceOwnerSet.model_validate(c.payload(data))
            if body.auth_user_id is not None and not await _auth_user_repo.get(session, body.auth_user_id):
                raise HTTPException(status_code=404, detail="Auth user not found")
            workspace = await workspace_service.set_owner(session, workspace, body.auth_user_id, actor=user)
            return await _owner_payload(session, workspace)

        return await c.envelope(logger, "workspaces.owner_set", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.owner_transfer")
    async def _owner_transfer(data: dict, msg: RabbitMessage) -> dict:
        """Hand the workspace over — stamp and ``owner`` role together.

        Open to the workspace's own current owner, not just a superuser: this is
        the self-service half of ownership, and the person on the hook is the one
        entitled to get off it. Everyone else is refused, ``workspace.update``
        holders included — a co-administrator must not be able to give away a
        workspace they do not answer for. An unowned workspace has nobody to hand
        it off, so only a superuser can seed one (via ``owner_set``).

        The recipient's ownership cap is enforced unless the actor is a
        superuser: without it, create → transfer → create would mint workspaces
        forever past ``max_owned_per_user``.
        """

        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            user = c.actor(data)
            c.require_active(user)
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            if not user.is_superuser and workspace.owner_id != user.id:
                raise HTTPException(status_code=403, detail="Only the workspace owner may transfer ownership")
            body = schemas.WorkspaceOwnerTransfer.model_validate(c.payload(data))
            recipient = await _auth_user_repo.get(session, body.auth_user_id)
            if not recipient:
                raise HTTPException(status_code=404, detail="Auth user not found")
            if not user.is_superuser:
                await workspace_service.ensure_create_limit(session, recipient, detail="workspace_owner_limit_reached")
            previous_owner_id = workspace.owner_id
            workspace = await workspace_service.transfer_ownership(session, workspace, body.auth_user_id, actor=user)
            # Both sides' permissions changed, so both cached RBAC payloads are
            # stale -- same bust the member ops do after a role write.
            for auth_user_id in {body.auth_user_id, previous_owner_id} - {None}:
                await _invalidate_auth_rbac_cache(auth_user_id, logger)
            return await _owner_payload(session, workspace)

        return await c.envelope(logger, "workspaces.owner_transfer", op, session_factory=_SF)

    # --- Discord entities (roles, channels, server status) ------------------
    # Reads of an organizer's own server config, so they carry the same
    # workspace.update gate as the custom-domain endpoints above: the role and
    # channel lists (and the server's name and headcount) are private to the
    # guild, and these only ever back the workspace settings pickers.
    @broker.subscriber("rpc.app.workspaces.discord_roles")
    async def _discord_roles(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await _discord_lookup(
                broker,
                logger,
                session,
                data,
                label="discord_roles",
                read=DiscordClient.guild_roles,
                key="roles",
                empty={"roles": []},
            )

        return await c.envelope(logger, "workspaces.discord_roles", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.discord_channels")
    async def _discord_channels(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await _discord_lookup(
                broker,
                logger,
                session,
                data,
                label="discord_channels",
                read=DiscordClient.guild_channels,
                key="channels",
                empty={"channels": []},
            )

        return await c.envelope(logger, "workspaces.discord_channels", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.discord_guild")
    async def _discord_guild(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await _discord_lookup(
                broker,
                logger,
                session,
                data,
                label="discord_guild",
                read=DiscordClient.guild_info,
                key=None,
                empty={
                    "connected": False,
                    "name": None,
                    "icon_url": None,
                    "member_count": 0,
                    "owner_id": None,
                    "owner_name": None,
                    "owner_avatar_url": None,
                },
                # A failed round trip only knows the guild is unreachable; the rest
                # of the shape would be inventing values the caller must not trust.
                degraded={"connected": False},
            )

        return await c.envelope(logger, "workspaces.discord_guild", op, session_factory=_SF)
