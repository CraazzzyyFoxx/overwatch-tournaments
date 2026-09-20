"""Admin CRUD for users + identities + profile merge + avatar + CSV import,
relocated from parser-service. Reads of users already live in app-service.

Pure transport: every handler decodes params, applies its permission gate, and
makes one service call. No SQL and no transaction lives here — the services own
``commit()``.

Permission model: writes to the global identity (create/update/delete, avatar)
require the global ``user.<action>`` permission, and merge is superuser-only —
a player identity is platform-wide, so editing one from inside a workspace
would reach into every other workspace's history. **Reads** are workspace
grantable instead: ``admin_list`` takes ``workspace_id`` as both the
authorization scope and the row filter (``_scope``), so a workspace owner's
``admin.*`` lists their own roster's identities and nothing else. Same shape as
the rank/subscription collection admin, see ``parser-service/src/rpc/rank.py``.
Social identities are managed by **superusers only**
(add/update/verify/delete/set_primary); their per-workspace/global display
**visibility** is a lighter capability gated on ``user.read`` — the
per-workspace switch against that workspace, the global one globally
(``_visibility_scope``). ``verify``
manually marks an OAuth-eligible account verified when the automatic sync
missed a real OAuth connection that proves it (see
``shared.services.social_identity.verify_social_account``); it never
fabricates verification. CSV import requires the global ``admin`` role.
Avatar + CSV are binary/multipart (base64 via the gateway binary handler).

Self-service (``me_social_*``, capability ``account.social``) lets users manage
their own player's identities, but is **hide-only**: they can set-primary
(verified accounts) and toggle global display visibility — full deletion stays
superuser-only, so the verified identity is never destroyed by its owner. The same
capability covers ``me_set_stream_visibility``, the veto on surfacing the owner's
live stream on tournament pages — a separate switch from account visibility on
purpose, so staying off a tournament page does not cost you your public handle.

The same ``_account_gate`` also covers ``me_favorites_*`` (list/add/remove a
favorite player), but those never resolve the caller's player id -- a favorite
is keyed by the caller's own ``auth_user_id`` directly, so it needs no player
of the caller's own to exist and survives that player being re-linked/merged.
"""

from __future__ import annotations

import base64
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.clients.s3 import upload_avatar
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import paginated_dump
from shared.core.social import PROVIDERS, SOCIAL_PROVIDERS, matches_handle_pattern
from shared.rpc.identity import ensure_workspace_permission
from shared.rpc.query import build_query_model
from shared.services.audit import record_admin_audit
from src import schemas
from src.core import clients, db
from src.services import user_cache
from src.services.admin.favorites import favorites as favorites_service
from src.services.admin.user import users as admin_users
from src.services.admin.user_merge import merges as merge_service
from src.services.user.service import users as user_service

from . import _common as c

_SF = db.async_session_maker
_ENTITIES = ["discord", "battle_tag", "twitch"]


