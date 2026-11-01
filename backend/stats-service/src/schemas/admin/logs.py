"""Pydantic schemas for the match-log admin surface (``src/rpc/logs.py``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from shared.models import RawSourceStatus
from src.schemas.ingest import IngestError, IngestTeamKey

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
    # Binding hint for awaiting_link. Omitted = keep the current attachment.
    encounter_id: int | None = None
    encounter_game_id: int | None = None
    # A done job is replayed only by an explicit reparse that names the observation revision the operator saw;
    # a stale revision answers 409 ``stale_revision``.
    reparse: bool = False
    expected_revision: int | None = None


class LogRecordRead(BaseModel):
    id: int
    tournament_id: int | None
    tournament_name: str | None
    # The mix owning the linked match's encounter (else the hinted one); ``None`` for tournament jobs.
    custom_game_id: int | None = None
    custom_game_name: str | None = None
    attached_encounter_id: int | None
    attached_encounter_game_id: int | None
    attached_encounter_name: str | None
    filename: str
    status: str
    source: str
    raw_status: RawSourceStatus
    raw_available: bool
    uploader_name: str | None
    # The human message of ``error`` (or the historical text itself).
    error_message: str | None
    # Structured failure/awaiting explanation of a canonical job; historical text reads as code ``historical``.
    error: IngestError | None = None
    # Times the record entered processing; >1 means the stall reaper requeued it.
    attempts: int = 0
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Revision of the observation this job is currently the evidence for; ``None`` while it is not (unbound,
    # awaiting link, failed or superseded). Bulk reparse sends it back as ``expected_revision``.
    observation_revision: int | None = None
    # ``True`` while this job is the current provenance of its game's observation.
    is_current_provenance: bool = False
    # Document teams in canonical order for an ``awaiting_link`` or ``failed`` job with a stored document (the bind
    # team map is keyed by these).
    teams: list[IngestTeamKey] = []

    model_config = {"from_attributes": True}


class LogHistoryResponse(BaseModel):
    items: list[LogRecordRead]
    total: int


class LogStatsRead(BaseModel):
    """Scope-wide (not per-page) processing aggregate, computed in one SQL round trip."""

    total: int
    pending: int
    processing: int
    done: int
    failed: int
    awaiting_link: int
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
