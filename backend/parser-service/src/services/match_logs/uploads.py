"""Shared helpers for storing uploaded match log files."""

from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from shared.clients.s3 import S3Client
from shared.models.log_processing import LogProcessingRecord, LogProcessingSource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.services.match_logs import log_records as record_service
from src.services.s3 import service as s3_service


def validate_log_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file name provided")

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid file name: {filename}")

    return filename


def decode_log_bytes(raw_bytes: bytes, filename: str | None) -> bytes:
    try:
        return raw_bytes.decode("utf-8").encode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File {filename or '<unnamed>'} is not valid UTF-8",
        ) from exc


async def resolve_auth_uploader_id(session: AsyncSession, auth_user: models.AuthUser | None) -> int | None:
    if auth_user is None:
        return None

    return await session.scalar(select(models.User.id).where(models.User.auth_user_id == auth_user.id))


async def store_uploaded_log_bytes(
    session: AsyncSession,
    *,
    s3: S3Client,
    tournament_id: int,
    filename: str | None,
    content: bytes,
    source: LogProcessingSource,
    uploader_id: int | None = None,
    attached_encounter_id: int | None = None,
) -> LogProcessingRecord:
    """Store an already-read log file (raw bytes) — shared by the multipart upload
    route and the gateway base64 / bot-RabbitMQ ingest paths."""
    filename = validate_log_filename(filename)
    decoded_bytes = decode_log_bytes(content, filename)

    uploaded = await s3_service.upload_log(s3, tournament_id, filename, decoded_bytes)
    if not uploaded:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to upload file {filename}")

    return await record_service.upsert_log_record(
        session,
        tournament_id=tournament_id,
        filename=filename,
        source=source,
        uploader_id=uploader_id,
        attached_encounter_id=attached_encounter_id,
    )
