"""Workspace typed-RPC subscribers: public reads + create + member management.

Reads (list/get) are public. create is open to any ACTIVE authenticated user,
capped per account (``ensure_create_limit``) and slug-filtered against the
platform's reserved slugs; the tier RPC that lifts a new workspace out of
``unverified`` (``verification_set``) is the superuser-only half. Member ops are
workspace-scoped (workspace_member.{read,create,update,delete}); granting or
revoking the ``owner`` role additionally takes ``owner`` there (or a superuser,
``ensure_owner_role_change_allowed``). workspace
update/delete go through the shared CRUD engine (see services/workspace/registry.py
+ rpc/admin_crud.py). The custom-domain set/verify/clear trio is bespoke too —
like member ops, gated on the workspace-scoped ``workspace.update`` permission —
since verification has a side effect (a DNS lookup) the generic CRUD engine has
no hook for.

Each handler decodes params, runs the permission gate and calls one service
operation. A bespoke mutation's ``audit_log`` row is staged on the session the
service commits, so the trail lives or dies with the write (``create`` records
it in a second transaction, once the new id exists). The workspace's own field
updates are NOT audited from here at all: they go through the shared CRUD
engine, which records them at its single hook.

Role resolution lives on ``WorkspaceService``, and so does the
``WorkspaceMemberChangedEvent`` every membership write stages for identity's
RBAC cache.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import Paginated
from shared.disciplines import DISCIPLINES
from shared.repository import AuthUserRepository
from shared.rpc.identity import ensure_workspace_permission, rehydrate_user_optional
from shared.rpc.query import parse_id_list
from shared.schemas.team_format import TeamFormatWrite
from shared.services.audit import record_admin_audit
from shared.services.discord_client import DiscordClient
from shared.services.team_format import save_workspace_format, team_format_read, workspace_format
from shared.tenancy.hostnames import normalize_custom_domain, subdomain_from_host
from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services import notification_config
from src.services.admin.quota import quota_admin_service
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


def _avatar_url(auth_user: models.AuthUser | None) -> str | None:
    """An account's avatar is its player's (``players.user.avatar_url``); ``player`` must already be loaded."""
    player = auth_user.player if auth_user else None
    return player.avatar_url if player else None


async def _member_payload(session: AsyncSession, member: models.WorkspaceMember) -> schemas.WorkspaceMemberRead:
    auth_user_id = await workspace_service.get_member_auth_user_id(session, member)
    auth_user = await _auth_user_repo.get_identity(session, auth_user_id, include_player=True)
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
            "avatar_url": _avatar_url(auth_user),
            "rbac_roles": roles,
        }
    )


def _member_read(
    member: models.WorkspaceMember,
    auth_user: models.AuthUser,
    roles: list[models.Role],
) -> schemas.WorkspaceMemberRead:
    """Build a member payload from already-loaded rows (no queries) — the batched
    counterpart of ``_member_payload``; ``auth_user.player`` comes eager from the
    page query. ``rbac_roles`` are Role ORM objects that Pydantic validates via
    ``from_attributes`` (incl. ``is_system``); system roles sort before custom,
    then by name."""
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
            "avatar_url": _avatar_url(auth_user),
            "rbac_roles": sorted(roles, key=lambda role: (not role.is_system, role.name)),
        }
    )


async def _owner_payload(session: AsyncSession, workspace: models.Workspace) -> schemas.WorkspaceOwnerRead | None:
    """``Workspace.owner_id`` resolved to a person, or ``None`` when unstamped.

    Same transport-level enrichment as ``_member_payload``: one auth-user read
    (its player eager, for the avatar) keyed by an id the workspace row already
    carries. ``owner_id`` is nullable by design (workspaces predating
    self-service, and the FK is ``SET NULL``), and so is the answer -- "nobody is
    on the hook for this one" is a fact the admin screens have to be able to
    render.
    """
    owner_id = workspace.owner_id
    if owner_id is None:
        return None
    auth_user = await _auth_user_repo.get_identity(session, owner_id, include_player=True)
    return schemas.WorkspaceOwnerRead(
        auth_user_id=owner_id,
        username=auth_user.username if auth_user else None,
        email=auth_user.email if auth_user else None,
        first_name=auth_user.first_name if auth_user else None,
        last_name=auth_user.last_name if auth_user else None,
        avatar_url=_avatar_url(auth_user),
    )


async def _gate_workspace(session: AsyncSession, data: dict[str, Any]) -> models.Workspace:
    """The workspace named by the path, once the caller may administer it.

    The same three lines every ``workspace_id``-scoped settings handler opens
    with: active identity, ``workspace.update`` in *that* workspace, and a 404
    for a workspace that is not there.
    """
    workspace_id = _path_int(data, "workspace_id")
    user = c.actor(data)
    c.require_active(user)
    ensure_workspace_permission(user, workspace_id, "workspace", "update")
    workspace = await workspace_service.get_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _discipline(data: dict[str, Any]) -> str:
    code = str(data.get("discipline") or "")
    if code not in DISCIPLINES:
        raise HTTPException(status_code=404, detail="Discipline not found")
    return code


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
            return [schemas.WorkspaceListItem.model_validate(w, from_attributes=True) for w in workspaces]

        return await c.envelope(logger, "workspaces.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await workspace_service.get_by_id(session, c.require_id(data))
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.by_slug")
    async def _by_slug(data: dict, msg: RabbitMessage) -> dict:
        """``?slug=``: the community page's workspace, 404 unless ``scope=all`` would list it for the viewer."""

        async def op(session: Any) -> Any:
            slug = c.q1(data, "slug", str, "")
            viewer = rehydrate_user_optional(data.get("identity"))
            workspace = await workspace_service.get_visible_by_slug(session, slug, user=viewer)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.by_slug", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.staff")
    async def _staff(data: dict, msg: RabbitMessage) -> dict:
        """Who runs this workspace: ``[{role, name}]``, public.

        Same visibility as ``get`` above (404 only when the workspace does not
        exist): hidden workspaces stay reachable by id, they are merely absent
        from the directory.
        """

        async def op(session: Any) -> Any:
            workspace_id = _path_int(data, "workspace_id")
            if not await workspace_service.get_by_id(session, workspace_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            staff = await workspace_service.get_staff(session, workspace_id)
            return [schemas.WorkspaceStaffMember.model_validate({"role": role, "name": name}) for role, name in staff]

        return await c.envelope(logger, "workspaces.staff", op, session_factory=_SF)

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
            try:
                exclude_role_id = parse_id_list(c.q(data, "exclude_role_id"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="exclude_role_id must be an integer") from exc
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
                exclude_role_id=exclude_role_id or None,
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
            await workspace_service.ensure_owner_role_change_allowed(
                session, workspace_id, user, target_auth_user_id=body.auth_user_id, role_ids=role_ids
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
            return await _member_payload(session, member)

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
            await workspace_service.ensure_owner_role_change_allowed(
                session, workspace_id, user, target_auth_user_id=auth_user_id, role_ids=role_ids
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
            return await _member_payload(session, member)

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
            await workspace_service.ensure_owner_role_change_allowed(
                session, workspace_id, user, target_auth_user_id=auth_user_id, role_ids=None
            )
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
            return None

        return await c.envelope(logger, "workspaces.member_remove", op, session_factory=_SF)

    # --- custom domain --------------------------------------------------------
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

    # --- quota override (admin may lower, superuser may raise) --------------
    @broker.subscriber("rpc.app.workspaces.quota_set")
    async def _quota_set(data: dict, msg: RabbitMessage) -> dict:
        """One scope's ceilings for this workspace.

        ``workspace.update`` like the tenant-owned settings around it — the gate
        that actually matters here is the authority rule inside
        ``apply_workspace_limits``: an admin may only tighten what the plan
        grants (422 ``quota_above_inherited`` otherwise), while a superuser may
        raise, which is how a partner integration is served without moving the
        workspace's whole tier.

        The answer is the EFFECTIVE ceiling (plan merged with the stored row),
        not the row that was written: an override that leaves a dimension null
        inherits it, and an operator screen must show what will actually be
        enforced.
        """

        async def op(session: Any) -> Any:
            workspace = await _gate_workspace(session, data)
            body = schemas.WorkspaceQuotaSet.model_validate(c.payload(data))
            return await quota_admin_service.set_workspace_limits(
                session, workspace, actor=c.actor(data), data=data, body=body
            )

        return await c.envelope(logger, "workspaces.quota_set", op, session_factory=_SF)

    # --- owner (accountability) ---------------------------------------------
    @broker.subscriber("rpc.app.workspaces.owner_get")
    async def _owner_get(data: dict, msg: RabbitMessage) -> dict:
        """Who is accountable for this workspace.

        ``workspace.update``-gated like the other settings reads here: this
        resolves an internal ``auth_user_id`` to a name and an email,
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
            workspace = await workspace_service.transfer_ownership(session, workspace, body.auth_user_id, actor=user)
            return await _owner_payload(session, workspace)

        return await c.envelope(logger, "workspaces.owner_transfer", op, session_factory=_SF)

    # --- notification delivery settings -------------------------------------
    # Which channel this workspace's broadcasts are posted to, in which
    # language, and which kinds are posted at all. workspace.update-gated: it
    # names a private channel and it makes the bot speak.
    @broker.subscriber("rpc.app.workspaces.notification_config_get")
    async def _notification_config_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await _gate_workspace(session, data)
            return await notification_config.read_config(session, workspace)

        return await c.envelope(logger, "workspaces.notification_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.notification_config_update")
    async def _notification_config_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await _gate_workspace(session, data)
            body = schemas.NotificationWorkspaceConfigUpdate.model_validate(c.payload(data))
            # RPC-only: discord-service answers the guild's channel list.
            client = DiscordClient(broker=broker)
            return await notification_config.write_config(
                session,
                workspace,
                body,
                list_channels=client.guild_channels,
            )

        return await c.envelope(logger, "workspaces.notification_config_update", op, session_factory=_SF)

    # --- team format default per discipline ---------------------------------
    @broker.subscriber("rpc.app.workspaces.team_format_get")
    async def _team_format_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await _gate_workspace(session, data)
            team_format, source = await workspace_format(
                session, workspace_id=workspace.id, discipline=_discipline(data)
            )
            return await team_format_read(session, team_format, source=source, workspace_id=workspace.id)

        return await c.envelope(logger, "workspaces.team_format_get", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.team_format_put")
    async def _team_format_put(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await _gate_workspace(session, data)
            discipline = _discipline(data)
            body = TeamFormatWrite.model_validate(c.payload(data))
            await save_workspace_format(
                session, workspace_id=workspace.id, discipline=discipline, team_format=body.to_domain(discipline)
            )
            await record_admin_audit(
                session,
                action="workspace.team_format_set",
                actor=c.actor(data),
                data=data,
                workspace_id=workspace.id,
                entity_type="workspace",
                entity_id=workspace.id,
                entity_label=workspace.slug,
                after={"discipline": discipline, **body.model_dump(mode="json")},
            )
            await session.commit()
            team_format, source = await workspace_format(session, workspace_id=workspace.id, discipline=discipline)
            return await team_format_read(session, team_format, source=source, workspace_id=workspace.id)

        return await c.envelope(logger, "workspaces.team_format_put", op, session_factory=_SF)
