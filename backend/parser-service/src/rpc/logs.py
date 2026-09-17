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

from faststream.rabbit import RabbitMessage
from sqlalchemy import desc, func, select

from shared import quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.config import PROCESS_MATCH_LOG_QUEUE, PROCESS_TOURNAMENT_LOGS_QUEUE
from shared.models.ingestion.log_processing import LogProcessingSource, LogProcessingStatus
from shared.observability import publish_message
from shared.schemas.events import ProcessMatchLogEvent, ProcessTournamentLogsEvent
from shared.services.audit import record_admin_audit
from src import models, schemas
from src.core import auth, db
from src.core import clients as _clients
from src.core.config import settings
from src.services.match_logs import uploads as upload_service
from src.services.match_logs.admin_reads import (
    _fetch_queue_depths,
    _record_to_dict,
    _validate_attached_encounter,
    history_scope_conditions,
    history_search_condition,
)
from src.services.match_logs.limits import match_log_oversize_message
from src.services.match_logs.log_records import log_records_service
from src.services.tournament import flows as tournament_flows

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

    @broker.subscriber("rpc.parser.logs.history")
    async def _history(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/logs/history — per-arg permission gating mirrors the route.
        async def op(session: Any) -> Any:
            tournament_id = c.q1(data, "tournament_id", int)
            encounter_id = c.q1(data, "encounter_id", int)
            limit = c.q1(data, "limit", int, 50)
            offset = c.q1(data, "offset", int, 0)
            status_filter = (c.q1(data, "status", str) or "").strip() or None
            search = c.q1(data, "search", str)
            if limit < 1 or limit > 200:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
            if offset < 0:
                raise HTTPException(status_code=422, detail="offset must be >= 0")
            if status_filter is not None and status_filter not in LogProcessingStatus.__members__:
                raise HTTPException(
                    status_code=422,
                    detail=f"status must be one of: {', '.join(LogProcessingStatus.__members__)}",
                )

            workspace_id = await _authorize_scope(
                session,
                data,
                tournament_id=tournament_id,
                encounter_id=encounter_id,
                workspace_id=c.q1(data, "workspace_id", int),
            )

            conditions = history_scope_conditions(
                tournament_id=tournament_id, encounter_id=encounter_id, workspace_id=workspace_id
            )
            if status_filter is not None:
                conditions.append(models.LogProcessingRecord.status == LogProcessingStatus[status_filter])
            search_condition = history_search_condition(search)
            if search_condition is not None:
                conditions.append(search_condition)

            # Aggregate count, not a full row fetch: the previous len(all()) pulled
            # every matching record over the wire just to size the page footer.
            total = await session.scalar(
                select(func.count()).select_from(models.LogProcessingRecord).where(*conditions)
            )

            result = await session.execute(
                select(models.LogProcessingRecord)
                .where(*conditions)
                .order_by(desc(models.LogProcessingRecord.created_at), desc(models.LogProcessingRecord.id))
                .limit(limit)
                .offset(offset)
            )
            items = [_record_to_dict(r) for r in result.scalars().all()]
            return {"items": items, "total": int(total or 0)}

        return await c.envelope(logger, "logs.history", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.stats")
    async def _stats(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/logs/stats — same scoping/gating as history, one aggregate row.
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

            record = models.LogProcessingRecord
            conditions = history_scope_conditions(
                tournament_id=tournament_id, encounter_id=encounter_id, workspace_id=workspace_id
            )
            duration = func.extract("epoch", record.finished_at - record.started_at)
            row = (
                await session.execute(
                    select(
                        func.count(),
                        *(
                            func.count().filter(record.status == member)
                            for member in (
                                LogProcessingStatus.pending,
                                LogProcessingStatus.processing,
                                LogProcessingStatus.done,
                                LogProcessingStatus.failed,
                            )
                        ),
                        # AVG skips NULL rows, so unfinished records drop out on their own.
                        func.avg(duration),
                        func.max(record.created_at),
                    )
                    .select_from(record)
                    .where(*conditions)
                )
            ).one()

            total, pending, processing, done, failed, avg_duration, last_created_at = row
            return schemas.LogStatsRead(
                total=int(total or 0),
                pending=int(pending or 0),
                processing=int(processing or 0),
                done=int(done or 0),
                failed=int(failed or 0),
                avg_duration_seconds=float(avg_duration) if avg_duration is not None else None,
                last_created_at=last_created_at,
            )

        return await c.envelope(logger, "logs.stats", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.retry")
    async def _retry(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/logs/{record_id}/retry — dependency: require_log_record_permission("log","update").
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            record_id = c.require_id(data)
            workspace_id = await auth._get_log_record_workspace_id(session, record_id)
            await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="update")

            # `log_records_service.retry` commits — stage the row on that session first.
            await record_admin_audit(
                session,
                action="match_log.retry",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="match_log",
                entity_id=record_id,
            )
            record = await log_records_service.retry(session, record_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Log processing record not found")

            event = ProcessMatchLogEvent(tournament_id=record.tournament_id, filename=record.filename)
            await publish_message(broker, event.model_dump(), PROCESS_MATCH_LOG_QUEUE, logger=logger)

            return schemas.LogRecordRead.model_validate(_record_to_dict(record))

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
                session, user, tournament_id=tournament_id, resource="log", action="create"
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
            # Each file costs an S3 write plus its own parse job on the match-log
            # queue, so the call is priced by both byte volume and file count.
            await quota.charge(
                user,
                "parser.logs.upload",
                workspace_id=tournament.workspace_id,
                size_bytes=sum(len(f.get("content_b64") or "") for f in files),
                item_count=len(files),
            )
            uploader_id = await upload_service.resolve_auth_uploader_id(session, user)

            uploaded: list[schemas.LogUploadItem] = []
            errors: list[schemas.LogUploadError] = []
            attached_encounter_id = attached_encounter.id if attached_encounter else None
            # One row for the call, staged before the first per-file commit inside
            # the loop. Names only — never the decoded bytes.
            await record_admin_audit(
                session,
                action="match_log.upload",
                actor=user,
                data=data,
                workspace_id=tournament.workspace_id,
                entity_type="tournament",
                entity_id=tournament.id,
                entity_label=tournament.name,
                after={"filenames": filenames},
            )

            max_log_bytes = settings.max_match_log_bytes
            for file_obj, filename in zip(files, filenames, strict=True):
                try:
                    raw_b64 = file_obj.get("content_b64") or ""
                    # Reject before decoding: base64 inflates ~4/3, so cap the
                    # encoded length first to avoid materializing a huge buffer.
                    if len(raw_b64) > (max_log_bytes // 3 + 1) * 4:
                        raise HTTPException(
                            status_code=413,
                            detail=match_log_oversize_message(max_log_bytes + 1, max_log_bytes),
                        )
                    content = base64.b64decode(raw_b64)
                    oversize = match_log_oversize_message(len(content), max_log_bytes)
                    if oversize:
                        raise HTTPException(status_code=413, detail=oversize)
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
                        schemas.LogUploadItem(
                            record_id=record.id,
                            filename=record.filename,
                            attached_encounter_id=record.attached_encounter_id,
                        )
                    )
                except HTTPException as exc:
                    errors.append(schemas.LogUploadError(filename=filename, error=str(exc.detail)))
                except Exception as exc:  # noqa: BLE001 - collected per-file, mirrors the route
                    logger.exception("Failed to upload and queue admin log %s", filename)
                    errors.append(schemas.LogUploadError(filename=filename, error=str(exc)))

            return schemas.LogUploadResponse(uploaded=uploaded, errors=errors)

        return await c.envelope(logger, "logs.upload", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.logs.process_tournament")
    async def _process_tournament(data: dict, msg: RabbitMessage) -> dict:
        # POST /logs/{tournament_id} — tournament-scoped log.update (the HTTP route
        # gated on the admin role); the bot path moves to RabbitMQ.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            tournament_id = c.require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="log", action="update"
            )
            tournament = await tournament_flows.get(session, tournament_id, [])
            # Fans out one parse job per stored log of the tournament — the cost is
            # the whole fan-out, not this ack.
            await quota.charge(user, "parser.logs.process_tournament", workspace_id=tournament.workspace_id)
            await record_admin_audit(
                session,
                action="match_log.process_tournament",
                actor=user,
                data=data,
                workspace_id=tournament.workspace_id,
                entity_type="tournament",
                entity_id=tournament.id,
                entity_label=tournament.name,
            )
            # Nothing else in this handler writes, so the row needs its own commit
            # before the event goes out.
            await session.commit()
            event = ProcessTournamentLogsEvent(tournament_id=tournament.id)
            await publish_message(broker, event.model_dump(), PROCESS_TOURNAMENT_LOGS_QUEUE, logger=logger)
            return {"message": f"Processing all logs for tournament '{tournament.name}'"}

        return await c.envelope(logger, "logs.process_tournament", op, session_factory=_SF)
