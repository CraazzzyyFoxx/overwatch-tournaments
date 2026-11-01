"""Cache behaviour + invalidation coverage for the /users/* read surface.

Guards two things that are easy to break silently:

* the per-flow ``@versioned`` keys actually memoize (and normalize their inputs), and
* every user read cache misses after *both* invalidation shapes (a tournament write → every user; a profile/identity
  edit → that user), so a longer TTL never serves stale data.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))


flows = importlib.import_module("src.services.user.service")
enums = importlib.import_module("shared.core.enums")
pagination = importlib.import_module("shared.core.pagination")
user_cache = importlib.import_module("shared.services.user_cache")
users = flows.UserService.of("overwatch")

from shared.schemas.events import CacheInvalidatedEvent  # noqa: E402
from shared.schemas.identity import PersonDisplayRead  # noqa: E402
from shared.services.realtime import Resource  # noqa: E402
from shared.services.realtime.consumer import invalidate_from_event  # noqa: E402
from shared.testing.cache import configure_test_cache  # noqa: E402


async def _tournament_write(*resources: Resource) -> None:
    await invalidate_from_event(
        CacheInvalidatedEvent(scope_kind="tournament", scope_id=42, resources=[str(r) for r in resources])
    )


class _CacheTestBase(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        configure_test_cache()
        await cache.clear()


class _SummaryReads(_CacheTestBase):
    """``get_matches_summary`` stands in for every per-user read: all of them are keyed by ``user_generations``."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.opponents = AsyncMock(return_value=[])
        for patcher in (
            patch.object(users, "get", AsyncMock(return_value=SimpleNamespace(id=1, name="Player"))),
            patch.object(users.encounters, "get_user_opponents", self.opponents),
            patch.object(users.encounters, "get_user_stage_breakdown", AsyncMock(return_value=[])),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def read(self, *user_ids: int) -> int:
        """Read each user's summary; how many were rebuilt."""
        before = self.opponents.await_count
        for user_id in user_ids:
            await users.get_matches_summary(object(), user_id, workspace_id=1)
        return self.opponents.await_count - before


class UserCacheInvalidationTests(_SummaryReads):
    async def test_a_tournament_write_misses_every_users_reads(self) -> None:
        # The event does not name the users a tournament touched.
        self.assertEqual(2, await self.read(5, 6))
        for resource in (
            Resource.TOURNAMENT_STANDINGS,
            Resource.TOURNAMENT_TEAMS,
            Resource.TOURNAMENT_STRUCTURE,
            Resource.TOURNAMENT_DETAIL,
            Resource.TOURNAMENT_STAGES,
        ):
            await _tournament_write(resource)
            self.assertEqual(2, await self.read(5, 6), resource)

    async def test_a_score_report_or_a_registration_misses_no_users_reads(self) -> None:
        self.assertEqual(2, await self.read(5, 6))
        await _tournament_write(Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_REGISTRATIONS)
        self.assertEqual(0, await self.read(5, 6))

    async def test_a_profile_edit_misses_only_the_subjects_reads(self) -> None:
        self.assertEqual(2, await self.read(5, 6))
        await user_cache.invalidate_user_caches(5)
        self.assertEqual(1, await self.read(5, 6))
        self.assertEqual(0, await self.read(5, 6))

    async def test_a_merge_misses_both_users_reads(self) -> None:
        self.assertEqual(3, await self.read(7, 9, 11))
        await user_cache.invalidate_user_caches(7, 9)
        self.assertEqual(2, await self.read(7, 9, 11))


class CharactersCacheTests(_CacheTestBase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # The reads under test cache whole payloads; naming the user is a database read these tests do not have.
        patcher = patch.object(
            flows, "load_person_displays", AsyncMock(return_value={101: PersonDisplayRead(name="Player")})
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_deps(self):
        user = SimpleNamespace(id=101, name="Player")
        get_user = patch.object(users, "get", AsyncMock(return_value=user))
        compute = AsyncMock(return_value=[])
        svc = patch.multiple(
            users.profile,
            get_statistics_by_heroes=compute,
            get_statistics_by_heroes_all_values=AsyncMock(return_value=[]),
        )
        records = patch.object(users.encounters, "get_user_hero_records", AsyncMock(return_value=[]))
        return get_user, svc, compute, records

    async def test_repeat_request_is_served_from_cache(self) -> None:
        get_user, svc, compute, records = self._patch_deps()
        params = pagination.PaginationParams(page=1, per_page=10)
        stats = [enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations]
        with get_user, svc, records:
            await users.get_heroes(object(), 101, params, stats, workspace_id=1)
            await users.get_heroes(object(), 101, params, stats, workspace_id=1)
            stored = [key async for key in cache.scan("backend:user_characters*")]
        compute.assert_awaited_once()
        # Versioned (rows gained fields).
        self.assertTrue(stored)
        self.assertTrue(all(key.startswith("backend:user_characters:v3:101:") for key in stored), stored)

    async def test_stats_order_and_duplicates_share_one_key(self) -> None:
        get_user, svc, compute, records = self._patch_deps()
        params = pagination.PaginationParams(page=1, per_page=10)
        with get_user, svc, records:
            await users.get_heroes(
                object(),
                101,
                params,
                [enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations],
                workspace_id=1,
            )
            await users.get_heroes(
                object(),
                101,
                params,
                [enums.LogStatsName.Eliminations, enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations],
                workspace_id=1,
            )
        compute.assert_awaited_once()

    async def test_pagination_is_part_of_the_key(self) -> None:
        get_user, svc, compute, records = self._patch_deps()
        stats = [enums.LogStatsName.Deaths]
        with get_user, svc, records:
            await users.get_heroes(
                object(), 101, pagination.PaginationParams(page=1, per_page=10), stats, workspace_id=1
            )
            await users.get_heroes(
                object(), 101, pagination.PaginationParams(page=2, per_page=10), stats, workspace_id=1
            )
        self.assertEqual(2, compute.await_count)


class MatchesSummaryCacheTests(_CacheTestBase):
    async def test_repeat_request_is_served_from_cache(self) -> None:
        user = SimpleNamespace(id=202, name="Player")
        opponents = AsyncMock(return_value=[])
        with (
            patch.object(users, "get", AsyncMock(return_value=user)),
            patch.object(users.encounters, "get_user_opponents", opponents),
            patch.object(users.encounters, "get_user_stage_breakdown", AsyncMock(return_value=[])),
        ):
            await users.get_matches_summary(object(), 202, workspace_id=1)
            await users.get_matches_summary(object(), 202, workspace_id=1)
            await users.get_matches_summary(object(), 202, workspace_id=2)  # different scope
        self.assertEqual(2, opponents.await_count)


class VersionedEncounterFamiliesTests(_CacheTestBase):
    async def test_both_encounter_families_miss_after_both_invalidation_shapes(self) -> None:
        """``user_encounters`` and ``user_tournament_encounters`` embed the native match header of one game, so their
        keys are versioned (``:v8:``); a subject's edit and a tournament write must both still reach them."""
        user = SimpleNamespace(id=404, name="Player")
        page = AsyncMock(return_value=([], 0))
        dossier = AsyncMock(return_value=[])
        params = pagination.PaginationSortParams(page=1, per_page=10, sort="played_at")
        with (
            patch.object(users, "get", AsyncMock(return_value=user)),
            patch.object(users.encounters, "get_user_encounters_paginated", page),
            patch.object(users.encounters, "get_user_encounter_matches_unpaginated", dossier),
        ):

            async def read() -> None:
                await users.get_encounters_by_user(object(), 404, params, workspace_id=1)
                await users.get_tournament_encounters(object(), 404, 7)

            await read()
            stored = sorted([key async for key in cache.scan("backend:*")])
            self.assertEqual(
                ["backend:user_encounters:v9:404:", "backend:user_tournament_encounters:v9:404:"],
                [key[: key.index("404:") + 4] for key in stored],
            )
            await read()
            await user_cache.invalidate_user_caches(404)
            await read()
            await _tournament_write(Resource.TOURNAMENT_STANDINGS)
            await read()
        self.assertEqual(3, page.await_count)
        self.assertEqual(3, dossier.await_count)


class CacheKeyShapeTests(_CacheTestBase):
    def test_no_cache_decorator_reintroduces_the_prefix_kwarg(self) -> None:
        """``prefix="backend:"`` next to a bare ``key="user_…"`` renders ``backend::user_…`` (cashews joins them with
        a colon). The prefix belongs in the key template."""
        domain = Path(__file__).resolve().parents[1] / "src" / "services"
        offenders = [
            path.relative_to(domain).as_posix()
            for path in domain.rglob("*.py")
            if 'prefix="backend:"' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)
