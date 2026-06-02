"""DTOs for OverFast rank fetching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.core import enums


@dataclass(frozen=True)
class ParsedRank:
    """One competitive rank entry parsed from an OverFast summary."""

    platform: str  # enums.RankPlatform
    role: str  # enums.RankRole
    division: str | None
    tier: int | None
    season: int | None
    is_ranked: bool
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class RankFetchResult:
    """Outcome of fetching one battle tag's summary from OverFast.

    Expected, non-exceptional states (``not_found``/``private``) are returned
    rather than raised. Rate limiting and transport/5xx failures are raised
    (``OverFastRateLimited`` / ``OverFastError``) so the worker can back off and
    let RabbitMQ retry.
    """

    status: enums.RankCollectionStatus
    ranks: list[ParsedRank] = field(default_factory=list)
    error: str | None = None
