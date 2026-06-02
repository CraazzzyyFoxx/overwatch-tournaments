from datetime import datetime

from pydantic import BaseModel

__all__ = ("CollectionStatusRead", "CollectTriggerRequest", "CollectTriggerResponse")


class CollectionStatusRead(BaseModel):
    battle_tag_id: int
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
    battle_tag_ids: list[int] | None = None


class CollectTriggerResponse(BaseModel):
    enqueued: int
