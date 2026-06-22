"""Pydantic schemas for the match-log admin surface.

Extracted verbatim from the former ``src/routes/admin/logs.py`` HTTP route so the
typed-RPC handlers (``src/rpc/logs.py``) keep emitting byte-identical payloads after
the FastAPI face was removed. These are pure response models — no FastAPI imports.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = (
    "QueueDepth",
    "LogRecordRead",
    "LogHistoryResponse",
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
