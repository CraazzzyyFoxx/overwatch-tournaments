import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from shared.domain.ffa_formula import FORMULA_MAX_LENGTH, RESERVED_NAMES, FfaFormulaError, compile_formula
from shared.domain.ffa_scoring import (
    DEFAULT_COLUMN_KEY,
    DEFAULT_COLUMN_LABEL,
    DEFAULT_FORMULA,
    FFA_MAX_COLUMNS,
    FFA_MAX_LOBBY_SIZE,
)
from shared.services.bracket.template import BracketTemplate
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
    "FfaColumnSettings",
    "FfaScoring",
    "GrandFinalType",
    "SeedRankingValue",
    "BracketSeedCounts",
    "BracketTemplateRead",
)

GrandFinalType = Literal["no_reset", "with_reset"]
SeedRankingValue = Literal["slot", "avg_sr", "total_sr", "random"]


class BracketSeedCounts(BaseModel):
    """How many teams start in each half of a bracket stage."""

    upper: int
    lower: int


class BracketTemplateRead(BaseModel):
    """A stage's bracket layout: its custom template, or the one its format generates now.

    ``template`` is ``None`` only when fewer than two upper seeds are known, so
    there is nothing to draw yet.
    """

    custom: bool
    template: BracketTemplate | None = None
    seeds: BracketSeedCounts


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


#: A column key is a formula identifier, so it is spelled like one and short
#: enough to type: a lowercase letter, then letters, digits or underscores.
COLUMN_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,23}")


class FfaColumnSettings(BaseModel):
    """One value an ffa_league stage records per team per game."""

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The organizer's word for it ("Kills", "Убийства"): each stage has its
    #: own, so it is data, not a translation key.
    label: str = Field(min_length=1, max_length=32)
    #: False = viewers see neither the column nor its values (plan §2).
    public: bool = True
    better: Literal["higher", "lower"] = "higher"

    @field_validator("label", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("key")
    @classmethod
    def _usable_key(cls, value: str) -> str:
        if not COLUMN_KEY_PATTERN.fullmatch(value):
            raise PydanticCustomError(
                "ffa_column_key_invalid",
                "A column key is up to 24 characters: a lowercase letter, then letters, digits or _",
                {"name": value},
            )
        if value in RESERVED_NAMES:
            raise PydanticCustomError(
                "ffa_column_key_reserved", "`{name}` is a word the formula language owns", {"name": value}
            )
        return value


class FfaScoring(BaseModel):
    """What an ffa_league stage records and what it pays for it (plan §3.1).

    Inert on any other stage type. The unset block is the behaviour a stage had
    before columns existed: one raw score column paid one for one.
    """

    model_config = ConfigDict(extra="forbid")

    columns: list[FfaColumnSettings] = Field(default_factory=lambda: [_default_column()])
    #: Points for 1st, 2nd, ... place, read by the formula as ``place_pts``.
    placement_points: list[float] = Field(default_factory=list, max_length=FFA_MAX_LOBBY_SIZE)
    formula: str = Field(default=DEFAULT_FORMULA, min_length=1, max_length=FORMULA_MAX_LENGTH)

    @field_validator("placement_points")
    @classmethod
    def _non_negative(cls, value: list[float]) -> list[float]:
        if any(points < 0 for points in value):
            raise ValueError("placement points cannot be negative")
        return value

    @field_validator("columns")
    @classmethod
    def _distinct(cls, value: list[FfaColumnSettings]) -> list[FfaColumnSettings]:
        if len(value) > FFA_MAX_COLUMNS:
            raise PydanticCustomError(
                "ffa_columns_too_many", "A stage has at most {limit} columns", {"limit": FFA_MAX_COLUMNS}
            )
        seen: set[str] = set()
        for column in value:
            if column.key in seen:
                raise PydanticCustomError("ffa_column_duplicate", "`{name}` is listed twice", {"name": column.key})
            seen.add(column.key)
        return value

    @model_validator(mode="after")
    def _formula_compiles(self) -> FfaScoring:
        """Columns and formula are one rule: neither is valid without the other.

        The error the parser raises is re-raised with its own code and its
        position in ``ctx``, so the editor can underline the character instead
        of showing "invalid".
        """
        try:
            compile_formula(self.formula, [column.key for column in self.columns])
        except FfaFormulaError as exc:
            raise PydanticCustomError(exc.code, str(exc), {"offset": exc.offset, "name": exc.name}) from exc
        return self


def _default_column() -> FfaColumnSettings:
    return FfaColumnSettings(key=DEFAULT_COLUMN_KEY, label=DEFAULT_COLUMN_LABEL)


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
    advance_upper_count: int | None = None
    inputs: list[StageItemInputRead] = []


class StageItemSummaryRead(BaseRead):
    stage_id: int
    name: str
    type: enums.StageItemType
    order: int
    advance_count: int | None = None
    advance_upper_count: int | None = None


class StageSummaryRead(BaseRead, _StageRegulationRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: enums.StageType
    max_rounds: int = 5
    advance_count: int | None = None
    advance_upper_count: int | None = None
    order: int
    is_active: bool
    is_published: bool = False
    is_completed: bool
    challonge_id: int | None = None
    challonge_slug: str | None = None
    has_custom_bracket: bool = False


class StageRead(BaseRead, _StageRegulationRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: enums.StageType
    max_rounds: int = 5
    advance_count: int | None = None
    advance_upper_count: int | None = None
    order: int
    is_active: bool
    is_published: bool = False
    is_completed: bool
    challonge_id: int | None = None
    challonge_slug: str | None = None
    has_custom_bracket: bool = False
    items: list[StageItemRead] = []
