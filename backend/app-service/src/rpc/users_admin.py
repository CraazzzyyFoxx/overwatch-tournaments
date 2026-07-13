"""Admin CRUD for users + identities + profile merge + avatar + CSV import,
relocated from parser-service. Reads of users already live in app-service.

Permission model: user CRUD requires the global ``user.<action>`` permission;
merge is superuser-only. Social identities are managed by **superusers only**
(add/update/delete/set_primary); their per-workspace/global display **visibility**
is a lighter capability gated on ``user.read``. CSV import requires the global
``admin`` role. Avatar + CSV are binary/multipart (base64 via the gateway binary
handler).

Self-service (``me_social_*``, capability ``account.social``) lets users manage
their own player's identities, but is **hide-only**: they can set-primary
(verified accounts) and toggle global display visibility — full deletion stays
superuser-only, so the verified identity is never destroyed by its owner.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
import sqlalchemy as sa
from faststream.rabbit import RabbitMessage

from shared.clients.s3 import upload_avatar
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SOCIAL_PROVIDERS, SocialProvider
from shared.rpc.query import build_query_model
from shared.services import social_identity as social_svc
from src import models, schemas
from src.core import db
from src.schemas.admin import user as admin_schemas
from src.schemas.admin import user_merge as merge_schemas
from src.services.admin import user as admin_service
from src.services.admin import user_csv as csv_service
from src.services.admin import user_merge as merge_service
from src.services.user import flows as user_flows

from . import _clients
from . import _common as c

_SF = db.async_session_maker
_ENTITIES = ["discord", "battle_tag", "twitch"]

_SHEETS_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_GID_RE = re.compile(r"[?&#]gid=(\d+)")


def _gate(data: dict, action: str) -> Any:
    user = c.actor(data)
    c.require_active(user)
    if not user.has_permission("user", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: user.{action} required")
    return user


def _account_gate(data: dict) -> Any:
    """Self-service gate: any active user may manage their own accounts unless the
    ``account.social`` capability is explicitly denied (negative RBAC)."""
    user = c.actor(data)
    c.require_active(user)
    if user.is_denied("account", "social"):
        raise HTTPException(status_code=403, detail="You are not allowed to manage your accounts")
    return user


async def _resolve_my_player_id_or_none(session: Any, user: Any) -> int | None:
    """Current user's linked player id, or None when no player is linked."""
    return await session.scalar(sa.select(models.User.id).where(models.User.auth_user_id == user.id))


async def _resolve_my_player_id(session: Any, user: Any) -> int:
    """Current user's linked player id (404 if the user has no player)."""
    player_id = await _resolve_my_player_id_or_none(session, user)
    if player_id is None:
        raise HTTPException(status_code=404, detail="No linked player profile")
    return player_id


async def _propagate_avatar_to_auth_user(session: Any, player_user: Any, avatar_url: str | None) -> None:
    """Mirror an admin-set player avatar onto the linked auth user's ``avatar_url``.

    The public profile / admin dialog read ``players.avatar_url``, but the header
    and the self-service My Account modal read ``AuthUser.avatar_url`` (via ``/me``).
    Without this, an admin avatar change updated only the player and the two views
    desynced. This is the inverse of identity-svc's ``_propagate_to_player`` (which
    already mirrors self-service changes onto the player). No-op for players with no
    linked account."""
    if player_user.auth_user_id is None:
        return
    auth_user = await session.scalar(sa.select(models.AuthUser).where(models.AuthUser.id == player_user.auth_user_id))
    if auth_user is not None:
        auth_user.avatar_url = avatar_url


