"""Typed-RPC handlers for the match-log admin surface: queue status, history, stats, retry, upload, tournament reprocess.

Permission gating rehydrates the gateway-injected identity via ``_common.actor`` and resolves the scope's workspace
through ``src.core.auth``. The binary upload arrives base64-encoded from the gateway; the live stream is the realtime
WS hub's.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared import quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.models import IngestJobStatus
from src import schemas
from src.core import auth, db
from src.core import clients as _clients
from src.services.ingest.process import retry_log
from src.services.match_logs import admin_reads
from src.services.match_logs.log_records import log_records_service
from src.services.match_logs.uploads import upload_service

from . import _common as c

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.stats.logs.queue_status")
    async def _queue_status(data: dict, msg: RabbitMessage) -> dict:
        async def op(_session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_permission("log", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: log.read required")
            return await admin_reads._fetch_queue_depths()

        return await c.envelope(logger, "logs.queue_status", op, session_factory=_SF)

    def _optional_int(data: dict, key: str) -> int | None:
        raw = data.get(key)
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{key} is invalid") from exc

    async def _authorize_scope(
        session: Any,
        data: dict,
        *,
        tournament_id: int | None,
        encounter_id: int | None,
        workspace_id: int | None,
    ) -> int | None:
        """Shared per-arg gating for the two scoped log reads (history, stats).

        Returns the workspace id the scope resolved to (derived from the encounter
        when only ``encounter_id`` was given), so callers can use it as a filter.
        """
        user = c.actor(data)
        c.require_active(user)
        if workspace_id is not None:
            await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="read")
        elif tournament_id is not None:
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="log", action="read"
            )
        elif encounter_id is not None:
            workspace_id = await auth._get_encounter_workspace_id(session, encounter_id)
            await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="read")
        elif not user.has_permission("log", "read"):
            raise HTTPException(status_code=403, detail="Permission denied: log.read required")
        return workspace_id

    @broker.subscriber("rpc.stats.logs.history")
    async def _history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = c.q1(data, "tournament_id", int)
            encounter_id = c.q1(data, "encounter_id", int)
            limit = c.q1(data, "limit", int, 50)
            offset = c.q1(data, "offset", int, 0)
            status_filter = (c.q1(data, "status", str) or "").strip() or None
            if limit < 1 or limit > 200:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
            if offset < 0:
                raise HTTPException(status_code=422, detail="offset must be >= 0")
            if status_filter is not None and status_filter not in {member.value for member in IngestJobStatus}:
                raise HTTPException(
                    status_code=422,
                    detail=f"status must be one of: {', '.join(member.value for member in IngestJobStatus)}",
                )
            workspace_id = await _authorize_scope(
                session,
                data,
                tournament_id=tournament_id,
                encounter_id=encounter_id,
                workspace_id=c.q1(data, "workspace_id", int),
            )
            return await admin_reads.history_page(
                session,
                _clients.s3_client,
                tournament_id=tournament_id,
                encounter_id=encounter_id,
                workspace_id=workspace_id,
                status_filter=status_filter,
                search=c.q1(data, "search", str),
                limit=limit,
                offset=offset,
            )

        return await c.envelope(logger, "logs.history", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.logs.stats")
    async def _stats(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = c.q1(data, "tournament_id", int)
            encounter_id = c.q1(data, "encounter_id", int)
            workspace_id = await _authorize_scope(
                session,
                data,
                tournament_id=tournament_id,
                encounter_id=encounter_id,
                workspace_id=c.q1(data, "workspace_id", int),
            )
            return await admin_reads.log_stats(
                session, tournament_id=tournament_id, encounter_id=encounter_id, workspace_id=workspace_id
            )

        return await c.envelope(logger, "logs.stats", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.logs.retry")
    async def _retry(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            record_id = c.require_id(data)
            workspace_id = await auth._get_ingest_job_workspace_id(session, record_id)
            await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="update")
            return await retry_log(
                session,
                job_id=record_id,
                workspace_id=workspace_id,
                request=schemas.LogRetryRequest.model_validate(c.payload(data)),
                user=user,
                data=data,
                s3=_clients.s3_client,
            )

        return await c.envelope(logger, "logs.retry", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.logs.upload")
    async def _upload(data: dict, msg: RabbitMessage) -> dict:
        # Per-file errors are collected into the reply; validation/permission failures before the loop fail the call.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            raw_tournament, raw_mix = (data.get(k) not in (None, "") for k in ("tournament_id", "custom_game_id"))
            if raw_tournament == raw_mix:
                raise HTTPException(
                    status_code=422, detail="Exactly one of tournament_id or custom_game_id is required"
                )
            encounter_id = _optional_int(data, "encounter_id")
            if not raw_mix:
                tournament_id = c.require_path_int(data, "tournament_id")
                await auth.require_tournament_id_permission(
                    session, user, tournament_id=tournament_id, resource="log", action="create"
                )
                return await upload_service.upload_batch(
                    session,
                    _clients.s3_client,
                    user=user,
                    data=data,
                    tournament_id=tournament_id,
                    encounter_id=encounter_id,
                    files=data.get("files") or [],
                )
            lobby_index = _optional_int(data, "lobby_index")
            if (encounter_id is None) == (lobby_index is None) or (lobby_index is not None and lobby_index < 0):
                raise HTTPException(
                    status_code=422,
                    detail="A mix upload needs exactly one of encounter_id or a non-negative lobby_index",
                )
            # The mix host / `log.create` permission needs the mix row, so the service checks it (D1).
            return await upload_service.upload_batch(
                session,
                _clients.s3_client,
                user=user,
                data=data,
                custom_game_id=c.require_path_int(data, "custom_game_id"),
                encounter_id=encounter_id,
                lobby_index=lobby_index,
                files=data.get("files") or [],
            )

        return await c.envelope(logger, "logs.upload", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.logs.process_tournament")
    async def _process_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            tournament_id = c.require_id(data)
            workspace_id = await auth._get_tournament_workspace_id(session, tournament_id)
            await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="update")
            # Fans out one parse job per stored log of the tournament — the cost is
            # the whole fan-out, not this ack.
            await quota.charge(user, "stats.logs.process_tournament", workspace_id=workspace_id)
            return await log_records_service.request_tournament_reprocess(
                session, tournament_id=tournament_id, user=user, data=data
            )

        return await c.envelope(logger, "logs.process_tournament", op, session_factory=_SF)