def _gate(data: dict, action: str) -> Any:
    user = c.actor(data)
    c.require_active(user)
    if not user.has_permission("user", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: user.{action} required")
    return user


def _scope(data: dict, action: str) -> int | None:
    """Gate on ``user.<action>`` and return the workspace to scope rows to.

    ``None`` means "every player identity on the platform", and only a global
    grant ever gets it — a workspace-scoped holder cannot widen their read into
    the platform-wide registry by dropping ``workspace_id``. Conversely a
    workspace owner (whose ``admin.*`` is workspace-scoped and so answers no
    global check) is no longer refused outright: they get their own roster.
    """
    user = c.actor(data)
    c.require_active(user)
    if user.has_permission("user", action):
        return None
    workspace_id: int | None = c.q1(data, "workspace_id", int)
    if workspace_id is None:
        raise HTTPException(status_code=403, detail=f"Permission denied: user.{action} required")
    ensure_workspace_permission(user, workspace_id, "user", action)
    return workspace_id


def _visibility_scope(data: dict, workspace_id: int | None) -> None:
    """Gate a display-visibility toggle on ``user.read`` in the scope it changes.

    The per-workspace switch only governs what that workspace shows, so that
    workspace's own ``user.read`` is the honest gate. The global switch hides the
    handle everywhere, so it keeps the global grant.
    """
    user = c.actor(data)
    c.require_active(user)
    if workspace_id is None:
        if not user.has_permission("user", "read"):
            raise HTTPException(status_code=403, detail="Permission denied: user.read required")
        return
    ensure_workspace_permission(user, workspace_id, "user", "read")


def _account_gate(data: dict) -> Any:
    """Self-service gate: any active user may manage their own accounts unless the
    ``account.social`` capability is explicitly denied (negative RBAC)."""
    user = c.actor(data)
    c.require_active(user)
    if user.is_denied("account", "social"):
        raise HTTPException(status_code=403, detail="You are not allowed to manage your accounts")
    return user


async def _envelope_and_invalidate(logger: Any, label: str, op: Any, data: dict) -> dict:
    """Run a user-mutating op, then drop the subject user's read caches on success.

    Profile/identity edits (name, avatar, socials) are not driven by
    TournamentChangedEvent, so without this the subject's cached profile/heroes/
    encounters/etc. would serve stale data until ``users_cache_ttl`` elapses.
    Runs after the DB session closes and only on ``ok`` — a failed write leaves
    the cache untouched. Cross-user cosmetic staleness (this user's name/avatar
    embedded in other users' cached lists) is left to the TTL.
    """
    result = await c.envelope(logger, label, op, session_factory=_SF)
    if result.get("ok"):
        try:
            user_id = c.require_id(data)
        except HTTPException:
            user_id = None
        if user_id is not None:
            await user_cache.invalidate_user_caches(user_id)
    return result


def register(broker: Any, logger: Any) -> None:
    # ── User CRUD ───────────────────────────────────────────────────────────
    @broker.subscriber("rpc.app.users.admin_list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _scope(data, "read")
            qp = build_query_model(schemas.UserListQueryParams, data.get("query"))
            res = await admin_users.get_users(
                session, schemas.UserListParams.from_query_params(qp), workspace_id=workspace_id
            )
            return paginated_dump(
                {**res, "results": [user_service.to_read(user, _ENTITIES) for user in res["results"]]}
            )

        return await c.envelope(logger, "users.admin_list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.admin_create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _gate(data, "create")
            payload = schemas.UserCreate.model_validate(c.payload(data))
            # Every write in this module edits the platform-wide player identity, so
            # each journal row is workspace_id=None (the helper's default) — the only
            # exception is ``social_set_visibility``, which is scoped to a workspace.
            # ``create_user`` owns the commit, so the row is staged before it: the new
            # id does not exist yet, the name identifies what was created.
            await record_admin_audit(
                session,
                action="user.create",
                actor=user,
                data=data,
                entity_type="user",
                entity_label=payload.name,
                after={"username": payload.name},
            )
            created = await admin_users.create_user(session, payload)
            return user_service.to_read(created, _ENTITIES)

        return await c.envelope(logger, "users.admin_create", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.admin_update")
    async def _update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _gate(data, "update")
            user_id = c.require_id(data)
            payload = schemas.UserAdminUpdate.model_validate(c.payload(data))
            await record_admin_audit(
                session,
                action="user.update",
                actor=user,
                data=data,
                entity_type="user",
                entity_id=user_id,
                entity_label=payload.name,
                after=payload.model_dump(exclude_unset=True),
            )
            updated = await admin_users.update_user(session, user_id, payload)
            return user_service.to_read(updated, _ENTITIES)

        return await _envelope_and_invalidate(logger, "users.admin_update", op, data)

    @broker.subscriber("rpc.app.users.admin_delete")
    async def _delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _gate(data, "delete")
            user_id = c.require_id(data)
            await record_admin_audit(
                session,
                action="user.delete",
                actor=user,
                data=data,
                entity_type="user",
                entity_id=user_id,
            )
            await admin_users.delete_user(session, user_id)
            return None

        return await _envelope_and_invalidate(logger, "users.admin_delete", op, data)

    # ── Profile merge (superuser) ─────────────────────────────────────────────
    @broker.subscriber("rpc.app.users.merge_preview")
    async def _merge_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            return await merge_service.preview_merge(
                session, schemas.UserMergePreviewRequest.model_validate(c.payload(data))
            )

        return await c.envelope(logger, "users.merge_preview", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.merge_execute")
    async def _merge_execute(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            payload = schemas.UserMergeExecuteRequest.model_validate(c.payload(data))
            # ``execute_merge`` commits (and rolls back on failure), so this row is
            # staged first and shares that fate. Distinct from the merge's own
            # ``user_merge_audit`` detail row: this is the platform journal.
            await record_admin_audit(
                session,
                action="user.merge",
                actor=user,
                data=data,
                entity_type="user",
                entity_id=payload.target_user_id,
                after={
                    "source_user_id": payload.source_user_id,
                    "target_user_id": payload.target_user_id,
                },
            )
            return await merge_service.execute_merge(
                session,
                payload,
                operator_auth_user_id=user.id,
            )

        return await c.envelope(logger, "users.merge_execute", op, session_factory=_SF)

    # ── Social identities (unified, generic) ──────────────────────────────────
    async def _refresh_user(session: Any, user_id: int) -> Any:
        user = await admin_users.get_user_or_404(session, user_id)
        return user_service.to_read(user, _ENTITIES)

    def _validate_social_create(payload: schemas.SocialAccountCreate) -> None:
        if payload.provider not in SOCIAL_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider}")
        if not payload.username.strip():
            raise HTTPException(status_code=400, detail="username is required")
        # The canonical grammar, not a hand-rolled "has a '#'" check: an admin
        # adding an identity must produce the same shape self-registration does,
        # or the two paths disagree about what the platform considers a handle.
        if not matches_handle_pattern(payload.provider, payload.username):
            spec = PROVIDERS[payload.provider]
            raise HTTPException(status_code=400, detail=f"Invalid {spec.label} handle: {payload.username!r}")

    @broker.subscriber("rpc.app.users.social_add")
    async def _social_add(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            user_id = c.require_id(data)
            payload = schemas.SocialAccountCreate.model_validate(c.payload(data))
            _validate_social_create(payload)
            # Staged before the writer's commit, so the account id does not exist yet.
            await record_admin_audit(
                session,
                action="social_account.create",
                actor=user,
                data=data,
                entity_type="social_account",
                entity_label=payload.username,
                after={"user_id": user_id, "provider": payload.provider, "username": payload.username},
            )
            await admin_users.add_social_account(
                session,
                user_id=user_id,
                provider=payload.provider,
                username=payload.username,
                url=payload.url,
            )
            return await _refresh_user(session, user_id)

        return await _envelope_and_invalidate(logger, "users.social_add", op, data)

    @broker.subscriber("rpc.app.users.social_update")
    async def _social_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            payload = schemas.SocialAccountUpdate.model_validate(c.payload(data))
            await record_admin_audit(
                session,
                action="social_account.update",
                actor=user,
                data=data,
                entity_type="social_account",
                entity_id=account_id,
                entity_label=payload.username,
                after={"user_id": user_id, **payload.model_dump(exclude_unset=True)},
            )
            await admin_users.update_social_account(
                session,
                user_id=user_id,
                account_id=account_id,
                username=payload.username,
                url=payload.url,
            )
            return await _refresh_user(session, user_id)

        return await _envelope_and_invalidate(logger, "users.social_update", op, data)

    @broker.subscriber("rpc.app.users.social_verify")
    async def _social_verify(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            await record_admin_audit(
                session,
                action="social_account.verify",
                actor=user,
                data=data,
                entity_type="social_account",
                entity_id=account_id,
                after={"user_id": user_id, "verified": True},
            )
            await admin_users.verify_social_account(session, user_id=user_id, account_id=account_id)
            return await _refresh_user(session, user_id)

        return await _envelope_and_invalidate(logger, "users.social_verify", op, data)

    @broker.subscriber("rpc.app.users.social_delete")
    async def _social_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            await record_admin_audit(
                session,
                action="social_account.delete",
                actor=user,
                data=data,
                entity_type="social_account",
                entity_id=account_id,
                before={"user_id": user_id},
            )
            await admin_users.delete_social_account(session, user_id=user_id, account_id=account_id)
            return await _refresh_user(session, user_id)

        return await _envelope_and_invalidate(logger, "users.social_delete", op, data)

    @broker.subscriber("rpc.app.users.social_set_primary")
    async def _social_set_primary(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            await record_admin_audit(
                session,
                action="social_account.set_primary",
                actor=user,
                data=data,
                entity_type="social_account",
                entity_id=account_id,
                after={"user_id": user_id, "is_primary": True},
            )
            await admin_users.set_social_primary(session, user_id=user_id, account_id=account_id)
            return await _refresh_user(session, user_id)

        return await _envelope_and_invalidate(logger, "users.social_set_primary", op, data)

    @broker.subscriber("rpc.app.users.social_set_visibility")
    async def _social_set_visibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Display visibility (per-workspace / global) is a lighter capability than
            # editing identities: ``user.read`` is enough. The payload names the scope
            # being changed, so it is also the scope being authorized.
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            payload = schemas.SocialVisibilityUpdate.model_validate(c.payload(data))
            _visibility_scope(data, payload.workspace_id)
            await record_admin_audit(
                session,
                action="social_account.set_visibility",
                actor=c.actor(data),
                data=data,
                # The scope the gate above ran against: the workspace whose display
                # this toggles, or None for the global switch.
                workspace_id=payload.workspace_id,
                entity_type="social_account",
                entity_id=account_id,
                after={"user_id": user_id, "visible": payload.visible},
            )
            await admin_users.set_social_visibility(
                session,
                user_id=user_id,
                account_id=account_id,
                workspace_id=payload.workspace_id,
                visible=payload.visible,
            )
            return await _refresh_user(session, user_id)

        return await _envelope_and_invalidate(logger, "users.social_set_visibility", op, data)

    # ── Self-service: a user manages their OWN player's social accounts ───────
    # Adding is OAuth-only (handled by identity-service link flow); here we only
    # list / set-primary (verified only) / remove. Gated on the account.social
    # capability (deny-aware), NOT superuser.
    @broker.subscriber("rpc.app.users.me_social_list")
    async def _me_social_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            player_id = await admin_users.resolve_my_player_id_or_none(session, user.id)
            if player_id is None:
                # Belt-and-suspenders after the iwrefac09 backfill: a self-listing
                # endpoint must not 404 just because the caller has no linked
                # player. Return an empty list (My Account then renders the empty
                # state + link buttons) instead of crashing. id=0 is a "no player"
                # sentinel; both callers read only ``.social_accounts``.
                return schemas.UserRead(id=0, name="", social_accounts=[])
            return await _refresh_user(session, player_id)

        return await c.envelope(logger, "users.me_social_list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_social_set_primary")
    async def _me_social_set_primary(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            player_id = await admin_users.resolve_my_player_id(session, user.id)
            await admin_users.set_own_social_primary(session, player_id=player_id, account_id=int(data["account_id"]))
            await user_cache.invalidate_user_caches(player_id)
            return await _refresh_user(session, player_id)

        return await c.envelope(logger, "users.me_social_set_primary", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_social_set_visibility")
    async def _me_social_set_visibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            player_id = await admin_users.resolve_my_player_id(session, user.id)
            # The request body arrives under ``data["payload"]`` (gateway convention),
            # not the top level — read it via ``c.payload`` like the admin handler.
            visible = bool(c.payload(data).get("visible", True))
            await admin_users.set_own_social_visibility(
                session, player_id=player_id, account_id=int(data["account_id"]), visible=visible
            )
            await user_cache.invalidate_user_caches(player_id)
            return await _refresh_user(session, player_id)

        return await c.envelope(logger, "users.me_social_set_visibility", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_set_stream_visibility")
    async def _me_set_stream_visibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # No capability beyond "this is my account": refusing to be broadcast is
            # not a privilege. Deliberately NOT folded into
            # ``me_social_set_visibility`` — that one hides the handle from the public
            # profile too, and having to disappear from your own profile to stay off a
            # tournament page is the bug this endpoint exists to fix.
            user = _account_gate(data)
            player_id = await admin_users.resolve_my_player_id(session, user.id)
            payload = schemas.StreamVisibilityUpdate.model_validate(c.payload(data))
            await admin_users.set_stream_visible(session, player_id, visible=payload.visible)
            await user_cache.invalidate_user_caches(player_id)
            return await _refresh_user(session, player_id)

        return await c.envelope(logger, "users.me_set_stream_visibility", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_favorites_list")
    async def _me_favorites_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            return await favorites_service.list_for(session, user.id)

        return await c.envelope(logger, "users.me_favorites_list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_favorite_add")
    async def _me_favorite_add(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            return await favorites_service.add(session, auth_user_id=user.id, player_id=c.require_id(data))

        return await c.envelope(logger, "users.me_favorite_add", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_favorite_remove")
    async def _me_favorite_remove(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            return await favorites_service.remove(session, auth_user_id=user.id, player_id=c.require_id(data))

        return await c.envelope(logger, "users.me_favorite_remove", op, session_factory=_SF)

    # ── Avatar (binary base64) ────────────────────────────────────────────────
    @broker.subscriber("rpc.app.users.avatar_upload")
    async def _avatar_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _gate(data, "update")
            user_id = c.require_id(data)
            # 404 before anything reaches S3, so a bad id never leaves an orphan object.
            existing = await admin_users.get_user_or_404(session, user_id)
            file_data = base64.b64decode(data.get("content_b64", ""))
            result = await upload_avatar(
                clients.s3_client,
                entity_type="players",
                entity_id=user_id,
                file_data=file_data,
                content_type=data.get("content_type") or "application/octet-stream",
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            await record_admin_audit(
                session,
                action="user.avatar_set",
                actor=user,
                data=data,
                entity_type="user",
                entity_id=user_id,
                entity_label=existing.name,
                before={"avatar_url": existing.avatar_url},
                after={"avatar_url": result.public_url},
            )
            player_user = await admin_users.set_avatar(session, user_id=user_id, avatar_url=result.public_url)
            return user_service.to_read(player_user, _ENTITIES)

        return await _envelope_and_invalidate(logger, "users.avatar_upload", op, data)

    @broker.subscriber("rpc.app.users.avatar_delete")
    async def _avatar_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _gate(data, "update")
            user_id = c.require_id(data)
            existing = await admin_users.get_user_or_404(session, user_id)
            await clients.s3_client.delete_prefix(f"avatars/players/{user_id}/")
            await record_admin_audit(
                session,
                action="user.avatar_clear",
                actor=user,
                data=data,
                entity_type="user",
                entity_id=user_id,
                entity_label=existing.name,
                before={"avatar_url": existing.avatar_url},
                after={"avatar_url": None},
            )
            player_user = await admin_users.set_avatar(session, user_id=user_id, avatar_url=None)
            return user_service.to_read(player_user, _ENTITIES)

        return await _envelope_and_invalidate(logger, "users.avatar_delete", op, data)
