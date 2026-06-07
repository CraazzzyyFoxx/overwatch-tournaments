from src.core import enums
from src.schemas.base import BaseRead

__all__ = (
    "StageRead",
    "StageSummaryRead",
    "StageItemRead",
    "StageItemSummaryRead",
    "StageItemInputRead",
)


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
    inputs: list[StageItemInputRead] = []


class StageItemSummaryRead(BaseRead):
    stage_id: int
    name: str
    type: enums.StageItemType
    order: int


class StageSummaryRead(BaseRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: enums.StageType
    max_rounds: int = 5
    advance_count: int | None = None
    split_lower_bracket: bool = False
    order: int
    is_active: bool
    is_completed: bool
    settings_json: dict | None = None
    challonge_id: int | None = None
    challonge_slug: str | None = None


class StageRead(BaseRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: enums.StageType
    max_rounds: int = 5
    advance_count: int | None = None
    split_lower_bracket: bool = False
    order: int
    is_active: bool
    is_completed: bool
    settings_json: dict | None = None
    challonge_id: int | None = None
    challonge_slug: str | None = None
    items: list[StageItemRead] = []
