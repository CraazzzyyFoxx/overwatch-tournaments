"""Binary/multipart endpoints over typed RPC (base64 in the JSON envelope).

The gateway parses multipart uploads and base64-encodes the file into the RPC
body (``content_b64`` + ``content_type``); the match-log read returns
``{content_b64, media_type, filename}`` which the gateway decodes back to raw
bytes. Permission is enforced here (workspace.update for icons, superuser for
assets). S3 access uses the worker's module-level client (started in serve.py).
"""

from __future__ import annotations

import base64
from typing import Any

import sqlalchemy as sa
from faststream.rabbit import RabbitMessage

from shared.clients.s3.upload import upload_asset, upload_avatar
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src import models, schemas
from src.core import db
from src.rpc import _common as c
from src.rpc._clients import s3_client
from src.services.workspace import service as workspace_service

_SF = db.async_session_maker
_ASSET_TYPES = ("achievements", "divisions")


def _decode(data: dict[str, Any]) -> bytes:
    raw = data.get("content_b64")
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail="content_b64 is required")
    try:
        return base64.b64decode(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid base64 content") from exc


def _content_type(data: dict[str, Any]) -> str:
    ct = data.get("content_type")
    return ct if isinstance(ct, str) and ct else "application/octet-stream"


async def _resolve_workspace_slug(session: Any, workspace_id: int | None) -> str | None:
    if workspace_id is None:
        return None
    ws = await session.get(models.Workspace, workspace_id)
    return ws.slug if ws else None


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.workspaces.icon_upload")
    async def _icon_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = c.require_id(data)
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            result = await upload_avatar(
                s3_client,
                entity_type="workspaces",
                entity_id=workspace_id,
                file_data=_decode(data),
                content_type=_content_type(data),
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            workspace = await workspace_service.update(session, workspace, {"icon_url": result.public_url})
            await session.commit()
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.icon_upload", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.icon_delete")
    async def _icon_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = c.require_id(data)
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_service.get_by_id(session, workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            await s3_client.delete_prefix(f"avatars/workspaces/{workspace_id}/")
            workspace = await workspace_service.update(session, workspace, {"icon_url": None})
            await session.commit()
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.icon_delete", op, session_factory=_SF)

    @broker.subscriber("rpc.app.assets.upload")
    async def _asset_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            asset_type = data.get("asset_type")
            if asset_type not in _ASSET_TYPES:
                raise HTTPException(status_code=422, detail="invalid asset_type")
            workspace_slug = await _resolve_workspace_slug(session, c.q1(data, "workspace_id", int))
            result = await upload_asset(
                s3_client,
                asset_type=asset_type,
                slug=data.get("slug"),
                file_data=_decode(data),
                content_type=_content_type(data),
                workspace_slug=workspace_slug,
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            return {"key": result.key, "public_url": result.public_url}

        return await c.envelope(logger, "assets.upload", op, session_factory=_SF)

    @broker.subscriber("rpc.app.assets.delete")
    async def _asset_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            asset_type = data.get("asset_type")
            if asset_type not in _ASSET_TYPES:
                raise HTTPException(status_code=422, detail="invalid asset_type")
            slug = data.get("slug")
            workspace_slug = await _resolve_workspace_slug(session, c.q1(data, "workspace_id", int))
            if workspace_slug:
                prefix = f"assets/{asset_type}/{workspace_slug}/{slug}."
            else:
                prefix = f"assets/{asset_type}/{slug}."
            deleted = await s3_client.delete_prefix(prefix)
            if deleted == 0:
                raise HTTPException(status_code=404, detail="Asset not found")
            return {"deleted": deleted}

        return await c.envelope(logger, "assets.delete", op, session_factory=_SF)

    @broker.subscriber("rpc.app.matches.log")
    async def _match_log(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            match_id = c.require_id(data)
            row = (
                await session.execute(
                    sa.select(models.Match.log_name, models.Encounter.tournament_id)
                    .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
                    .where(models.Match.id == match_id)
                )
            ).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Match not found")
            log_name, tournament_id = row
            filename = (log_name or "").rsplit("/", 1)[-1]
            if not filename or ".." in filename:
                raise HTTPException(status_code=404, detail="No log available for this match")
            data_bytes = await s3_client.get_object(f"logs/{tournament_id}/{filename}")
            if data_bytes is None:
                raise HTTPException(status_code=404, detail="Log file not found")
            return {
                "content_b64": base64.b64encode(data_bytes).decode("ascii"),
                "media_type": "application/octet-stream",
                "filename": filename,
            }

        return await c.envelope(logger, "matches.log", op, session_factory=_SF)
