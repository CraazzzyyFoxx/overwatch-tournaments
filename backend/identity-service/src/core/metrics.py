"""Identity-specific Prometheus metrics, served by the shared worker metrics server.

Process-global like ``shared.observability.worker``'s: the default registry is
what ``start_worker_metrics_server`` exposes on ``WORKER_METRICS_PORT``.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

__all__ = (
    "LOGIN_TOTAL",
    "PASSWORD_HASH_SECONDS",
    "RBAC_CACHE_TOTAL",
    "REDIS_DEGRADED_TOTAL",
    "REFRESH_TOTAL",
)

# result: hit (whole payload from Redis) | miss (any component loaded from the database)
RBAC_CACHE_TOTAL = Counter(
    "identity_rbac_cache_total",
    "RBAC cache lookups on the token-validation path.",
    ("result",),
)
# result: success | invalid | locked | inactive
LOGIN_TOTAL = Counter(
    "identity_login_total",
    "Password login attempts by outcome.",
    ("result",),
)
# result: rotated | idempotent | grace | concurrent | reuse | invalid
REFRESH_TOTAL = Counter(
    "identity_refresh_total",
    "Refresh-token rotations by outcome.",
    ("result",),
)
# store: the RedisStore purpose; action: read | write | redeem | claim | invalidation
REDIS_DEGRADED_TOTAL = Counter(
    "identity_redis_degraded_total",
    "Redis operations that fell back because Redis was unavailable.",
    ("store", "action"),
)
# op: hash | verify
PASSWORD_HASH_SECONDS = Histogram(
    "identity_password_hash_seconds",
    "Wall time of bcrypt operations, including the wait for a hashing slot.",
    ("op",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
