"""Service helpers for creating and updating LogProcessingRecord entries."""

import hashlib
from datetime import UTC, datetime

from loguru import logger
from shared.models.log_processing import LogProcessingRecord, LogProcessingSource, LogProcessingStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def compute_content_hash(raw_bytes: bytes) -> str:
    """Return hex SHA-256 of the raw log file bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


async def is_already_processed(
    session: AsyncSession,
    tournament_id: int,
    filename: str,
    content_hash: str,
) -> bool:
    """Return True when a *done* record with the same content hash already exists.

    This lets us skip reprocessing an unchanged log file that was re-uploaded.
    """
    result = await session.execute(
        select(LogProcessingRecord)
        .where(
            LogProcessingRecord.tournament_id == tournament_id,
            LogProcessingRecord.filename == filename,
            LogProcessingRecord.status == LogProcessingStatus.done,
            LogProcessingRecord.content_hash == content_hash,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def upsert_log_record(
    session: AsyncSession,
    tournament_id: int,
    filename: str,
    source: LogProcessingSource,
    uploader_id: int | None = None,
    attached_encounter_id: int | None = None,
) -> LogProcessingRecord:
    """Create or refresh a log processing record. If a pending/failed record
    already exists for the same (tournament_id, filename), reuse it. Otherwise
    create a new one."""
    result = await session.execute(
        select(LogProcessingRecord)
        .where(
            LogProcessingRecord.tournament_id == tournament_id,
            LogProcessingRecord.filename == filename,
            LogProcessingRecord.status.in_([LogProcessingStatus.pending, LogProcessingStatus.failed]),
        )
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if record is None:
        record = LogProcessingRecord(
            tournament_id=tournament_id,
            filename=filename,
            source=source,
            status=LogProcessingStatus.pending,
            uploader_id=uploader_id,
            attached_encounter_id=attached_encounter_id,
        )
        session.add(record)
    else:
        record.source = source
        record.status = LogProcessingStatus.pending
        record.attached_encounter_id = attached_encounter_id
        record.error_message = None
        record.started_at = None
        record.finished_at = None
        if uploader_id is not None:
            record.uploader_id = uploader_id

    await session.commit()
    await session.refresh(record)
    return record


async def set_processing(
    session: AsyncSession,
    tournament_id: int,
    filename: str,
    content_hash: str | None = None,
) -> LogProcessingRecord | None:
    """Mark the most recent pending record as 'processing'."""
    result = await session.execute(
        select(LogProcessingRecord)
        .where(
            LogProcessingRecord.tournament_id == tournament_id,
            LogProcessingRecord.filename == filename,
        )
        .order_by(LogProcessingRecord.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if record is None:
        # No record created by upload — create one now for consumer-initiated processing
        record = LogProcessingRecord(
            tournament_id=tournament_id,
            filename=filename,
            source=LogProcessingSource.manual,
            status=LogProcessingStatus.processing,
            started_at=datetime.now(UTC),
            content_hash=content_hash,
        )
        session.add(record)
    else:
        record.status = LogProcessingStatus.processing
        record.started_at = datetime.now(UTC)
        record.error_message = None
        record.finished_at = None
        if content_hash is not None:
            record.content_hash = content_hash

    try:
        await session.commit()
    except Exception as exc:
        logger.warning(f"Failed to update log record to processing state: {exc}")
        await session.rollback()
        return None

    await session.refresh(record)
    return record


async def finish_duplicate_record(
    session: AsyncSession,
    tournament_id: int,
    filename: str,
    content_hash: str,
) -> LogProcessingRecord | None:
    """Mark the latest incomplete record as done when the uploaded content is a duplicate."""
    result = await session.execute(
        select(LogProcessingRecord)
        .where(
            LogProcessingRecord.tournament_id == tournament_id,
            LogProcessingRecord.filename == filename,
            LogProcessingRecord.status.in_(
                [
                    LogProcessingStatus.pending,
                    LogProcessingStatus.processing,
                    LogProcessingStatus.failed,
                ]
            ),
        )
        .order_by(LogProcessingRecord.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None

    if record.started_at is None:
        record.started_at = datetime.now(UTC)
    record.error_message = None
    record.content_hash = content_hash
    await set_done(session, record)
    return record


async def set_done(session: AsyncSession, record: LogProcessingRecord) -> None:
    """Mark a log processing record as done."""
    record.status = LogProcessingStatus.done
    record.finished_at = datetime.now(UTC)
    try:
        await session.commit()
    except Exception as exc:
        logger.warning(f"Failed to mark log record as done: {exc}")
        await session.rollback()


async def set_failed(session: AsyncSession, record: LogProcessingRecord, error: str) -> None:
    """Mark a log processing record as failed."""
    record.status = LogProcessingStatus.failed
    record.finished_at = datetime.now(UTC)
    record.error_message = error[:2000]  # guard against huge tracebacks
    try:
        await session.commit()
    except Exception as exc:
        logger.warning(f"Failed to mark log record as failed: {exc}")
        await session.rollback()
