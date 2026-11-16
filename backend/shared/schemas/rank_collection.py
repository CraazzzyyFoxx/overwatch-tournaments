"""Request/response models of the rank domain: public history and ladder reads and the admin collection RPCs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = (
    "CareerAccount",
    "CareerCharacter",
    "CareerProfile",
    "CareerQueue",
    "CareerResponse",
    "CareerRole",
    "CareerSignal",
    "CareerSignalsResponse",
    "CareerUserSignals",
    "CollectTriggerRequest",
    "CollectTriggerResponse",
    "CollectionStatusRead",
    "CurrentRank",
    "CurrentRanksResponse",
    "FetchLogRead",
    "RankCollectionStats",
    "RankHistoryPoint",
    "RankHistoryResponse",
    "RankSeries",
    "RankStatusCounts",
    "ReenableDisabledRequest",
    "ReenableDisabledResponse",
)


class CareerCharacter(BaseModel):
    """One character in one queue: time, games and per-10-minute rates from the game's own career."""

    character: str
    role: str | None
    seconds: float
    share: float
    """Of the queue's time."""
    games_played: int | None = None
    games_won: int | None = None
    winrate: float | None = None
    rates: dict[str, float] = {}
    """Per 10 minutes of this character, keyed by the game's stat key."""


class CareerRole(BaseModel):
    role: str
    seconds: float
    share: float
    pool_size: float
    """Effective number of characters played (exp of the entropy of their time shares): 1 is a one-trick."""
    mains: list[str]
    """The most played characters, in order, covering 80% of the role's time."""


class CareerQueue(BaseModel):
    """One platform and queue of an account as the game shows it now; a seasonal queue covers its current season."""

    platform: str | None
    queue: str | None
    season: int | None
    seconds: float
    games_played: int | None
    games_won: int | None
    games_lost: int | None
    winrate: float | None
    rates: dict[str, float]
    roles: list[CareerRole]
    characters: list[CareerCharacter]
    captured_at: datetime
    """When the newest of these figures was collected."""


class CareerProfile(BaseModel):
    display_name: str | None
    avatar_url: str | None
    attrs: dict[str, Any]
    is_public: bool
    """Whether the last poll saw the career; a closed profile shows only its name and avatar."""
    upstream_updated_at: datetime | None
    """The game's own "profile last changed" moment: roughly the last game played."""
    fetched_at: datetime


class CareerAccount(BaseModel):
    """One linked game account. ``queues`` is empty while its profile is closed."""

    social_account_id: int
    handle: str
    is_primary: bool
    status: str | None
    """Collection status of the account (``ok``, ``private``, ``not_found``, ...); ``None`` = never collected."""
    last_success_at: datetime | None
    profile: CareerProfile | None
    queues: list[CareerQueue]


class CareerResponse(BaseModel):
    user_id: int
    accounts: list[CareerAccount]
    generated_at: datetime


class CareerSignal(BaseModel):
    code: str
    """``profile_not_found``, ``previously_found``, ``profile_private``, ``never_collected``, ``renamed``,
    ``low_hours_high_rank`` (``value`` = hours) or ``inactive``."""
    social_account_id: int | None = None
    """The account it is about; ``None`` for the player as a whole."""
    value: float | None = None


class CareerUserSignals(BaseModel):
    user_id: int
    competitive_role_shares: dict[str, float]
    """Each role's share of the player's current-season competitive time, across their accounts."""
    hours: float
    last_played_at: datetime | None
    """The newest "profile last changed" moment among the player's accounts."""
    signals: list[CareerSignal]


class CareerSignalsResponse(BaseModel):
    users: list[CareerUserSignals]
    generated_at: datetime


class RankHistoryPoint(BaseModel):
    captured_at: datetime
    rank_value: int | None
    division: str | None
    tier: int | None
    is_ranked: bool
    season: int | None
    #: League of Legends only (league points, season wins/losses); null for other games.
    lp: int | None = None
    wins: int | None = None
    losses: int | None = None


class RankSeries(BaseModel):
    """One time series of one game account: per (role, platform) for Overwatch, per ``queue`` for League."""

    social_account_id: int
    handle: str
    role: str | None
    platform: str | None
    queue: str | None = None
    points: list[RankHistoryPoint]
    current: RankHistoryPoint | None
    peak_rank_value: int | None
    latest_captured_at: datetime | None


class RankHistoryResponse(BaseModel):
    user_id: int | None
    series: list[RankSeries]
    generated_at: datetime


class CurrentRank(BaseModel):
    social_account_id: int
    handle: str
    role: str | None
    platform: str | None
    queue: str | None = None
    rank_value: int | None
    division: str | None
    tier: int | None
    is_ranked: bool
    season: int | None
    lp: int | None = None
    wins: int | None = None
    losses: int | None = None
    captured_at: datetime


class CurrentRanksResponse(BaseModel):
    user_id: int | None
    ranks: list[CurrentRank]
    generated_at: datetime


class CollectionStatusRead(BaseModel):
    social_account_id: int
    handle: str
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
    upstream_base_url: str = ""
    """The upstream the worker fetches from (OverFast instance, Riot API cluster) — named on the dashboard so an outage
    points at a host instead of at "the collector"."""
    upstream_circuit_state: str = "closed"
    """``closed`` / ``half_open`` / ``open``. Open = every fetch is refused before it leaves the process."""
    invalid_handles_24h: int = 0
    """Fetches rejected because the stored handle is malformed for its game."""


class FetchLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    social_account_id: int | None
    # Owning player (resolved via the social account) so a log row is clickable
    # through to the player detail view; null when the account was deleted.
    user_id: int | None = None
    handle: str
    status: str
    source: str
    error: str | None
    snapshots_written: int
    created_at: datetime
