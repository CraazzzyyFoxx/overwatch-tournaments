from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = (
    "CollectionStatusRead",
    "CollectTriggerRequest",
    "CollectTriggerResponse",
    "ReenableDisabledRequest",
    "ReenableDisabledResponse",
    "FetchLogRead",
)


class CollectionStatusRead(BaseModel):
    social_account_id: int
    battle_tag: str
    status: str | None = None
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    next_eligible_at: datetime | None = None
    priority_tier: int = 0


class CollectTriggerRequest(BaseModel):
    user_id: int | None = None
    social_account_ids: list[int] | None = None


class CollectTriggerResponse(BaseModel):
    enqueued: int


class ReenableDisabledRequest(BaseModel):
    # Limit to tags that ever produced a snapshot (skip genuinely-dead handles).
    only_previously_succeeded: bool = False


class ReenableDisabledResponse(BaseModel):
    reenabled: int


class FetchLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    social_account_id: int | None
    battle_tag: str
    status: str
    source: str
    error: str | None
    snapshots_written: int
    created_at: datetime
