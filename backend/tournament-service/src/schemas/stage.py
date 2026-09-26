from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.domain.ffa_scoring import FFA_MAX_LOBBY_SIZE
from src.core import enums
from src.schemas.base import BaseRead

__all__ = (
    "StageRead",
    "StageSummaryRead",
    "StageItemRead",
    "StageItemSummaryRead",
    "StageItemInputRead",
    "StageScoring",
    "StageBestOf",
    "FfaScoring",
    "GrandFinalType",
    "SeedRankingValue",
)

GrandFinalType = Literal["no_reset", "with_reset"]
SeedRankingValue = Literal["slot", "avg_sr", "total_sr", "random"]


class StageScoring(BaseModel):
    """Points per result on this stage. ``None`` = the tournament's points."""

    model_config = ConfigDict(extra="forbid")

    win: float | None = None
    draw: float | None = None
    loss: float | None = None


class StageBestOf(BaseModel):
    """Series length per encounter: ``final`` (an elimination stage's last round),
    else the round's own ``by_round`` entry, else ``default``."""

    model_config = ConfigDict(extra="forbid")

    default: int = Field(default=3, ge=1)
    #: Round number (negative in a lower bracket) -> best-of.
    by_round: dict[int, int] = Field(default_factory=dict)
    final: int | None = Field(default=None, ge=1)

    @field_validator("by_round")
    @classmethod
    def _positive(cls, value: dict[int, int]) -> dict[int, int]:
        if any(best_of < 1 for best_of in value.values()):
            raise ValueError("a round's best-of must be at least 1")
        return value


class FfaScoring(BaseModel):
    """What an ffa_league stage pays for (plan §4.2); inert on any other type."""

    model_config = ConfigDict(extra="forbid")

    placement_points: list[float] = Field(default_factory=list, max_length=FFA_MAX_LOBBY_SIZE)
    score_points: float = Field(default=1.0, ge=0)
    #: The organizer's word for the score column ("Kills", "Убийства"): each game
    #: has its own, so it is data, not a translation key.
    score_label: str | None = Field(default=None, max_length=32)

    @field_validator("placement_points")
    @classmethod
    def _non_negative(cls, value: list[float]) -> list[float]:
        if any(points < 0 for points in value):
            raise ValueError("placement points cannot be negative")
        return value


class _StageRegulationRead(BaseModel):
    """The regulation every stage read carries (``Stage`` columns and properties)."""

    #: ``None`` = the preset chosen by ``stage_type``.
    ranking_preset: str | None = None
    #: ``None`` = the preset's order.
    tiebreak_order: list[str] | None = None
    scoring: StageScoring = Field(default_factory=StageScoring)
    #: ``None`` = a bye pays the win points.
    swiss_bye_points: float | None = None
    de_grand_final_type: GrandFinalType = "no_reset"
    seed_ranking: SeedRankingValue = "slot"
    best_of: StageBestOf = Field(default_factory=StageBestOf)
    ffa_scoring: FfaScoring = Field(default_factory=FfaScoring)


class StageItemInputRead(BaseRead):
    stage_item_id: int
    slot: int
    input_type: enums.StageItemInputType
    team_id: int | None
    source_stage_item_id: int | None
    source_position: int | None


class StageItemRead(BaseRead):
    stage_id: int
    name: str
    type: enums.StageItemType
    order: int
    advance_count: int | None = None
    inputs: list[StageItemInputRead] = []


class StageItemSummaryRead(BaseRead):
    stage_id: int
    name: str
    type: enums.StageItemType
    order: int
    advance_count: int | None = None


class StageSummaryRead(BaseRead, _StageRegulationRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: enums.StageType
    max_rounds: int = 5
    advance_count: int | None = None
    split_lower_bracket: bool = False
    order: int
    is_active: bool
    is_published: bool = False
    is_completed: bool
    challonge_id: int | None = None
    challonge_slug: str | None = None


class StageRead(BaseRead, _StageRegulationRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: enums.StageType
    max_rounds: int = 5
    advance_count: int | None = None
    split_lower_bracket: bool = False
    order: int
    is_active: bool
    is_published: bool = False
    is_completed: bool
    challonge_id: int | None = None
    challonge_slug: str | None = None
    items: list[StageItemRead] = []
