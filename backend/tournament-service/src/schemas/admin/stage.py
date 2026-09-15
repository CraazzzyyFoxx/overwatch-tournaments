from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from shared.core.enums import StageItemInputType, StageItemType, StageType

__all__ = (
    "StageCreate",
    "StageUpdate",
    "StageSettings",
    "StageItemCreate",
    "StageItemUpdate",
    "StageItemInputCreate",
    "StageItemInputUpdate",
    "MergeGroupStagesRequest",
    "WireFromGroupsRequest",
    "SeedTeamsRequest",
)


class StageScoring(BaseModel):
    """Points per result. Numeric because the standings adder is."""

    model_config = ConfigDict(extra="allow")

    win: float = 3
    draw: float = 1
    loss: float = 0


class StageSettings(BaseModel):
    """The known keys of ``Stage.settings_json``.

    Validated, not exhaustive: ``extra="allow"`` keeps best-of config, Challonge
    hints and the Swiss bookkeeping the engine writes back (``swiss_byes``,
    ``swiss_stopped_scopes``) passing through untouched. The point is that the
    keys the regulation actually runs on cannot arrive in a shape that only
    explodes later, mid-tournament, inside the points adder.
    """

    model_config = ConfigDict(extra="allow")

    scoring: StageScoring | None = None
    de_grand_final_type: Literal["single", "with_reset"] | None = None
    tiebreak_order: list[str] | None = None


def _validate_settings_json(value: dict | None) -> dict | None:
    """Check the known regulation keys; store the blob verbatim.

    Parsing into ``StageSettings`` and dumping it back would rewrite the blob --
    inventing defaults for keys the stage never set and dropping ``None``s the
    readers distinguish from absent. So the model is used as a validator and the
    caller's dict is what gets stored.
    """
    if value is not None:
        StageSettings.model_validate(value)
    return value


SettingsJson = Annotated[dict | None, AfterValidator(_validate_settings_json)]


class StageCreate(BaseModel):
    name: str
    description: str | None = None
    stage_type: StageType
    max_rounds: int = Field(default=5, ge=1)
    advance_count: int | None = Field(default=None, ge=1)
    split_lower_bracket: bool = False
    order: int = 0
    settings_json: SettingsJson = None
    challonge_id: int | None = None
    challonge_slug: str | None = None


class StageUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    stage_type: StageType | None = None
    max_rounds: int | None = Field(default=None, ge=1)
    advance_count: int | None = Field(default=None, ge=1)
    split_lower_bracket: bool | None = None
    order: int | None = None
    settings_json: SettingsJson = None


class StageItemCreate(BaseModel):
    name: str
    type: StageItemType
    order: int = 0
    #: Overrides ``Stage.advance_count`` for this group only; None = inherit.
    advance_count: int | None = Field(default=None, ge=1)


class StageItemUpdate(BaseModel):
    name: str | None = None
    type: StageItemType | None = None
    order: int | None = None
    advance_count: int | None = Field(default=None, ge=1)


class StageItemInputCreate(BaseModel):
    slot: int = Field(ge=1)
    input_type: StageItemInputType = StageItemInputType.EMPTY
    team_id: int | None = None
    source_stage_item_id: int | None = None
    source_position: int | None = None

    @model_validator(mode="after")
    def _validate_input_shape(self) -> StageItemInputCreate:
        if self.input_type == StageItemInputType.FINAL and self.team_id is None:
            raise ValueError("FINAL inputs require team_id")
        if self.input_type == StageItemInputType.EMPTY and self.team_id is not None:
            raise ValueError("EMPTY inputs must not have team_id")
        if self.input_type == StageItemInputType.TENTATIVE:
            if self.source_stage_item_id is None or self.source_position is None:
                raise ValueError("TENTATIVE inputs require source_stage_item_id and source_position")
            if self.team_id is not None:
                raise ValueError("TENTATIVE inputs must not have team_id (it is resolved on activation)")
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
