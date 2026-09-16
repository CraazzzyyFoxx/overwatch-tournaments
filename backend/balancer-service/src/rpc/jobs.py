"""Public balancer compute API over typed RPC (rpc.balancer.jobs.* + rpc.balancer.balance).

Ports the job endpoints from ``src/routes/balancer.py``: create (multipart upload
arrives base64-encoded from the gateway), status poll, and result. These accept
both access tokens and workspace-scoped API keys, so the user is rebuilt with the
full balancer identity (``_resolve_user_from_token`` — restores credential_type +
api_key attrs the api-key rate-limit/policy/ownership logic needs) rather than the
generic shared rehydrate. Only ``create`` needs a DB session — it resolves the
tournament's roster shape into the queued job; status and result are pure
Redis-backed job-store reads.

The SSE stream endpoint is intentionally NOT migrated: it's dead code (the
frontend tracks progress via the tournament:{id}:balancer WS topic), and a
long-lived stream does not fit the request/reply RPC model.

``rpc.balancer.balance`` is the synchronous twin of that job trio: one request
carrying the whole pool, one response carrying the teams. It lives here because
it shares the job path's limiter, API-key policy and result schema — it differs
only in transport and in a solver budget clamped to fit an HTTP round trip.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any

from faststream.rabbit import RabbitMessage
from starlette.datastructures import Headers, UploadFile

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rbac.workspace_lookup import get_tournament_workspace_id
from shared.rpc.identity import MissingIdentityError
from src import schemas
from src.core import db
from src.core.auth import _resolve_user_from_token
from src.rpc import _common as c
from src.services.balancer import jobs

_SF = db.async_session_maker


async def _resolve_user(data: dict[str, Any]) -> Any:
    """Rebuild the exact balancer AuthUser the HTTP path produces from the
    gateway-injected token payload (incl. api-key attributes)."""
    identity = data.get("identity")
    if not identity or not isinstance(identity, dict):
        raise MissingIdentityError("no identity payload")
    raw = identity.get("user_id", identity.get("sub"))
    try:
        user_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissingIdentityError("identity has no valid user_id") from exc
    return await _resolve_user_from_token(user_id, identity)


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid integer value") from exc


async def _build_upload(data: dict[str, Any]) -> UploadFile:
    raw = data.get("content_b64")
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail="player_data_file is required")
    try:
        # Uploads can reach 25MB of base64; decode off the event loop.
        file_bytes = await asyncio.to_thread(base64.b64decode, raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid base64 content") from exc
    content_type = data.get("content_type") or "application/json"
    return UploadFile(
        file=io.BytesIO(file_bytes),
        size=len(file_bytes),
        filename=data.get("filename") or "players.json",
        headers=Headers({"content-type": content_type}),
    )


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.jobs.create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = await _resolve_user(data)
            workspace_id = c.q1(data, "workspace_id", int)
            if workspace_id is None:
                raise HTTPException(status_code=422, detail="workspace_id is required")
            try:
                return await jobs.create_job(
                    session=session,
                    uploaded_file=await _build_upload(data),
                    raw_config=data.get("config_overrides"),
                    workspace_id=workspace_id,
                    user=user,
                    broker=broker,
                    tournament_id=_opt_int(data.get("tournament_id")),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return await c.envelope(logger, "jobs.create", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.jobs.create_for_tournament")
    async def _create_for_tournament(data: dict, msg: RabbitMessage) -> dict:
        """Balance a tournament's own pool: nothing is uploaded.

        The xv-1 payload is built server-side from ``shared.services.roster`` --
        the same engine the draft reads -- so the algorithm and the draft can no
        longer be fed two different rank sources.
        """

        async def op(session: Any) -> Any:
            user = await _resolve_user(data)
            tournament_id = int(data["id"])
            workspace_id = await get_tournament_workspace_id(session, tournament_id)
            payload = schemas.TournamentBalanceRequest.model_validate(c.payload(data) or {})
            overrides = payload.config_overrides
            return await jobs.create_tournament_job(
                session=session,
                tournament_id=tournament_id,
                raw_config=json.dumps(overrides.model_dump(exclude_none=True)) if overrides else None,
                workspace_id=workspace_id,
                user=user,
                broker=broker,
            )

        return await c.envelope(logger, "jobs.create_for_tournament", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.jobs.status")
    async def _status(data: dict, msg: RabbitMessage) -> dict:
        async def op() -> Any:
            user = await _resolve_user(data)
            return await jobs.get_job_status(job_id=str(data.get("id")), user=user)

        return await c.call(logger, "jobs.status", op)

    @broker.subscriber("rpc.balancer.jobs.result")
    async def _result(data: dict, msg: RabbitMessage) -> dict:
        async def op() -> Any:
            user = await _resolve_user(data)
            return await jobs.get_job_result(job_id=str(data.get("id")), user=user)

        return await c.call(logger, "jobs.result", op)

    @broker.subscriber("rpc.balancer.balance")
    async def _balance(data: dict, msg: RabbitMessage) -> dict:
        """Solve a payload and answer with the teams: no job id, no polling.

        Session-less on purpose. Unlike both creators above, this one reads
        nothing from the workspace — the pool and the roster shape arrive in the
        body — so there is no transaction to open. ``workspace_id`` is still
        required: it is what the API key is scoped against and what the
        `team.create` permission is checked on.
        """

        async def op() -> Any:
            user = await _resolve_user(data)
            workspace_id = c.q1(data, "workspace_id", int)
            if workspace_id is None:
                raise HTTPException(status_code=422, detail="workspace_id is required")
            body = schemas.BalanceRequest.model_validate(c.payload(data) or {})
            return await jobs.balance_inline(
                player_data=body.player_data,
                role_mask=body.role_mask,
                config_overrides=(
                    body.config_overrides.model_dump(exclude_none=True) if body.config_overrides else None
                ),
                workspace_id=workspace_id,
                user=user,
            )

        return await c.call(logger, "balance", op)
