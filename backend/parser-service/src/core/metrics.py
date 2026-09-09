from __future__ import annotations

from prometheus_client import Gauge

RANK_COLLECTION_LAST_SUCCESS_TIMESTAMP = Gauge(
    "rank_collection_last_success_timestamp_seconds",
    "Unix timestamp of the newest successful OverFast rank capture across all battle tags. "
    "0 means nothing has ever succeeded.",
)

RANK_COLLECTION_ENABLED = Gauge(
    "rank_collection_enabled",
    "Whether OverFast rank collection is switched on in admin settings (1) or paused (0). "
    "Staleness alerts gate on this so a deliberate pause does not page anyone.",
)
