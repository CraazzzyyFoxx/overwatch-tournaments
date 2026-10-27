"""The durable re-bump moves only a generation whose commit-time bump was lost.

Every consuming service gets each ``CacheInvalidatedEvent``; re-bumping a generation the writer's commit already
moved orphaned every entry cached since — one extra miss wave per consumer per write.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from cashews import cache  # noqa: E402

from shared.schemas.events import CacheInvalidatedEvent  # noqa: E402
from shared.services.cache_generations import PREFIX, bump, current  # noqa: E402
from shared.services.realtime import Resource, resource_generation  # noqa: E402
from shared.services.realtime.consumer import invalidate_from_event  # noqa: E402
from shared.testing.cache import configure_test_cache  # noqa: E402

RESOURCE = Resource("tournament.standings")
NAMES = (resource_generation(RESOURCE, 42), resource_generation(RESOURCE))


def _event(at: float) -> CacheInvalidatedEvent:
    return CacheInvalidatedEvent(scope_kind="tournament", scope_id=42, resources=[str(RESOURCE)], timestamp=at)


async def _values() -> list[str]:
    return [await current(name) for name in NAMES]


class ConditionalRebumpTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        configure_test_cache()

    async def asyncTearDown(self) -> None:
        await cache.delete_many(*(PREFIX + name for name in NAMES))

    async def test_a_generation_bumped_after_the_event_is_left_alone(self) -> None:
        written_at = time.time() - 1  # the event is stamped inside the transaction, before its commit bump
        await bump(*NAMES)
        before = await _values()

        await invalidate_from_event(_event(written_at))

        self.assertEqual(before, await _values())

    async def test_a_lost_commit_bump_is_redone(self) -> None:
        await bump(*NAMES)  # an earlier write's bump; this write's own bump never landed
        before = await _values()

        await invalidate_from_event(_event(time.time() + 1))

        self.assertTrue(all(a != b for a, b in zip(await _values(), before, strict=True)))

    async def test_a_generation_only_a_read_created_is_bumped(self) -> None:
        before = await _values()  # created by ``current``: never bumped

        await invalidate_from_event(_event(time.time()))

        self.assertTrue(all(a != b for a, b in zip(await _values(), before, strict=True)))

    async def test_values_written_before_the_stamp_still_parse_and_are_bumped(self) -> None:
        # Pre-stamp values are bare 12-hex tokens; an all-digit one must not read as a bump time.
        for name, legacy in zip(NAMES, ("a1b2c3d4e5f6", "123456789012"), strict=True):
            await cache.set(PREFIX + name, legacy)

        await invalidate_from_event(_event(time.time()))

        self.assertTrue(all(value not in ("a1b2c3d4e5f6", "123456789012") for value in await _values()))
