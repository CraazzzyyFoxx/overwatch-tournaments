"""Pydantic DTOs for the Live Draft REST API.

Request models validate at the system boundary; read models carry the data the
public ``/board`` snapshot and admin views need. Enum-like fields use the
shared StrEnums so values are validated and serialize to their string form.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.core.enums import (
    DraftAutopickStrategy,
    DraftCaptainOrder,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftPoolSource,
    DraftRole,
    DraftStatus,
)

from src.schemas.base import BaseRead

__all__ = (
    "DraftBoardSnapshot",
    "DraftOrderEntry",
    "DraftOrderRequest",
    "DraftPickAutopickRequest",
    "DraftPickOverrideRequest",
    "DraftPickRead",
    "DraftPickSelectRequest",
    "DraftPlayerRead",
    "DraftSeedRequest",
    "DraftSessionCreateRequest",
    "DraftSessionPatchRequest",
    "DraftSessionRead",
    "DraftSuggestion",
    "DraftSuggestionsResponse",
    "DraftTeamRead",
)

_ReadConfig = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class DraftSessionCreateRequest(BaseModel):
    pool_source: DraftPoolSource = DraftPoolSource.BALANCER_BALANCE
    source_balance_id: int | None = None
    format: DraftFormat = DraftFormat.SNAKE
    rounds: int = 4
    pick_time_seconds: int = 45
    team_size: int = 5
    autopick_strategy: DraftAutopickStrategy = DraftAutopickStrategy.BEST_FIT
    allow_admin_override: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rounds")
    @classmethod
    def _rounds_range(cls, v: int) -> int:
        if not 1 <= v <= 8:
            raise ValueError("rounds must be between 1 and 8")
        return v

    @field_validator("pick_time_seconds")
    @classmethod
    def _pick_time_range(cls, v: int) -> int:
        if not 10 <= v <= 600:
            raise ValueError("pick_time_seconds must be between 10 and 600")
        return v

    @field_validator("team_size")
    @classmethod
    def _team_size_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError("team_size must be between 1 and 12")
        return v


class DraftManualCaptainInput(BaseModel):
    user_id: int | None = None
    battle_tag: str | None = None
    name: str
    draft_position: int


class DraftManualPlayerInput(BaseModel):
    user_id: int | None = None
    battle_tag: str | None = None
    primary_role: DraftRole
    secondary_roles: list[DraftRole] = Field(default_factory=list)
    sub_role: str | None = None
    is_flex: bool = False
    division_number: int | None = None
    rank_value: int | None = None


class DraftPoolCaptainInput(BaseModel):
    """A captain chosen from the balancer pool (by balancer.registration id)."""

    registration_id: int
    name: str | None = None


class DraftSeedRequest(BaseModel):
    source_balance_id: int | None = None
    seed: int | None = None
    # Seat order for captains (who picks first). WEAKEST_FIRST seats the lowest-
    # rated captain at position 1; snake then balances across rounds.
    captain_order: DraftCaptainOrder = DraftCaptainOrder.MANUAL
    # Pool-derived seeding (preferred): captains picked from the balancer pool;
    # every other in-pool player becomes available. Roles/ranks come from the pool.
    pool_captains: list[DraftPoolCaptainInput] = Field(default_factory=list)
    # Manual seeding fallback.
    captains: list[DraftManualCaptainInput] = Field(default_factory=list)
    players: list[DraftManualPlayerInput] = Field(default_factory=list)


class DraftSessionPatchRequest(BaseModel):
    pick_time_seconds: int | None = None
    autopick_strategy: DraftAutopickStrategy | None = None
    allow_admin_override: bool | None = None
    rounds: int | None = None
    settings: dict[str, Any] | None = None

    @field_validator("pick_time_seconds")
    @classmethod
    def _pick_time_range(cls, v: int | None) -> int | None:
        if v is not None and not 10 <= v <= 600:
            raise ValueError("pick_time_seconds must be between 10 and 600")
        return v


class DraftOrderEntry(BaseModel):
    draft_team_id: int
    draft_position: int


class DraftOrderRequest(BaseModel):
    order: list[DraftOrderEntry]

    @model_validator(mode="after")
    def _positions_are_permutation(self) -> DraftOrderRequest:
        positions = sorted(e.draft_position for e in self.order)
        if positions != list(range(1, len(self.order) + 1)):
            raise ValueError("draft_position values must be a permutation of 1..N")
        team_ids = [e.draft_team_id for e in self.order]
        if len(set(team_ids)) != len(team_ids):
            raise ValueError("draft_team_id values must be unique")
        return self


class DraftPickSelectRequest(BaseModel):
    player_id: int
    expected_version: int
    target_role: DraftRole | None = None


class DraftPickAutopickRequest(BaseModel):
    expected_version: int
    reason: Literal["expiry", "admin"] = "expiry"


class DraftPickOverrideRequest(BaseModel):
    expected_version: int
    player_id: int | None = None
    draft_team_id: int | None = None
    target_role: DraftRole | None = None
    note: str | None = None


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
class DraftTeamRead(BaseRead):
    model_config = _ReadConfig

    session_id: int
    captain_user_id: int | None
    captain_auth_user_id: int | None
    name: str
    draft_position: int
    exported_team_id: int | None


class DraftPlayerRead(BaseRead):
    model_config = _ReadConfig

    session_id: int
    user_id: int | None
    battle_tag: str | None
    primary_role: str
    sub_role: str | None
    is_flex: bool
    division_number: int | None
    rank_value: int | None
    status: DraftPlayerStatus
    is_captain: bool
    drafted_by_team_id: int | None
    secondary_roles_json: list[str] | None = None
    role_ranks: dict[str, int] = Field(default_factory=dict)
    role_top_heroes: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    additional_info: dict[str, Any] = Field(default_factory=dict)


class DraftPickRead(BaseRead):
    model_config = _ReadConfig

    session_id: int
    overall_no: int
    round_no: int
    pick_in_round: int
    draft_team_id: int
    target_role: str | None
    target_rank_value: int | None
    status: DraftPickStatus
    picked_player_id: int | None
    picked_by_user_id: int | None
    is_autopick: bool
    is_admin_override: bool
    clock_started_at: datetime | None
    clock_expires_at: datetime | None
    version: int


class DraftSessionRead(BaseRead):
    model_config = _ReadConfig

    tournament_id: int
    workspace_id: int
    status: DraftStatus
    format: DraftFormat
    rounds: int
    pick_time_seconds: int
    team_size: int
    current_pick_id: int | None
    pool_source: DraftPoolSource
    source_balance_id: int | None
    autopick_strategy: DraftAutopickStrategy
    allow_admin_override: bool
    exported_at: datetime | None
    export_status: str | None
    settings_json: dict[str, Any]


class DraftBoardSnapshot(BaseModel):
    """Single-shot spectator/captain bootstrap + realtime resume cursor."""

    session: DraftSessionRead
    teams: list[DraftTeamRead]
    picks: list[DraftPickRead]
    players: list[DraftPlayerRead]  # all pool players; client derives availability + rosters
    current_pick: DraftPickRead | None
    server_time: datetime
    last_event_id: int | None = None


class DraftSuggestion(BaseModel):
    player_id: int
    role: DraftRole
    fit_score: float
    breakdown: dict[str, float] = Field(default_factory=dict)


class DraftSuggestionsResponse(BaseModel):
    pick_id: int
    draft_team_id: int
    suggestions: list[DraftSuggestion]