def _sheets_to_csv_url(url: str) -> str:
    match = _SHEETS_ID_RE.search(url)
    if not match:
        raise HTTPException(status_code=400, detail="Could not extract spreadsheet ID from the provided URL.")
    spreadsheet_id = match.group(1)
    gid_match = _GID_RE.search(url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"


def register(broker: Any, logger: Any) -> None:
    # ── User CRUD ───────────────────────────────────────────────────────────
    @broker.subscriber("rpc.app.users.admin_list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _gate(data, "read")
            qp = build_query_model(admin_schemas.UserListQueryParams, data.get("query"))
            res = await admin_service.get_users(session, admin_schemas.UserListParams.from_query_params(qp))
            results = [
                (await user_flows.to_pydantic(session, user, _ENTITIES)).model_dump(mode="json")
                for user in res["results"]
            ]
            return {
                "results": results,
                "total": res["total"],
                "page": res["page"],
                "per_page": res["per_page"],
            }

        return await c.envelope(logger, "users.admin_list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.admin_create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _gate(data, "create")
            created = await admin_service.create_user(session, admin_schemas.UserCreate.model_validate(c.payload(data)))
            return await user_flows.to_pydantic(session, created, _ENTITIES)

        return await c.envelope(logger, "users.admin_create", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.admin_update")
    async def _update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _gate(data, "update")
            updated = await admin_service.update_user(
                session, c.require_id(data), admin_schemas.UserUpdate.model_validate(c.payload(data))
            )
            return await user_flows.to_pydantic(session, updated, _ENTITIES)

        return await c.envelope(logger, "users.admin_update", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.admin_delete")
    async def _delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _gate(data, "delete")
            await admin_service.delete_user(session, c.require_id(data))
            return None

        return await c.envelope(logger, "users.admin_delete", op, session_factory=_SF)

    # ── Profile merge (superuser) ─────────────────────────────────────────────
    @broker.subscriber("rpc.app.users.merge_preview")
    async def _merge_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            return await merge_service.preview_merge(
                session, merge_schemas.UserMergePreviewRequest.model_validate(c.payload(data))
            )

        return await c.envelope(logger, "users.merge_preview", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.merge_execute")
    async def _merge_execute(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_superuser(user)
            return await merge_service.execute_merge(
                session,
                merge_schemas.UserMergeExecuteRequest.model_validate(c.payload(data)),
                operator_auth_user_id=user.id,
            )

        return await c.envelope(logger, "users.merge_execute", op, session_factory=_SF)

    # ── Social identities (unified, generic) ──────────────────────────────────
    async def _refresh_user(session: Any, user_id: int) -> Any:
        user = await admin_service.get_user_or_404(session, user_id)
        return await user_flows.to_pydantic(session, user, _ENTITIES)

    def _validate_social_create(payload: admin_schemas.SocialAccountCreate) -> None:
        if payload.provider not in SOCIAL_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider}")
        if not payload.username.strip():
            raise HTTPException(status_code=400, detail="username is required")
        if payload.provider == SocialProvider.BATTLENET and "#" not in payload.username:
            raise HTTPException(status_code=400, detail="Invalid BattleTag format. Expected 'Name#1234'.")

    @broker.subscriber("rpc.app.users.social_add")
    async def _social_add(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            user_id = c.require_id(data)
            await admin_service.get_user_or_404(session, user_id)
            payload = admin_schemas.SocialAccountCreate.model_validate(c.payload(data))
            _validate_social_create(payload)
            await social_svc.upsert_social_account(
                session,
                user_id=user_id,
                provider=payload.provider,
                username=payload.username,
                url=payload.url,
            )
            await session.commit()
            return await _refresh_user(session, user_id)

        return await c.envelope(logger, "users.social_add", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.social_update")
    async def _social_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            payload = admin_schemas.SocialAccountUpdate.model_validate(c.payload(data))
            try:
                account = await social_svc.update_social_account(
                    session,
                    account_id=account_id,
                    user_id=user_id,
                    username=payload.username,
                    url=payload.url,
                )
            except social_svc.SocialHandleConflict as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if account is None:
                raise HTTPException(status_code=404, detail="Social account not found")
            await session.commit()
            return await _refresh_user(session, user_id)

        return await c.envelope(logger, "users.social_update", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.social_delete")
    async def _social_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            user_id = c.require_id(data)
            account = await social_svc.delete_social_account(
                session, account_id=int(data["account_id"]), user_id=user_id
            )
            if account is None:
                raise HTTPException(status_code=404, detail="Social account not found")
            await session.commit()
            return await _refresh_user(session, user_id)

        return await c.envelope(logger, "users.social_delete", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.social_set_primary")
    async def _social_set_primary(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            user_id = c.require_id(data)
            account = await social_svc.set_primary(session, account_id=int(data["account_id"]), user_id=user_id)
            if account is None:
                raise HTTPException(status_code=404, detail="Social account not found")
            await session.commit()
            return await _refresh_user(session, user_id)

        return await c.envelope(logger, "users.social_set_primary", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.social_set_visibility")
    async def _social_set_visibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Display visibility (per-workspace / global) is a lighter capability than
            # editing identities: anyone with ``user.read`` may configure it.
            _gate(data, "read")
            user_id = c.require_id(data)
            account_id = int(data["account_id"])
            account = await social_svc.get_social_account(session, account_id)
            if account is None or account.user_id != user_id:
                raise HTTPException(status_code=404, detail="Social account not found")
            payload = admin_schemas.SocialVisibilityUpdate.model_validate(c.payload(data))
            await social_svc.set_visibility(
                session, account_id=account_id, workspace_id=payload.workspace_id, visible=payload.visible
            )
            await session.commit()
            return await _refresh_user(session, user_id)

        return await c.envelope(logger, "users.social_set_visibility", op, session_factory=_SF)

    # ── Self-service: a user manages their OWN player's social accounts ───────
    # Adding is OAuth-only (handled by identity-service link flow); here we only
    # list / set-primary (verified only) / remove. Gated on the account.social
    # capability (deny-aware), NOT superuser.
    @broker.subscriber("rpc.app.users.me_social_list")
    async def _me_social_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            player_id = await _resolve_my_player_id_or_none(session, user)
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
            player_id = await _resolve_my_player_id(session, user)
            account = await social_svc.get_social_account(session, int(data["account_id"]))
            if account is None or account.user_id != player_id:
                raise HTTPException(status_code=404, detail="Social account not found")
            if not account.is_verified:
                raise HTTPException(status_code=400, detail="Only OAuth-verified accounts can be primary")
            await social_svc.set_primary(session, account_id=account.id, user_id=player_id)
            await session.commit()
            return await _refresh_user(session, player_id)

        return await c.envelope(logger, "users.me_social_set_primary", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.me_social_set_visibility")
    async def _me_social_set_visibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _account_gate(data)
            player_id = await _resolve_my_player_id(session, user)
            account = await social_svc.get_social_account(session, int(data["account_id"]))
            if account is None or account.user_id != player_id:
                raise HTTPException(status_code=404, detail="Social account not found")
            # Self-service is hide-only and global-scope: users toggle whether the
            # account shows on their public profile. Hard delete stays superuser-only
            # so the verified identity (and its OAuth link) is never destroyed here.
            # The request body arrives under ``data["payload"]`` (gateway convention),
            # not the top level — read it via ``c.payload`` like the admin handler.
            visible = bool(c.payload(data).get("visible", True))
            await social_svc.set_visibility(
                session,
                account_id=account.id,
                workspace_id=None,
                visible=visible,
            )
            await session.commit()
            return await _refresh_user(session, player_id)

        return await c.envelope(logger, "users.me_social_set_visibility", op, session_factory=_SF)

    # ── Avatar (binary base64) ────────────────────────────────────────────────
    @broker.subscriber("rpc.app.users.avatar_upload")
    async def _avatar_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _gate(data, "update")
            user_id = c.require_id(data)
            player_user = await admin_service.get_user_or_404(session, user_id)
            file_data = base64.b64decode(data.get("content_b64", ""))
            result = await upload_avatar(
                _clients.s3_client,
                entity_type="players",
                entity_id=user_id,
                file_data=file_data,
                content_type=data.get("content_type") or "application/octet-stream",
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            player_user.avatar_url = result.public_url
            await _propagate_avatar_to_auth_user(session, player_user, result.public_url)
            await session.commit()
            player_user = await admin_service.get_user_or_404(session, user_id)
            return await user_flows.to_pydantic(session, player_user, _ENTITIES)

        return await c.envelope(logger, "users.avatar_upload", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.avatar_delete")
    async def _avatar_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _gate(data, "update")
            user_id = c.require_id(data)
            player_user = await admin_service.get_user_or_404(session, user_id)
            await _clients.s3_client.delete_prefix(f"avatars/players/{user_id}/")
            player_user.avatar_url = None
            await _propagate_avatar_to_auth_user(session, player_user, None)
            await session.commit()
            player_user = await admin_service.get_user_or_404(session, user_id)
            return await user_flows.to_pydantic(session, player_user, _ENTITIES)

        return await c.envelope(logger, "users.avatar_delete", op, session_factory=_SF)

    # ── CSV / Google-Sheets bulk import (admin role) ──────────────────────────
    @broker.subscriber("rpc.app.users.csv_import")
    async def _csv_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")

            content_b64 = data.get("content_b64")
            sheet_url = c.q1(data, "sheet_url") or data.get("sheet_url")
            if content_b64:
                lines = base64.b64decode(content_b64).decode("utf-8").split("\n")
                filename = data.get("filename") or "upload.csv"
            elif sheet_url:
                csv_url = _sheets_to_csv_url(sheet_url)
                async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                    resp = await client.get(csv_url)
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=400, detail=f"Failed to fetch Google Sheet (HTTP {resp.status_code})."
                    )
                lines = resp.text.split("\n")
                filename = sheet_url
            else:
                raise HTTPException(status_code=400, detail="Provide either a CSV file upload or a Google Sheets URL.")

            await csv_service.bulk_create_users_from_csv(
                session,
                filename,
                lines,
                c.q1(data, "start_row", int, 0),
                battle_tag_row=c.require_query_int(data, "battle_tag_row"),
                discord_row=c.require_query_int(data, "discord_row"),
                twitch_row=c.require_query_int(data, "twitch_row"),
                smurf_row=c.require_query_int(data, "smurf_row"),
                delimiter=c.q1(data, "delimiter", str, ","),
                has_discord=c.q1(data, "has_discord", c.qbool, True),
                has_smurf=c.q1(data, "has_smurf", c.qbool, True),
                has_twitch=c.q1(data, "has_twitch", c.qbool, True),
            )
            return {"success": True}

        return await c.envelope(logger, "users.csv_import", op, session_factory=_SF)
