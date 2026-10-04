"""Cross-replica single flight for draft reads (2026-09-30 follow-up).

Each "replica" here is an independent call into ``board._compute_once`` -- the
layer below the per-process in-flight map -- sharing one cache backend, which
is exactly what two balancer processes sharing one Redis do.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from cashews import cache  # noqa: E402

from src.services.draft import board  # noqa: E402

_TTL = "15s"


async def _two_replicas(key: str, compute, *, lead_in: float = 0.25) -> list[object]:
    """Start a leader, let the second replica reach its poll loop, then let compute finish."""
    gate = asyncio.Event()

    async def replica(label: str):
        return await board._compute_once(key, lambda: compute(label, gate), _TTL)

    leader = asyncio.create_task(replica("leader"))
    await asyncio.sleep(0.01)  # the leader takes the lock first
    follower = asyncio.create_task(replica("follower"))
    await asyncio.sleep(lead_in)  # the follower is now polling for the leader's answer
    gate.set()
    return await asyncio.gather(leader, follower, return_exceptions=True)


def test_one_replica_computes_a_board_state_and_the_other_reuses_its_answer() -> None:
    runs: list[str] = []

    async def compute(label: str, gate: asyncio.Event) -> str:
        runs.append(label)
        await gate.wait()
        return label

    results = asyncio.run(_two_replicas("backend:balancer:draft_read:test:shared", compute))

    assert runs == ["leader"], "the second replica must not rebuild the same board state"
    assert results == ["leader", "leader"]


def test_a_failed_leader_never_fails_the_other_replica() -> None:
    runs: list[str] = []

    async def compute(label: str, gate: asyncio.Event) -> str:
        runs.append(label)
        await gate.wait()
        if label == "leader":
            raise RuntimeError("leader broke")
        return label

    results = asyncio.run(_two_replicas("backend:balancer:draft_read:test:leader-dies", compute))

    assert isinstance(results[0], RuntimeError)
    assert results[1] == "follower"
    assert runs == ["leader", "follower"]


def test_an_unreachable_redis_degrades_to_everyone_computing(monkeypatch) -> None:
    runs: list[str] = []

    async def compute(label: str, gate: asyncio.Event) -> str:
        runs.append(label)
        await gate.wait()
        return label

    async def broken(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cache, "set_lock", broken)
    monkeypatch.setattr(cache, "get", broken)
    monkeypatch.setattr(cache, "set", broken)

    results = asyncio.run(_two_replicas("backend:balancer:draft_read:test:no-redis", compute, lead_in=0.01))

    assert results == ["leader", "follower"], "a cache outage must not fail a read"
    assert sorted(runs) == ["follower", "leader"]
