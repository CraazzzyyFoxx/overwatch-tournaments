"""Typed-RPC handlers for the match-log admin surface.

Mirrors the HTTP routes in ``src/routes/admin/logs.py`` (history, queue-status,
retry) and the ``POST /logs/{tournament_id}`` enqueue from
``src/routes/match_logs.py``. Permission gating mirrors the route dependencies
exactly, rehydrating the gateway-injected identity via ``_common.actor`` and
reusing parser's workspace-resolution helpers in ``src.core.auth``.

The reusable read helpers/schemas are imported from the route modules (the route
modules stay until the HTTP face is decommissioned), so the RPC output is
byte-identical to the HTTP responses.

Binary upload (multipart) and the live SSE stream are handled separately: upload
via the base64 binary handler, the stream via the realtime WS hub.
"""

from __future__ import annotations

import base64
from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from faststream.rabbit import RabbitMessage
from shared.messaging.config import PROCESS_MATCH_LOG_QUEUE, PROCESS_TOURNAMENT_LOGS_QUEUE
from shared.models.log_processing import LogProcessingSource, LogProcessingStatus
from shared.observability import publish_message
from shared.schemas.events import ProcessMatchLogEvent, ProcessTournamentLogsEvent
from sqlalchemy import desc, select

from src import models
from src.core import auth, db
from src.schemas.admin.logs import (
    LogRecordRead,
    LogUploadError,
    LogUploadItem,
    LogUploadResponse,
)
from src.services.match_logs import uploads as upload_service
from src.services.match_logs.admin_reads import (
    _fetch_queue_depths,
    _record_to_dict,
    _validate_attached_encounter,
)
from src.services.tournament import flows as tournament_flows

