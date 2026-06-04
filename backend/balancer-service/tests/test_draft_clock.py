from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.services.distributed_lock import (  # noqa: E402
    DistributedLockToken,
    renew_distributed_lock,
)
from src.services.draft import clock as draft_clock  # noqa: E402


def test_compute_sleep_none_expiry_is_renew_interval() -> None:
    assert draft_clock.compute_sleep_seconds(None, datetime.now(UTC)) == float(draft_clock.RENEW_INTERVAL_SECONDS)


def test_compute_sleep_future_expiry_positive() -> None:
    now = datetime.now(UTC)
    s = draft_clock.compute_sleep_seconds(now + timedelta(seconds=30), now)
    assert 29.0 < s <= 30.0


def test_compute_sleep_past_expiry_is_zero() -> None:
    now = datetime.now(UTC)
    assert draft_clock.compute_sleep_seconds(now - timedelta(seconds=5), now) == 0.0


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self.store = store

    async def eval(self, script, numkeys, key, value, *args):  # noqa: ANN001, ANN002
        # Mirror the compare-and-pexpire Lua: act only if token matches.
        return 1 if self.store.get(key) == value else 0


def test_renew_succeeds_when_token_matches() -> None:
    redis = _FakeRedis({"draft:1:clock_owner": "tok"})
    token = DistributedLockToken(key="draft:1:clock_owner", value="tok")
    assert asyncio.run(renew_distributed_lock(redis, token, ttl_seconds=10)) is True


def test_renew_fails_when_token_lost() -> None:
    redis = _FakeRedis({"draft:1:clock_owner": "someone-else"})
    token = DistributedLockToken(key="draft:1:clock_owner", value="tok")
    assert asyncio.run(renew_distributed_lock(redis, token, ttl_seconds=10)) is False


def test_control_channel_and_lock_key() -> None:
    assert draft_clock.control_channel(7) == "draft:7:control"
    assert draft_clock.lock_key(7) == "draft:7:clock_owner"
