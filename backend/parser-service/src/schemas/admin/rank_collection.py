from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = (
    "CollectionStatusRead",
    "CollectTriggerRequest",
    "CollectTriggerResponse",
    "ReenableDisabledRequest",
    "ReenableDisabledResponse",
    "RankStatusCounts",
    "RankCollectionStats",
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


class RankStatusCounts(BaseModel):
    """Count per RankCollectionStatus. Statuses absent in a source read stay 0.

    ``extra="ignore"`` so an unexpected status string can never break the read.
    """

    model_config = ConfigDict(extra="ignore")

    ok: int = 0
    pending: int = 0
    not_found: int = 0
    private: int = 0
    error: int = 0
    rate_limited: int = 0
    disabled: int = 0


class RankCollectionStats(BaseModel):
    """Aggregated collection health for the admin dashboard."""

    total: int
    never_checked: int
    by_status: RankStatusCounts
    tier0: int
    tier1: int
    tier2: int
    coverage_24h: int
    coverage_7d: int
    last_success_at: datetime | None
    fetch_24h: RankStatusCounts
    fetch_24h_total: int
    error_rate_24h: float
    enabled: bool
    scope: str
    interval_seconds: int
    rate_limit_per_minute: int


class FetchLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    social_account_id: int | None
    # Owning player (resolved via the social account) so a log row is clickable
    # through to the player detail view; null when the account was deleted.
    user_id: int | None = None
    battle_tag: str
    status: str
    source: str
    error: str | None
    snapshots_written: int
    created_at: datetime
