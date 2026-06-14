from shared.core.enums import StageItemInputType, StageItemType, StageType
from src.schemas.base import BaseRead

__all__ = ("StageRead", "StageItemRead", "StageItemInputRead")


class StageItemInputRead(BaseRead):
    stage_item_id: int
    slot: int
    input_type: StageItemInputType
    team_id: int | None
    source_stage_item_id: int | None
    source_position: int | None


class StageItemRead(BaseRead):
    stage_id: int
    name: str
    type: StageItemType
    order: int
    inputs: list[StageItemInputRead] = []


class StageRead(BaseRead):
    tournament_id: int
    name: str
    description: str | None
    stage_type: StageType
    max_rounds: int
    advance_count: int | None = None
    split_lower_bracket: bool = False
    order: int
    is_active: bool
    is_completed: bool
    settings_json: dict | None
    challonge_id: int | None
    challonge_slug: str | None
    items: list[StageItemRead] = []
