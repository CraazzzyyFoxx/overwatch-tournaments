from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.schemas.base import BaseRead

__all__ = (
    "BalanceExportResponse",
    "BalanceRead",
    "BalanceSaveRequest",
    "BalancerTournamentConfigRead",
    "BalancerTournamentConfigUpsert",
    "RanksExportResponse",
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
    mix_discord_channel_id: str | None = Field(
        default=None,
        description=(
            "Workspace-wide Discord channel every mix posts its matchup to. "
            "A mix may name its own channel instead, but only a workspace admin can."
        ),
    )

    @field_validator("mix_discord_channel_id")
    @classmethod
    def _snowflake(cls, value: str | None) -> str | None:
        """Digits or ``None``: a snowflake outgrows a JavaScript safe integer,
        so it travels as a string -- same contract as the per-mix
        ``CustomGameDiscordChannelPatch.channel_id``. Empty means "no channel".
        """
        if value is None:
            return None
        trimmed = value.strip()
        if trimmed == "":
            return None
        if not trimmed.isdigit() or len(trimmed) > 20:
            raise ValueError("mix_discord_channel_id must be a Discord id (1-20 digits)")
        return trimmed


class WorkspaceBalancerConfigRead(BaseRead):
    workspace_id: int
    rank_delta_threshold: int | None
    rank_delta_hide_from_pool: bool
    mix_discord_channel_id: str | None = None
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


class RanksExportResponse(BaseModel):
    """Result of a rank-only re-export (balance or draft): nothing was created or removed."""

    success: bool
    updated_players: int
