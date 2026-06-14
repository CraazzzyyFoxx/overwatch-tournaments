from pydantic import BaseModel, Field, model_validator

__all__ = (
    "EncounterCreate",
    "EncounterUpdate",
    "BulkEncounterUpdate",
    "MatchUpdate",
)


class EncounterCreate(BaseModel):
    """Schema for creating an encounter"""

    name: str
    tournament_id: int
    tournament_group_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    round: int
    home_score: int = 0
    away_score: int = 0
    status: str = "open"  # open, pending, completed


class EncounterUpdate(BaseModel):
    """Schema for updating an encounter"""

    name: str | None = None
    tournament_group_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    status: str | None = None
    round: int | None = None
    closeness: float | None = Field(default=None, ge=0.0, le=1.0)


class MatchUpdate(BaseModel):
    """Partial update for a single match (map) within an encounter."""

    home_team_id: int | None = None
    away_team_id: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    map_id: int | None = None
    code: str | None = None
    time: float | None = None
    log_name: str | None = None


class BulkEncounterUpdate(BaseModel):
    """Apply the same update to many encounters in a single transaction.

    Supports the high-frequency admin operations on 40+ team tournaments:
    - mass-set status (e.g. "mark all group R1 matches as COMPLETED")
    - mass-reschedule (when a matchday moves by 30 minutes)
    - clear scores (rollback after wrong data entry)

    Triggers exactly one standings recalc per affected tournament, not N —
    crucial for keeping admin UI responsive on bulk actions.
    """

    encounter_ids: list[int] = Field(min_length=1, max_length=500)
    status: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    reset_scores: bool = False  # if True, forces home_score=away_score=0

    @model_validator(mode="after")
    def _validate_some_update(self) -> "BulkEncounterUpdate":
        has_update = (
            self.status is not None
            or self.home_score is not None
            or self.away_score is not None
            or self.reset_scores
        )
        if not has_update:
            raise ValueError(
                "Bulk update must specify at least one field (status, home_score, away_score, reset_scores)"
            )
        if self.reset_scores and (self.home_score is not None or self.away_score is not None):
            raise ValueError("reset_scores is mutually exclusive with explicit scores")
        return self
