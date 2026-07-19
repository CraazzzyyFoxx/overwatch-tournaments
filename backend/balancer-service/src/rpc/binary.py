"""Binary/multipart balancer endpoints over typed RPC (base64 in the envelope).

The gateway parses the multipart upload and base64-encodes the JSON file into the
RPC body (``content_b64``) alongside the ``payload_format`` form field. Ports the
``POST /tournaments/{id}/teams/import`` route from ``src/routes/admin/balancer.py``.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.balancer_realtime import BALANCER_TEAMS_CHANGED
from src.core import db
from src.core.auth import _get_tournament_workspace_id
from src.rpc import _common as c
from src.schemas.team import BalancerTeam, InternalBalancerTeamsPayload
from src.services import team as team_service
from src.services.balancer.realtime import emit_balancer_data_event

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
            c.require_workspace_permission(data, user, ws_id, "team", "import")

            payload_format = data.get("payload_format") or "auto"
            if payload_format not in _PAYLOAD_FORMATS:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid payload_format")

            # Imports can be multi-MB; base64-decode + parse off the event loop.
            payload = await asyncio.to_thread(_decode_and_parse, data)

            use_atravkovs = payload_format == "atravkovs" or (
                payload_format == "auto"
                and isinstance(payload, dict)
                and isinstance(payload.get("data"), dict)
                and "teams" in payload["data"]
            )

            if use_atravkovs:
                teams = [BalancerTeam.model_validate(team) for team in payload["data"]["teams"]]
            else:
                internal_payload = InternalBalancerTeamsPayload.model_validate(payload)
                teams = [team.to_balancer_team() for team in internal_payload.teams]

            await team_service.bulk_create_from_balancer(session, tournament_id, teams)
            await emit_balancer_data_event(tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=user.id)
            return {"imported_teams": len(teams)}

        return await c.envelope(logger, "admin.teams_import", op, session_factory=_SF)
