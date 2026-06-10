from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.schemas.base import BaseRead

__all__ = (
    "BalanceExportResponse",
    "BalanceRead",
    "BalanceSaveRequest",
    "BalancerTournamentConfigRead",
    "BalancerTournamentConfigUpsert",
    "WorkspaceBalancerConfigRead",
    "WorkspaceBalancerConfigUpsert",
)


class BalanceSaveRequest(BaseModel):
    config_json: dict[str, Any] | None = None
    result_json: dict[str, Any]


class BalancerTournamentConfigUpsert(BaseModel):
    config_json: dict[str, Any] | None = None


class BalancerTournamentConfigRead(BaseRead):
    tournament_id: int
    workspace_id: int
    config_json: dict[str, Any]
    updated_by: int | None = None
    updated_at: datetime | None = None


class WorkspaceBalancerConfigUpsert(BaseModel):
    rank_delta_threshold: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        description="Absolute rank-point delta above which a player is flagged. Null disables the feature.",
    )
    rank_delta_hide_from_pool: bool = False


class WorkspaceBalancerConfigRead(BaseRead):
    workspace_id: int
    rank_delta_threshold: int | None
    rank_delta_hide_from_pool: bool
    updated_by: int | None = None


class BalanceRead(BaseRead):
    tournament_id: int
    config_json: dict[str, Any] | None = None
    result_json: dict[str, Any]
    saved_by: int | None
    saved_at: datetime
    exported_at: datetime | None = None
    export_status: str | None = None
    export_error: str | None = None


class BalanceExportResponse(BaseModel):
    success: bool
    removed_teams: int
    imported_teams: int
    balance_id: int
