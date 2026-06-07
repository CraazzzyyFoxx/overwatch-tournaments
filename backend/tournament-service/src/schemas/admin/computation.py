from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class TournamentComputationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Literal["bracket", "standings"]
    operation: str
    tournament_id: int
    stage_id: int | None
    stage_item_id: int | None
    status: Literal["pending", "running", "succeeded", "failed", "superseded"]
    payload_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error: str | None
    requested_by_user_id: int | None
    idempotency_key: str
    attempts: int
    created_at: datetime
    updated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