from . import _clients
from . import _common as c

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.logs.queue_status")
    async def _queue_status(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/logs/queue-status — dependency: require_permission("log","read").
        async def op(_session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_permission("log", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: log.read required")
            return await _fetch_queue_depths()

        return await c.envelope(logger, "logs.queue_status", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.history")
    async def _history(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/logs/history — per-arg permission gating mirrors the route.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            tournament_id = c.q1(data, "tournament_id", int)
            encounter_id = c.q1(data, "encounter_id", int)
            workspace_id = c.q1(data, "workspace_id", int)
            limit = c.q1(data, "limit", int, 50)
            offset = c.q1(data, "offset", int, 0)
            if limit < 1 or limit > 200:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
            if offset < 0:
                raise HTTPException(status_code=422, detail="offset must be >= 0")

            if workspace_id is not None:
                await auth._require_workspace_permission(
                    user, workspace_id=workspace_id, resource="log", action="read"
                )
            elif tournament_id is not None:
                await auth.require_tournament_id_permission(
                    session, user, tournament_id=tournament_id, resource="log", action="read"
                )
            elif encounter_id is not None:
                workspace_id = await auth._get_encounter_workspace_id(session, encounter_id)
                await auth._require_workspace_permission(
                    user, workspace_id=workspace_id, resource="log", action="read"
                )
            elif not user.has_permission("log", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: log.read required")

            query = select(models.LogProcessingRecord).order_by(desc(models.LogProcessingRecord.created_at))
            count_query = select(models.LogProcessingRecord.id)

            if tournament_id is not None:
                query = query.where(models.LogProcessingRecord.tournament_id == tournament_id)
                count_query = count_query.where(models.LogProcessingRecord.tournament_id == tournament_id)
            if encounter_id is not None:
                query = query.where(models.LogProcessingRecord.attached_encounter_id == encounter_id)
                count_query = count_query.where(models.LogProcessingRecord.attached_encounter_id == encounter_id)
            if workspace_id is not None:
                query = query.join(
                    models.Tournament, models.LogProcessingRecord.tournament_id == models.Tournament.id
                ).where(models.Tournament.workspace_id == workspace_id)
                count_query = count_query.join(
                    models.Tournament, models.LogProcessingRecord.tournament_id == models.Tournament.id
                ).where(models.Tournament.workspace_id == workspace_id)

            count_result = await session.execute(count_query)
            total = len(count_result.scalars().all())

            result = await session.execute(query.limit(limit).offset(offset))
            items = [_record_to_dict(r) for r in result.scalars().all()]
            return {"items": items, "total": total}

        return await c.envelope(logger, "logs.history", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.retry")
    async def _retry(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/logs/{record_id}/retry — dependency: require_log_record_permission("log","reprocess").
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            record_id = c.require_id(data)
            workspace_id = await auth._get_log_record_workspace_id(session, record_id)
            await auth._require_workspace_permission(
                user, workspace_id=workspace_id, resource="log", action="reprocess"
            )

            result = await session.execute(
                select(models.LogProcessingRecord).where(models.LogProcessingRecord.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise HTTPException(status_code=404, detail="Log processing record not found")

            record.status = LogProcessingStatus.pending
            record.error_message = None
            record.started_at = None
            record.finished_at = None
            await session.commit()
            await session.refresh(record)

            event = ProcessMatchLogEvent(tournament_id=record.tournament_id, filename=record.filename)
            await publish_message(broker, event.model_dump(), PROCESS_MATCH_LOG_QUEUE, logger=logger)

            return LogRecordRead.model_validate(_record_to_dict(record))

        return await c.envelope(logger, "logs.retry", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.upload")
    async def _upload(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/logs/upload (multipart -> base64 via the gateway binary handler).
        # Mirrors upload_admin_logs: per-file errors are collected (HTTP 200 with an
        # errors list); pre-loop validation/permission failures propagate as errors.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            try:
                tournament_id = int(data["tournament_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="tournament_id is required") from exc
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="log", action="upload"
            )

            files = data.get("files") or []
            if not files:
                raise HTTPException(status_code=400, detail="At least one log file is required")
            filenames = [upload_service.validate_log_filename(f.get("filename")) for f in files]
            duplicate_names = sorted({name for name in filenames if filenames.count(name) > 1})
            if duplicate_names:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate file names in upload: {', '.join(duplicate_names)}",
                )

            tournament = await tournament_flows.get(session, tournament_id, [])
            raw_encounter = data.get("encounter_id")
            encounter_id = int(raw_encounter) if raw_encounter not in (None, "") else None
            attached_encounter = await _validate_attached_encounter(
                session, tournament_id=tournament.id, encounter_id=encounter_id
            )
            uploader_id = await upload_service.resolve_auth_uploader_id(session, user)

            uploaded: list[LogUploadItem] = []
            errors: list[LogUploadError] = []
            attached_encounter_id = attached_encounter.id if attached_encounter else None

            for file_obj, filename in zip(files, filenames, strict=True):
                try:
                    content = base64.b64decode(file_obj.get("content_b64") or "")
                    record = await upload_service.store_uploaded_log_bytes(
                        session,
                        s3=_clients.s3_client,
                        tournament_id=tournament.id,
                        filename=filename,
                        content=content,
                        source=LogProcessingSource.upload,
                        uploader_id=uploader_id,
                        attached_encounter_id=attached_encounter_id,
                    )
                    event = ProcessMatchLogEvent(tournament_id=tournament.id, filename=filename)
                    await publish_message(broker, event.model_dump(), PROCESS_MATCH_LOG_QUEUE, logger=logger)
                    uploaded.append(
                        LogUploadItem(
                            record_id=record.id,
                            filename=record.filename,
                            attached_encounter_id=record.attached_encounter_id,
                        )
                    )
                except HTTPException as exc:
                    errors.append(LogUploadError(filename=filename, error=str(exc.detail)))
                except Exception as exc:  # noqa: BLE001 - collected per-file, mirrors the route
                    logger.exception("Failed to upload and queue admin log %s", filename)
                    errors.append(LogUploadError(filename=filename, error=str(exc)))

            return LogUploadResponse(uploaded=uploaded, errors=errors)

        return await c.envelope(logger, "logs.upload", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.process_tournament")
    async def _process_tournament(data: dict, msg: RabbitMessage) -> dict:
        # POST /logs/{tournament_id} — router dep require_role_or_service_scope("admin","parser:logs");
        # the gateway path is the admin user (role "admin"); the bot path moves to RabbitMQ.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")
            tournament_id = c.require_id(data)
            tournament = await tournament_flows.get(session, tournament_id, [])
            event = ProcessTournamentLogsEvent(tournament_id=tournament.id)
            await publish_message(broker, event.model_dump(), PROCESS_TOURNAMENT_LOGS_QUEUE, logger=logger)
            return {"message": f"Processing all logs for tournament '{tournament.name}'"}

        return await c.envelope(logger, "logs.process_tournament", op, session_factory=_SF)
