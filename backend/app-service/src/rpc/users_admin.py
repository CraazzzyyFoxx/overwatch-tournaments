"""Admin CRUD for users + identities + profile merge + avatar + CSV import,
relocated from parser-service. Reads of users already live in app-service.

Permission model mirrors the parser routes: user CRUD/identities require the
global ``user.<action>`` permission; merge is superuser-only; CSV import requires
the global ``admin`` role. Avatar + CSV are binary/multipart (base64 via the
gateway binary handler).
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
from shared.core.errors import BaseAPIException as HTTPException
from faststream.rabbit import RabbitMessage
from shared.clients.s3 import upload_avatar
from shared.rpc.query import build_query_model

from src import schemas
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
            return {
                "results": [u.model_dump(mode="json") for u in res["results"]],
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

    # ── Identity management ───────────────────────────────────────────────────
    def _identity_handlers(platform: str, create_schema: Any, update_schema: Any, read_schema: Any,
                           add_fn: Any, update_fn: Any, delete_fn: Any) -> None:
        @broker.subscriber(f"rpc.app.users.{platform}_add")
        async def _add(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, "update")
                identity = await add_fn(session, c.require_id(data), create_schema.model_validate(c.payload(data)))
                return read_schema.model_validate(identity, from_attributes=True)

            return await c.envelope(logger, f"users.{platform}_add", op, session_factory=_SF)

        @broker.subscriber(f"rpc.app.users.{platform}_update")
        async def _upd(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, "update")
                identity = await update_fn(
                    session, c.require_id(data), int(data["identity_id"]), update_schema.model_validate(c.payload(data))
                )
                return read_schema.model_validate(identity, from_attributes=True)

            return await c.envelope(logger, f"users.{platform}_update", op, session_factory=_SF)

        @broker.subscriber(f"rpc.app.users.{platform}_delete")
        async def _del(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, "delete")
                await delete_fn(session, c.require_id(data), int(data["identity_id"]))
                return None

            return await c.envelope(logger, f"users.{platform}_delete", op, session_factory=_SF)

    _identity_handlers(
        "discord", admin_schemas.DiscordIdentityCreate, admin_schemas.DiscordIdentityUpdate, schemas.UserDiscordRead,
        admin_service.add_discord_identity, admin_service.update_discord_identity, admin_service.delete_discord_identity,
    )
    _identity_handlers(
        "battletag", admin_schemas.BattleTagIdentityCreate, admin_schemas.BattleTagIdentityUpdate,
        schemas.UserBattleTagRead,
        admin_service.add_battletag_identity, admin_service.update_battletag_identity,
        admin_service.delete_battletag_identity,
    )
    _identity_handlers(
        "twitch", admin_schemas.TwitchIdentityCreate, admin_schemas.TwitchIdentityUpdate, schemas.UserTwitchRead,
        admin_service.add_twitch_identity, admin_service.update_twitch_identity, admin_service.delete_twitch_identity,
    )

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
                    raise HTTPException(status_code=400, detail=f"Failed to fetch Google Sheet (HTTP {resp.status_code}).")
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
