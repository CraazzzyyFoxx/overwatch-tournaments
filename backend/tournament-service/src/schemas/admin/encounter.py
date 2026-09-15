from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.core.enums import EncounterResultAuditAction, EncounterResultStatus, EncounterStatus

__all__ = (
    "EncounterCreate",
    "EncounterUpdate",
    "MatchUpdate",
    "EncounterSetResultInput",
    "EncounterResultRead",
    "EncounterResultAuditRead",
    "EncounterSwapSlotInput",
    "EncounterSlotRead",
    "EncounterSlotSwapRead",
)


class EncounterCreate(BaseModel):
    """Schema for creating an encounter"""

    name: str
    tournament_id: int
    stage_id: int | None = None
    stage_item_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    round: int
    best_of: int = Field(default=3, ge=1)
    home_score: int = 0
    away_score: int = 0
    status: str = "open"  # open, pending, completed
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    current_map_index: int | None = None


class EncounterUpdate(BaseModel):
    """Schema for updating an encounter"""

    name: str | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    status: str | None = None
    round: int | None = None
    best_of: int | None = Field(default=None, ge=1)
    closeness: float | None = Field(default=None, ge=0.0, le=1.0)
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    current_map_index: int | None = None


class MatchUpdate(BaseModel):
    """Partial update for a single match (map) within an encounter."""

    home_team_id: int | None = None
    away_team_id: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    map_id: int | None = None
    code: str | None = None
    time: float | None = None


class EncounterSetResultInput(BaseModel):
    """Body of the single admin result write.

    Every field is optional: an empty body means "confirm what is already
    there", which covers the common case of two agreeing reports. Supplying
    ``adopt_report_team_id`` is how a dispute is resolved in one call — "this
    side was right" — instead of editing the score and confirming separately.
    """

    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    closeness: int | None = Field(default=None, ge=1, le=10)
    adopt_report_team_id: int | None = None


class EncounterSwapSlotInput(BaseModel):
    """Body of the bracket slot swap: which slot here, which slot there.

    Both sides are named explicitly so one endpoint covers the two moves the
    bracket offers -- dragging a team onto another encounter's slot, and
    flipping home/away inside one encounter (same ``target_encounter_id``,
    the other ``target_slot``).
    """

    slot: Literal["home", "away"]
    target_encounter_id: int
    target_slot: Literal["home", "away"]


class EncounterSlotRead(BaseModel):
    """One side of a swap: the slots it now holds, and the rebuilt name."""

    id: int
    home_team_id: int | None
    away_team_id: int | None
    name: str


class EncounterSlotSwapRead(BaseModel):
    """Both encounters the swap touched (the same one twice on a home/away flip)."""

    source: EncounterSlotRead
    target: EncounterSlotRead


class EncounterResultRead(BaseModel):
    """What the result endpoints return: the settled state of the encounter."""

    id: int
    status: EncounterStatus
    result_status: EncounterResultStatus
    home_score: int
    away_score: int
    closeness: float | None
    confirmed_at: datetime | None


class EncounterResultAuditRead(BaseModel):
    """One recorded transition. ``actor_user_id`` is NULL for a machine actor."""

    id: int
    encounter_id: int
    actor_user_id: int | None
    actor_name: str | None
    action: EncounterResultAuditAction
    from_result_status: EncounterResultStatus | None
    to_result_status: EncounterResultStatus
    home_score_before: int | None
    away_score_before: int | None
    home_score_after: int
    away_score_after: int
    adopted_team_id: int | None
    source: str
    created_at: datetime
