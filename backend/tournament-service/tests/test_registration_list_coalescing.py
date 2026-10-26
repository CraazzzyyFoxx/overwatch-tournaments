"""Single-flight coalescing of the public registration-list rebuild.

The list is the heaviest public read and every connected viewer refetches it
at once after any registration mutation (the "realtime invalidation herd").
Two things matter here and nothing else:

1. A burst of concurrent callers for the SAME tournament_id must trigger
   exactly one real read-model build -- not one per caller.
2. One follower's cancellation must never take the shared build down with it
   for every other follower still waiting on it.
3. A request arriving after a write never joins a build that started before it.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.schemas.events import CacheInvalidatedEvent  # noqa: E402
from shared.services.realtime.consumer import invalidate_from_event  # noqa: E402
from shared.testing.cache import configure_test_cache  # noqa: E402
from src.core import caching  # noqa: E402
from src.services.registration import public_list  # noqa: E402


class _FakeSessionCtx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> None:
        return None


def _session_maker() -> _FakeSessionCtx:
    return _FakeSessionCtx()


def _build(fake_build: object) -> Any:
    return patch.object(public_list.registration_service, "build_public_registration_list", fake_build)


class TestCoalescing(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        configure_test_cache()
        caching._inflight.clear()
        # The cashews layer under the coalescer is pinned by the cache-namespace
        # tests; here it would serve a sequential call from cache and mask
        # whether the in-flight share was released.
        uncached = patch.object(public_list, "build_registration_list", public_list.build_registration_list.__wrapped__)
        uncached.start()
        self.addCleanup(uncached.stop)

    async def test_concurrent_callers_share_one_build(self) -> None:
        calls = 0

        async def fake_build(session: object, *, tournament_id: int) -> str:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return f"snapshot-{tournament_id}-{calls}"

        with _build(fake_build):
            results = await asyncio.gather(
                *[public_list.coalesced_registration_list(_session_maker, 42) for _ in range(6)]
            )

        assert calls == 1, f"expected one real build for the whole burst, got {calls}"
        assert len(set(results)) == 1, "every concurrent caller must see the same live snapshot"
        assert not caching._inflight, "in-flight entry must be cleaned up after completion"

    async def test_distinct_tournaments_never_share_a_build(self) -> None:
        seen_ids: list[int] = []

        async def fake_build(session: object, *, tournament_id: int) -> int:
            seen_ids.append(tournament_id)
            await asyncio.sleep(0.02)
            return tournament_id

        with _build(fake_build):
            results = await asyncio.gather(
                public_list.coalesced_registration_list(_session_maker, 1),
                public_list.coalesced_registration_list(_session_maker, 2),
            )

        assert sorted(seen_ids) == [1, 2]
        assert results == [1, 2]

    async def test_sequential_calls_after_completion_rebuild(self) -> None:
        calls = 0

        async def fake_build(session: object, *, tournament_id: int) -> int:
            nonlocal calls
            calls += 1
            return calls

        with _build(fake_build):
            first = await public_list.coalesced_registration_list(_session_maker, 7)
            second = await public_list.coalesced_registration_list(_session_maker, 7)

        assert (first, second) == (1, 2), "a call after the burst settles must see fresh, live data, not a stale share"

    async def test_follower_cancellation_does_not_kill_the_shared_build(self) -> None:
        calls = 0

        async def fake_build(session: object, *, tournament_id: int) -> str:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.1)
            return "ok"

        with _build(fake_build):
            leader = asyncio.create_task(public_list.coalesced_registration_list(_session_maker, 9))
            follower = asyncio.create_task(public_list.coalesced_registration_list(_session_maker, 9))
            await asyncio.sleep(0.02)

            follower.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await follower

            result = await leader

        assert result == "ok"
        assert calls == 1

    async def test_a_request_after_a_write_starts_its_own_build(self) -> None:
        # The build that started before the write read the pre-write rows; a request after it must not be handed
        # that result, which is what joining its flight would do.
        release = asyncio.Event()
        builds = 0

        async def fake_build(session: object, *, tournament_id: int) -> str:
            nonlocal builds
            builds += 1
            build = builds
            if build == 1:
                await release.wait()
            return f"build-{build}"

        with _build(fake_build):
            before = asyncio.create_task(public_list.coalesced_registration_list(_session_maker, 11))
            await asyncio.sleep(0.01)
            await invalidate_from_event(
                CacheInvalidatedEvent(scope_kind="tournament", scope_id=11, resources=["tournament.registrations"])
            )
            try:
                after = await asyncio.wait_for(public_list.coalesced_registration_list(_session_maker, 11), timeout=2)
            finally:
                release.set()

            assert after == "build-2", "the request after the write joined the build from before it"
            assert await before == "build-1"
