"""Pydantic schemas for the match-log admin surface.

Extracted verbatim from the former ``src/routes/admin/logs.py`` HTTP route so the
typed-RPC handlers (``src/rpc/logs.py``) keep emitting byte-identical payloads after
the FastAPI face was removed. No FastAPI imports.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = (
    "QueueDepth",
    "LogRecordRead",
    "LogHistoryResponse",
    "LogRetryRequest",
    "LogStatsRead",
    "LogUploadItem",
    "LogUploadError",
    "LogUploadResponse",
)


class QueueDepth(BaseModel):
    name: str
    messages_ready: int
    messages_unacknowledged: int
    consumers: int
    status: str = "ok"  # "ok" | "not_found" | "error"


class LogRetryRequest(BaseModel):
    # Attaches the log to this encounter before requeueing it: the way out of an
    # `encounter_ambiguous` failure. Omitted = keep the current attachment.
    encounter_id: int | None = None


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
    # Times the record entered processing; >1 means the stall reaper requeued it.
    attempts: int = 0
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class LogHistoryResponse(BaseModel):
    items: list[LogRecordRead]
    total: int


class LogStatsRead(BaseModel):
    """Scope-wide processing aggregate, computed in one SQL round trip.

    The admin console used to derive these from the page it happened to be
    showing, so "Failed: 0" only ever meant "none on this page".
    """

    total: int
    pending: int
    processing: int
    done: int
    failed: int
    avg_duration_seconds: float | None
    last_created_at: datetime | None


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
