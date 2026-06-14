"""Admin routes for log processing monitoring: history, queue status, and SSE stream."""

import asyncio
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent
from loguru import logger
from pydantic import BaseModel
from shared.clients.s3 import S3Client
from shared.messaging.config import PROCESS_MATCH_LOG_QUEUE
from shared.models.log_processing import LogProcessingSource, LogProcessingStatus
from shared.observability import publish_message
from shared.schemas.events import ProcessMatchLogEvent
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, config, db
from src.routes.match_logs import get_s3, task_router
from src.services.match_logs import uploads as upload_service
from src.services.tournament import flows as tournament_flows

router = APIRouter(
    prefix="/logs",
    tags=["admin", "logs"],
)

MONITORED_QUEUES = [
    "process_match_log",
    "process_tournament_logs",
    "discord_commands",
    "balancer_jobs",
]


# ─── Response schemas ────────────────────────────────────────────────────────


class QueueDepth(BaseModel):
    name: str
    messages_ready: int
    messages_unacknowledged: int
    consumers: int
    status: str = "ok"  # "ok" | "not_found" | "error"


class LogRecordRead(BaseModel):
    id: int
    tournament_id: int
    tournament_name: str | None
    attached_encounter_id: int | None
    attached_encounter_name: str | None
    filename: str
    status: str
    source: str
    uploader_name: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class LogHistoryResponse(BaseModel):
    items: list[LogRecordRead]
    total: int


class LogUploadItem(BaseModel):
    record_id: int
    filename: str
    attached_encounter_id: int | None


class LogUploadError(BaseModel):
    filename: str | None
    error: str


class LogUploadResponse(BaseModel):
    uploaded: list[LogUploadItem]
    errors: list[LogUploadError]


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _fetch_queue_depths() -> list[QueueDepth]:
    """Query RabbitMQ Management API for queue depths."""
    cfg = config.settings
    base = cfg.rabbitmq_management_url.rstrip("/")
    auth_tuple = (cfg.rabbitmq_management_user, cfg.rabbitmq_management_password)
    depths: list[QueueDepth] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for queue_name in MONITORED_QUEUES:
                url = f"{base}/api/queues/%2F/{queue_name}"
                resp = await client.get(url, auth=auth_tuple)
                if resp.status_code == 200:
                    data = resp.json()
                    depths.append(
                        QueueDepth(
                            name=queue_name,
                            messages_ready=data.get("messages_ready", 0),
                            messages_unacknowledged=data.get("messages_unacknowledged", 0),
                            consumers=data.get("consumers", 0),
                        )
                    )
                elif resp.status_code == 404:
                    depths.append(QueueDepth(name=queue_name, messages_ready=-1, messages_unacknowledged=-1, consumers=0, status="not_found"))
                else:
                    depths.append(QueueDepth(name=queue_name, messages_ready=-1, messages_unacknowledged=-1, consumers=0, status="error"))
    except Exception as exc:
        logger.warning(f"Failed to fetch queue depths from RabbitMQ management API: {exc}")
        for queue_name in MONITORED_QUEUES:
            depths.append(QueueDepth(name=queue_name, messages_ready=-1, messages_unacknowledged=-1, consumers=0, status="error"))
    return depths


def _record_to_dict(record: models.LogProcessingRecord) -> dict:
    return {
        "id": record.id,
        "tournament_id": record.tournament_id,
        "tournament_name": record.tournament.name if record.tournament else None,
        "attached_encounter_id": record.attached_encounter_id,
        "attached_encounter_name": record.attached_encounter.name if record.attached_encounter else None,
        "filename": record.filename,
        "status": record.status.value if hasattr(record.status, "value") else record.status,
        "source": record.source.value if hasattr(record.source, "value") else record.source,
        "uploader_name": record.uploader.name if record.uploader else None,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


async def _fetch_recent_records(session: AsyncSession, limit: int = 20, workspace_id: int | None = None) -> list[dict]:
    query = select(models.LogProcessingRecord).order_by(desc(models.LogProcessingRecord.created_at))
    if workspace_id is not None:
        query = query.join(models.Tournament, models.LogProcessingRecord.tournament_id == models.Tournament.id).where(
            models.Tournament.workspace_id == workspace_id
        )
    result = await session.execute(query.limit(limit))
    return [_record_to_dict(r) for r in result.scalars().all()]


def _validate_upload_filenames(files: list[UploadFile]) -> list[str]:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one log file is required")

    filenames = [upload_service.validate_log_filename(file.filename) for file in files]
    duplicate_names = sorted({name for name in filenames if filenames.count(name) > 1})
    if duplicate_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate file names in upload: {', '.join(duplicate_names)}",
        )
    return filenames


