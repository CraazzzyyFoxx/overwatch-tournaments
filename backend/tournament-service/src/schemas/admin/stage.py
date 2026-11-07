from typing import Literal

from pydantic import BaseModel, Field, model_validator

from shared.core.enums import StageItemInputType, StageItemType, StagePairingMode, StageType
from src.schemas.stage import GrandFinalType, SeedRankingValue, StageBestOf, StageScoring

__all__ = (
    "StageCreate",
    "StageUpdate",
    "StageItemCreate",
    "StageItemUpdate",
    "StageItemInputCreate",
    "StageItemInputUpdate",
    "MergeGroupStagesRequest",
    "SeedTeamsRequest",
)

#: Same ceiling as a mix's ``points_per_win``.
MAX_RANK_DELTA = 1000


class StageCreate(BaseModel):
    name: str
    description: str | None = None
    stage_type: StageType
    max_rounds: int = Field(default=5, ge=1)
    order: int = 0
    ranking_preset: str | None = None
    tiebreak_order: list[str] | None = None
    scoring: StageScoring = Field(default_factory=StageScoring)
    swiss_bye_points: float | None = None
    swiss_qualify_wins: int | None = Field(default=None, ge=1)
    swiss_eliminate_losses: int | None = Field(default=None, ge=1)
    de_grand_final_type: GrandFinalType = "no_reset"
    seed_ranking: SeedRankingValue = "slot"
    pairing_mode: StagePairingMode | None = None
    playoff_team_count: int | None = Field(default=None, ge=1)
    rank_win_delta: int | None = Field(default=None, ge=0, le=MAX_RANK_DELTA)
    rank_loss_delta: int | None = Field(default=None, ge=0, le=MAX_RANK_DELTA)
    best_of: StageBestOf = Field(default_factory=StageBestOf)
    challonge_id: int | None = None
    challonge_slug: str | None = None


class StageUpdate(BaseModel):
    """A partial edit: only the fields sent change (the service reads
    ``exclude_unset``). ``scoring`` and ``best_of`` are each replaced as a
    whole. The non-nullable regulation fields carry a default only
    so that an explicit ``null`` is refused instead of written."""

    name: str | None = None
    description: str | None = None
    stage_type: StageType | None = None
    max_rounds: int | None = Field(default=None, ge=1)
    order: int | None = None
    ranking_preset: str | None = None
    tiebreak_order: list[str] | None = None
    scoring: StageScoring = Field(default_factory=StageScoring)
    swiss_bye_points: float | None = None
    swiss_qualify_wins: int | None = Field(default=None, ge=1)
    swiss_eliminate_losses: int | None = Field(default=None, ge=1)
    de_grand_final_type: GrandFinalType = "no_reset"
    seed_ranking: SeedRankingValue = "slot"
    pairing_mode: StagePairingMode | None = None
    playoff_team_count: int | None = Field(default=None, ge=1)
    rank_win_delta: int | None = Field(default=None, ge=0, le=MAX_RANK_DELTA)
    rank_loss_delta: int | None = Field(default=None, ge=0, le=MAX_RANK_DELTA)
    best_of: StageBestOf = Field(default_factory=StageBestOf)


class StageItemCreate(BaseModel):
    name: str
    type: StageItemType
    order: int = 0


class StageItemUpdate(BaseModel):
    name: str | None = None
    type: StageItemType | None = None
    order: int | None = None


class StageItemInputCreate(BaseModel):
    slot: int = Field(ge=1)
    input_type: StageItemInputType = StageItemInputType.EMPTY
    team_id: int | None = None

    @model_validator(mode="after")
    def _validate_input_shape(self) -> StageItemInputCreate:
        if self.input_type == StageItemInputType.FINAL and self.team_id is None:
            raise ValueError("FINAL inputs require team_id")
        if self.input_type == StageItemInputType.EMPTY and self.team_id is not None:
            raise ValueError("EMPTY inputs must not have team_id")
        return self


class StageItemInputUpdate(BaseModel):
    input_type: StageItemInputType | None = None
    team_id: int | None = None
    #: Moves the input into this item of the same stage; None = stays in its own.
    stage_item_id: int | None = None
    #: Seed to re-seat the input at. The inputs it passes shift by one, so every
    #: item keeps slots 1..N; past the end (or omitted with ``stage_item_id``) appends.
    slot: int | None = Field(default=None, ge=1)


class MergeGroupStagesRequest(BaseModel):
    """Merge one-group stages into one grouped stage.

    ``source_stage_ids`` are removed after their stage_items and stage-scoped
    references are moved under the target stage named by the path.
    """

    source_stage_ids: list[int] = Field(min_length=1)
    target_name: str | None = None


class SeedTeamsRequest(BaseModel):
    """Distribute teams into a stage's stage_items (groups) automatically.

    ``mode`` selects the distribution strategy:
    - ``snake_sr`` (default) — sort by Team.avg_sr desc, snake-distribute
      across groups so each group ends up roughly equally strong.
    - ``by_total_sr`` — same but sorts by Team.total_sr (raw sum).
    - ``random`` — deterministic shuffle based on team.id (reproducible).
    - ``captain_rank`` — sort by the captain's rank desc (the draft playoff: strongest captain is seed 1).
    """

    team_ids: list[int]
    mode: Literal["snake_sr", "by_total_sr", "random", "captain_rank"] = "snake_sr"
