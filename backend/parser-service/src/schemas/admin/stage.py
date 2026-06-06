from typing import Literal

from pydantic import BaseModel, Field, model_validator
from shared.core.enums import StageItemInputType, StageItemType, StageType

__all__ = (
    "StageCreate",
    "StageUpdate",
    "StageItemCreate",
    "StageItemUpdate",
    "StageItemInputCreate",
    "StageItemInputUpdate",
    "MergeGroupStagesRequest",
    "WireFromGroupsRequest",
    "SeedTeamsRequest",
)


class StageCreate(BaseModel):
    name: str
    description: str | None = None
    stage_type: StageType
    max_rounds: int = Field(default=5, ge=1)
    advance_count: int | None = Field(default=None, ge=1)
    order: int = 0
    settings_json: dict | None = None
    challonge_id: int | None = None
    challonge_slug: str | None = None


class StageUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    stage_type: StageType | None = None
    max_rounds: int | None = Field(default=None, ge=1)
    advance_count: int | None = Field(default=None, ge=1)
    order: int | None = None
    settings_json: dict | None = None


class StageItemCreate(BaseModel):
    name: str
    type: StageItemType
    order: int = 0


class StageItemUpdate(BaseModel):
    name: str | None = None
    type: StageItemType | None = None
    order: int | None = None


class StageItemInputCreate(BaseModel):
    slot: int
    input_type: StageItemInputType = StageItemInputType.EMPTY
    team_id: int | None = None
    source_stage_item_id: int | None = None
    source_position: int | None = None

    @model_validator(mode="after")
    def _validate_input_shape(self) -> "StageItemInputCreate":
        if self.input_type == StageItemInputType.FINAL and self.team_id is None:
            raise ValueError("FINAL inputs require team_id")
        if self.input_type == StageItemInputType.TENTATIVE:
            if self.source_stage_item_id is None or self.source_position is None:
                raise ValueError(
                    "TENTATIVE inputs require source_stage_item_id and source_position"
                )
            if self.team_id is not None:
                raise ValueError(
                    "TENTATIVE inputs must not have team_id (it is resolved on activation)"
                )
            if self.source_position < 1:
                raise ValueError("source_position is 1-based (>= 1)")
        return self


class StageItemInputUpdate(BaseModel):
    input_type: StageItemInputType | None = None
    team_id: int | None = None
    source_stage_item_id: int | None = None
    source_position: int | None = Field(default=None, ge=1)


class MergeGroupStagesRequest(BaseModel):
    """Merge legacy one-group stages into one grouped stage.

    ``source_stage_ids`` are removed after their stage_items and stage-scoped
    references are moved under the target stage from the route path.
    """

    source_stage_ids: list[int] = Field(min_length=1)
    target_name: str | None = None


class WireFromGroupsRequest(BaseModel):
    """Auto-wire TENTATIVE inputs in a playoff stage from a group stage.

    ``top`` = number of teams per group going to the upper bracket (UB).
    ``top_lb`` = number of teams per group going to the lower bracket (LB).
    When ``top_lb=0`` (default) all teams go into the UB item only.

    Total UB slots = num_groups * top; total LB slots = num_groups * top_lb.
    LB positions start from ``top + 1`` in each group's standings.

    ``mode`` = seeding pattern. "cross" avoids same-group rematches in R1
    by alternating direction per column; "snake" does plain top-down.
    """

    source_stage_id: int
    top: int = 2
    top_lb: int = 0
    mode: Literal["cross", "snake"] = "cross"


class SeedTeamsRequest(BaseModel):
    """Distribute teams into a stage's stage_items (groups) automatically.

    ``mode`` selects the distribution strategy:
    - ``snake_sr`` (default) — sort by Team.avg_sr desc, snake-distribute
      across groups so each group ends up roughly equally strong.
    - ``by_total_sr`` — same but sorts by Team.total_sr (raw sum).
    - ``random`` — deterministic shuffle based on team.id (reproducible).
    """

    team_ids: list[int]
    mode: Literal["snake_sr", "by_total_sr", "random"] = "snake_sr"