async def _validate_attached_encounter(
    session: AsyncSession,
    *,
    tournament_id: int,
    encounter_id: int | None,
) -> models.Encounter | None:
    if encounter_id is None:
        return None

    result = await session.execute(select(models.Encounter).where(models.Encounter.id == encounter_id).limit(1))
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    if encounter.tournament_id != tournament_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encounter does not belong to this tournament",
        )
    return encounter


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=LogUploadResponse,
)
async def upload_admin_logs(
    tournament_id: int = Form(...),
    files: list[UploadFile] = File(..., alias="files[]"),
    encounter_id: int | None = Form(None),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
    s3: S3Client = Depends(get_s3),
):
    """Upload one or more match logs from the admin panel and queue each for processing."""
    await auth.require_tournament_id_permission(
        session,
        user,
        tournament_id=tournament_id,
        resource="log",
        action="upload",
    )
    filenames = _validate_upload_filenames(files)
    tournament = await tournament_flows.get(session, tournament_id, [])
    attached_encounter = await _validate_attached_encounter(
        session,
        tournament_id=tournament.id,
        encounter_id=encounter_id,
    )
    uploader_id = await upload_service.resolve_auth_uploader_id(session, user)

    uploaded: list[LogUploadItem] = []
    errors: list[LogUploadError] = []
    attached_encounter_id = attached_encounter.id if attached_encounter else None

    for file, filename in zip(files, filenames, strict=True):
        try:
            record = await upload_service.store_uploaded_log(
                session,
                s3=s3,
                tournament_id=tournament.id,
                uploaded_file=file,
                source=LogProcessingSource.upload,
                uploader_id=uploader_id,
                attached_encounter_id=attached_encounter_id,
            )
            event = ProcessMatchLogEvent(tournament_id=tournament.id, filename=filename)
            await publish_message(task_router.broker, event.model_dump(), PROCESS_MATCH_LOG_QUEUE, logger=logger)
            uploaded.append(
                LogUploadItem(
                    record_id=record.id,
                    filename=record.filename,
                    attached_encounter_id=record.attached_encounter_id,
                )
            )
        except HTTPException as exc:
            errors.append(LogUploadError(filename=filename, error=str(exc.detail)))
        except Exception as exc:
            logger.exception(f"Failed to upload and queue admin log {filename}")
            errors.append(LogUploadError(filename=filename, error=str(exc)))

    return LogUploadResponse(uploaded=uploaded, errors=errors)


@router.get(
    "/queue-status",
    response_model=list[QueueDepth],
    dependencies=[Depends(auth.require_permission("log", "read"))],
)
async def get_queue_status():
    """Get current RabbitMQ queue depths for all monitored queues."""
    return await _fetch_queue_depths()


@router.get(
    "/history",
)
async def get_log_history(
    tournament_id: int | None = Query(None),
    encounter_id: int | None = Query(None),
    workspace_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Get paginated log processing history, optionally filtered by tournament or workspace."""
    if workspace_id is not None:
        await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="read")
    elif tournament_id is not None:
        await auth.require_tournament_id_permission(
            session,
            user,
            tournament_id=tournament_id,
            resource="log",
            action="read",
        )
    elif encounter_id is not None:
        workspace_id = await auth._get_encounter_workspace_id(session, encounter_id)
        await auth._require_workspace_permission(user, workspace_id=workspace_id, resource="log", action="read")
    elif not user.has_permission("log", "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: log.read required")

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


@router.post(
    "/{record_id}/retry",
    response_model=LogRecordRead,
)
async def retry_log_record(
    record_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_log_record_permission("log", "reprocess")),
):
    """Reset a failed/pending log record to pending and re-queue it for processing."""
    result = await session.execute(
        select(models.LogProcessingRecord).where(models.LogProcessingRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log processing record not found")

    record.status = LogProcessingStatus.pending
    record.error_message = None
    record.started_at = None
    record.finished_at = None
    await session.commit()
    await session.refresh(record)

    event = ProcessMatchLogEvent(tournament_id=record.tournament_id, filename=record.filename)
    await publish_message(task_router.broker, event.model_dump(), PROCESS_MATCH_LOG_QUEUE, logger=logger)

    return LogRecordRead.model_validate(_record_to_dict(record))


async def _require_sse_token(token: str = Query(..., description="JWT access token")) -> None:
    """Dependency that validates the SSE token query param (EventSource can't send headers)."""
    import main

    payload = await main.auth_client.validate_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.get("/stream", response_class=EventSourceResponse, dependencies=[Depends(_require_sse_token)])
async def stream_log_status(
    token: str = Query(..., description="JWT access token for authentication"),
    workspace_id: int | None = Query(None, description="Filter recent logs by workspace"),
):
    """SSE stream: emits queue depths + recent log processing updates every 2 seconds.

    The endpoint must be an async generator so FastAPI's native SSE machinery can
    iterate it directly.  A regular ``async def`` that *returns* a generator causes
    Starlette to try ``iter(<coroutine>)`` which raises TypeError.
    """
    async with db.async_session_maker() as session:
        # Initial keepalive so the browser knows the connection is open
        yield ServerSentEvent(comment="connected")

        while True:
            try:
                queues = await _fetch_queue_depths()
                recent = await _fetch_recent_records(session, limit=20, workspace_id=workspace_id)

                payload_data = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "queues": [q.model_dump() for q in queues],
                    "recent_logs": recent,
                }
                yield ServerSentEvent(data=payload_data, event="update")
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(f"SSE stream error: {exc}")
                yield ServerSentEvent(data={"error": str(exc)}, event="error")

            await asyncio.sleep(2)
