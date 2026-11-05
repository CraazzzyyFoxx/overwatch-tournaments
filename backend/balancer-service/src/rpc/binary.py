"""Binary/multipart balancer endpoints over typed RPC (base64 in the envelope).

The gateway parses the multipart upload and base64-encodes the JSON file into the
RPC body (``content_b64``) alongside the ``payload_format`` form field.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from faststream.rabbit import RabbitMessage

from shared import quota
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src.core import db
from src.core.auth import _get_tournament_workspace_id
from src.rpc import _common as c
from src.services.formation_node import require_formation_node
from src.services.registered_teams import registered_teams_service
from src.services.team import team_service

_SF = db.async_session_maker
_PAYLOAD_FORMATS = ("auto", "atravkovs", "internal")


def _decode_and_parse(data: dict[str, Any]) -> Any:
    raw = data.get("content_b64")
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail="content_b64 is required")
    try:
        decoded = base64.b64decode(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid base64 content") from exc
    return json.loads(decoded.decode("utf-8"))


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.admin.teams_import")
    async def _teams_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)

            payload_format = data.get("payload_format") or "auto"
            if payload_format not in _PAYLOAD_FORMATS:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid payload_format")

            # A multi-MB import that rewrites a tournament's roster is metered like the admin exports.
            raw_content = data.get("content_b64")
            await quota.charge(
                user,
                "balancer.teams_import",
                workspace_id=ws_id,
                size_bytes=len(raw_content) if isinstance(raw_content, str) else None,
            )

            # Imports can be multi-MB; base64-decode + parse off the event loop.
            payload = await asyncio.to_thread(_decode_and_parse, data)

            outcome = await team_service.import_teams(
                session, tournament_id, node_id, payload, payload_format, actor_user_id=user.id
            )
            return {"imported_teams": outcome.imported_teams, "advisories": outcome.materialization.advisories}

        return await c.envelope(logger, "admin.teams_import", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.teams.export_registered")
    async def _export_registered(data: dict, msg: RabbitMessage) -> dict:
        """Materialize this tournament's complete registered teams.

        The heavy lifting is the orchestrator's; this handler owns only permission
        and the optional team-id narrowing.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            await quota.charge(user, "balancer.teams_export", workspace_id=ws_id)

            # ``c.payload`` normalizes a missing/non-dict body to {}, so an empty
            # POST means "export every complete team".
            raw_ids = c.payload(data).get("team_ids")
            team_ids = [int(value) for value in raw_ids] if isinstance(raw_ids, list) and raw_ids else None

            result = await registered_teams_service.export_registered(
                session, tournament_id, node_id, team_ids=team_ids, actor_user_id=user.id
            )
            # Publishes the signals ``export_registered`` staged after the orchestrator's commit.
            await session.commit()
            return {
                "removed_teams": result.removed_teams,
                "imported_teams": result.imported_teams,
                "created_players": result.created_players,
                # Reported, never silently dropped: an organizer pressing export
                # needs to know WHICH teams did not go and why.
                "skipped": [{"team_id": item.team_id, "name": item.name, "code": item.code} for item in result.skipped],
            }

        return await c.envelope(logger, "teams.export_registered", op, session_factory=_SF)
