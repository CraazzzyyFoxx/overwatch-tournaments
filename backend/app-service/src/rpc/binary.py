"""Binary/multipart endpoints over typed RPC (base64 in the JSON envelope).

The gateway parses multipart uploads and base64-encodes the file into the RPC
body (``content_b64`` + ``content_type``); the match-log read returns
``{content_b64, media_type, filename}`` which the gateway decodes back to raw
bytes. Permission is enforced here (workspace.update for icons; asset.create/
delete scoped to the workspace when one is given, else superuser for
platform-wide catalog assets); every side effect — S3, the workspace row, the
audit row, the commit — belongs to ``services/workspace/binary.py``.

The two uploads are metered (``shared.quota``) between the permission check and
the storage write: charging an unauthorized caller would let an outsider drain
a tenant's budget, and charging after the write would bill for bytes already
stored.
"""

from __future__ import annotations

import base64
from typing import Any

from faststream.rabbit import RabbitMessage

from shared import quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services.workspace.binary import workspace_binary

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


def _asset_type(data: dict[str, Any]) -> str:
    asset_type = data.get("asset_type")
    if asset_type not in _ASSET_TYPES:
        raise HTTPException(status_code=422, detail="invalid asset_type")
    return asset_type


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.workspaces.icon_upload")
    async def _icon_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = c.require_id(data)
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            file_data = _decode(data)
            await quota.charge(user, "app.workspace_icon_upload", workspace_id=workspace_id, size_bytes=len(file_data))
            workspace = await workspace_binary.set_icon(
                session,
                workspace_id=workspace_id,
                actor=user,
                file_data=file_data,
                content_type=_content_type(data),
            )
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.icon_upload", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.icon_delete")
    async def _icon_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = c.require_id(data)
            user = c.actor(data)
            c.require_active(user)
            ensure_workspace_permission(user, workspace_id, "workspace", "update")
            workspace = await workspace_binary.clear_icon(session, workspace_id=workspace_id, actor=user)
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.icon_delete", op, session_factory=_SF)

    @broker.subscriber("rpc.app.assets.upload")
    async def _asset_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            workspace_id = c.q1(data, "workspace_id", int)
            if workspace_id is None:
                c.require_superuser(user)
            else:
                ensure_workspace_permission(user, workspace_id, "asset", "create")
            file_data = _decode(data)
            await quota.charge(user, "app.assets.upload", workspace_id=workspace_id, size_bytes=len(file_data))
            return await workspace_binary.store_asset(
                session,
                asset_type=_asset_type(data),
                slug=data.get("slug"),
                file_data=file_data,
                content_type=_content_type(data),
                workspace_id=workspace_id,
            )

        return await c.envelope(logger, "assets.upload", op, session_factory=_SF)

    @broker.subscriber("rpc.app.assets.delete")
    async def _asset_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            workspace_id = c.q1(data, "workspace_id", int)
            if workspace_id is None:
                c.require_superuser(user)
            else:
                ensure_workspace_permission(user, workspace_id, "asset", "delete")
            deleted = await workspace_binary.remove_asset(
                session,
                asset_type=_asset_type(data),
                slug=data.get("slug"),
                workspace_id=workspace_id,
            )
            return {"deleted": deleted}

        return await c.envelope(logger, "assets.delete", op, session_factory=_SF)

    @broker.subscriber("rpc.app.matches.log")
    async def _match_log(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            match_id = c.require_id(data)
            filename, tournament_id = await workspace_binary.resolve_match_log_ref(session, match_id)
            await c.gate_tournament(session, data, tournament_id)
            data_bytes = await workspace_binary.fetch_log_bytes(tournament_id, filename)
            return {
                "content_b64": base64.b64encode(data_bytes).decode("ascii"),
                "media_type": "application/octet-stream",
                "filename": filename,
            }

        return await c.envelope(logger, "matches.log", op, session_factory=_SF)
