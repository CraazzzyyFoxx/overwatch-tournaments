from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

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
    "WorkspaceRankerRead",
    "WorkspaceRankerRebuildRead",
    "WorkspaceRankerUpsert",
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


def _snowflake_or_none(value: str | None, field: str) -> str | None:
    """Digits or ``None``: a snowflake outgrows a JavaScript safe integer, so it
    travels as a string -- same contract as the per-mix
    ``CustomGameDiscordChannelPatch.channel_id``. Empty means "none".
    """
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "":
        return None
    if not trimmed.isdigit() or len(trimmed) > 20:
        raise ValueError(f"{field} must be a Discord id (1-20 digits)")
    return trimmed


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
    mix_voice_category_id: str | None = Field(
        default=None, description="Discord category whose voice channels mixes move players between."
    )
    mix_general_voice_channel_ids: list[str] = Field(
        default_factory=list,
        max_length=25,
        description="Voices of that category players wait in and are returned to; every other voice is a team voice.",
    )

    @field_validator("mix_discord_channel_id", "mix_voice_category_id")
    @classmethod
    def _snowflake(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _snowflake_or_none(value, info.field_name)

    @field_validator("mix_general_voice_channel_ids")
    @classmethod
    def _general(cls, values: list[str]) -> list[str]:
        cleaned = [_snowflake_or_none(value, "mix_general_voice_channel_ids") for value in values]
        return list(dict.fromkeys(value for value in cleaned if value is not None))

    @model_validator(mode="after")
    def _general_needs_category(self) -> WorkspaceBalancerConfigUpsert:
        """A general voice is one of the category's voices: without a category
        there is nothing to tell a general voice from a team voice."""
        if self.mix_general_voice_channel_ids and self.mix_voice_category_id is None:
            raise ValueError("mix_general_voice_channel_ids needs mix_voice_category_id")
        return self


class WorkspaceBalancerConfigRead(BaseRead):
    workspace_id: int
    rank_delta_threshold: int | None
    rank_delta_hide_from_pool: bool
    mix_discord_channel_id: str | None = None
    mix_voice_category_id: str | None = None
    mix_general_voice_channel_ids: list[str] = Field(default_factory=list)
    updated_by: int | None = None


_RANKER_DOCS = {
    "rating_min": "Lowest open rating the ranker maps onto.",
    "rating_max": "Highest open rating the ranker maps onto.",
    "rating_avg": "The open rating an average player holds; the hidden scale is centred on it.",
    "gravity": "How strongly an uncertain hidden rating is pulled towards the average (the specification's g).",
    "gate_steepness": "How sharply the correction switches from 'ignore' to 'apply' (the specification's d).",
    "sigma_init": "A newcomer's hidden uncertainty; also sets the hidden scale.",
    "variant": (
        "'corrected' follows the hidden rating by its own uncertainty; 'reference' scales by the whole "
        "open range, as the original specification does."
    ),
}


class WorkspaceRankerUpsert(BaseModel):
    """A full replacement of the workspace's mix ranker knobs.

    Changing ``rating_min``, ``rating_max``, ``rating_avg`` or ``sigma_init``
    reinterprets every stored hidden rating, so the save rebuilds them from the
    workspace's match history before it answers.
    """

    model_config = ConfigDict(extra="forbid")

    rating_min: float = Field(ge=0, le=100000, description=_RANKER_DOCS["rating_min"])
    rating_max: float = Field(ge=0, le=100000, description=_RANKER_DOCS["rating_max"])
    rating_avg: float = Field(ge=0, le=100000, description=_RANKER_DOCS["rating_avg"])
    gravity: float = Field(ge=0, le=10, description=_RANKER_DOCS["gravity"])
    gate_steepness: float = Field(gt=0, le=50, description=_RANKER_DOCS["gate_steepness"])
    sigma_init: float = Field(gt=0, le=1000, description=_RANKER_DOCS["sigma_init"])
    variant: Literal["reference", "corrected"] = Field(description=_RANKER_DOCS["variant"])

    @model_validator(mode="after")
    def _ordered(self) -> WorkspaceRankerUpsert:
        if not self.rating_min < self.rating_avg < self.rating_max:
            raise ValueError("rating_min < rating_avg < rating_max is required")
        return self


class WorkspaceRankerRead(BaseModel):
    """The knobs in force (defaults when never saved) and how many hidden ratings exist."""

    workspace_id: int
    rating_min: float = Field(description=_RANKER_DOCS["rating_min"])
    rating_max: float = Field(description=_RANKER_DOCS["rating_max"])
    rating_avg: float = Field(description=_RANKER_DOCS["rating_avg"])
    gravity: float = Field(description=_RANKER_DOCS["gravity"])
    gate_steepness: float = Field(description=_RANKER_DOCS["gate_steepness"])
    sigma_init: float = Field(description=_RANKER_DOCS["sigma_init"])
    variant: Literal["reference", "corrected"] = Field(description=_RANKER_DOCS["variant"])
    hidden_ratings: int = Field(description="Hidden ratings stored for this workspace's members, one per role.")


class WorkspaceRankerRebuildRead(BaseModel):
    matches: int = Field(description="Recorded mix matches replayed.")
    hidden_ratings: int = Field(description="Hidden ratings the replay produced.")


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
