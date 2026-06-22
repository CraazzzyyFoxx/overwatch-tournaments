"""Typed-RPC handlers for parser's bootstrap importers (the last frontend-used
HTTP routes before the parser HTTP service is decommissioned).

These create tournaments/teams/encounters from Challonge or a balancer export.
The logic stays in parser-service (parser-worker hosts it); only the transport
moves from HTTP to RPC. Mirrors:
- src/routes/tournament.py  (POST /tournament/create/with_groups)
- src/routes/team.py        (POST /teams/create/balancer [multipart], GET
                             /teams/challonge/preview, POST /teams/create/challonge)
- src/routes/encounter.py   (POST /encounter/challonge)
"""

from __future__ import annotations

import base64
import json
from datetime import date
from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from faststream.rabbit import RabbitMessage
from shared.rpc.identity import ensure_workspace_permission

from src import schemas
from src.core import db
from src.services.encounter import flows as encounter_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows

from . import _common as c

_SF = db.async_session_maker


def _require_role_admin(data: dict) -> Any:
    user = c.actor(data)
    c.require_active(user)
    if not user.has_role("admin"):
        raise HTTPException(status_code=403, detail="Role required: admin")
    return user


def _date(data: dict, key: str) -> date:
    raw = c.q1(data, key)
    if not raw:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date for {key}") from exc


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.tournament.create_with_groups")
    async def _create_with_groups(data: dict, msg: RabbitMessage) -> dict:
        # POST /tournament/create/with_groups — workspace tournament.create.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            workspace_id = c.require_query_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "tournament", "create")
            tournament = await tournament_flows.create_with_groups(
                session,
                workspace_id,
                c.require_query_int(data, "number"),
                c.q1(data, "is_league", c.qbool, False),
                _date(data, "start_date"),
                _date(data, "end_date"),
                c.q1(data, "challonge_slug"),
                division_grid_version_id=c.q1(data, "division_grid_version_id", int),
            )
            return await tournament_flows.to_pydantic(session, tournament, [])

        return await c.envelope(logger, "tournament.create_with_groups", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.teams.create_balancer")
    async def _teams_balancer(data: dict, msg: RabbitMessage) -> dict:
        # POST /teams/create/balancer (multipart JSON file -> base64) — admin role.
        async def op(session: Any) -> Any:
            _require_role_admin(data)
            try:
                tournament_id = int(data["tournament_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="tournament_id is required") from exc
            payload_format = c.q1(data, "payload_format", str, "auto")
            payload = json.loads(base64.b64decode(data.get("content_b64", "")))
            use_atravkovs = payload_format == "atravkovs" or (
                payload_format == "auto"
                and isinstance(payload, dict)
                and isinstance(payload.get("data"), dict)
                and "teams" in payload["data"]
            )
            if use_atravkovs:
                teams = [schemas.BalancerTeam.model_validate(team) for team in payload["data"]["teams"]]
            else:
                internal_payload = schemas.InternalBalancerTeamsPayload.model_validate(payload)
                teams = [team.to_balancer_team() for team in internal_payload.teams]
            return await team_flows.bulk_create_from_balancer(session, tournament_id, teams)

        return await c.envelope(logger, "teams.create_balancer", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.teams.challonge_preview")
    async def _challonge_preview(data: dict, msg: RabbitMessage) -> dict:
        # GET /teams/challonge/preview — admin role.
        async def op(session: Any) -> Any:
            _require_role_admin(data)
            return await team_flows.preview_challonge_team_sync(session, c.require_query_int(data, "tournament_id"))

        return await c.envelope(logger, "teams.challonge_preview", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.teams.create_challonge")
    async def _create_challonge(data: dict, msg: RabbitMessage) -> dict:
        # POST /teams/create/challonge — admin role.
        async def op(session: Any) -> Any:
            _require_role_admin(data)
            payload = schemas.ChallongeTeamSyncRequest.model_validate(c.payload(data))
            return await team_flows.sync_challonge_team_mappings(
                session, c.require_query_int(data, "tournament_id"), payload
            )

        return await c.envelope(logger, "teams.create_challonge", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.encounter.create_challonge")
    async def _encounter_challonge(data: dict, msg: RabbitMessage) -> dict:
        # POST /encounter/challonge — admin role.
        async def op(session: Any) -> Any:
            _require_role_admin(data)
            return await encounter_flows.bulk_create_for_tournament_from_challonge(
                session,
                c.require_query_int(data, "tournament_id"),
                skip_finals=c.q1(data, "skip_finals", c.qbool, False),
            )

        return await c.envelope(logger, "encounter.create_challonge", op, session_factory=_SF)
