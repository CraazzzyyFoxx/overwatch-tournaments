"""The public registration list and the teams list moved to versioned cache names (``:v2:``, teams ``:v3:``).

Their payloads changed shape in the multi-game cutover (``top_characters``, a required
``TournamentHistoryEntry.discipline``, roles as ``{dimension, role}``) while the keys stayed put, and the teams list
then moved from the pickled model to its wire dict. Values are pickled in a Redis that outlives a deploy and cashews
hands them back without re-validating, so a warm pre-bump entry would be served in the old shape. These tests pin the
keys cashews really writes, that a pre-bump entry is never read, and that a tournament write misses the versioned reads
of exactly one tournament.
"""

from __future__ import annotations

import importlib
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


public_list = importlib.import_module("src.services.registration.public_list")
team_flows = importlib.import_module("src.services.team.flows")
schemas = importlib.import_module("src.schemas")

from shared.schemas.events import CacheInvalidatedEvent  # noqa: E402
from shared.services.realtime import Resource  # noqa: E402
from shared.services.realtime.consumer import invalidate_from_event  # noqa: E402
from shared.testing.cache import configure_test_cache  # noqa: E402


@asynccontextmanager
async def _no_session():
    yield object()


async def _stored() -> set[str]:
    return {key async for key in cache.scan("fastapi:*")}


def _pre_bump(key: str) -> str:
    """The same key one version back (``:v2:`` had none before it)."""
    version = int(re.search(r":v(\d+):", key).group(1))
    return key.replace(f":v{version}:", ":" if version == 2 else f":v{version - 1}:", 1)


class RegistrationAndTeamCacheNamespaceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        configure_test_cache()
        await cache.clear()
        self.build = AsyncMock(side_effect=lambda _session, *, tournament_id: {"fresh": tournament_id})
        self.page = AsyncMock(return_value=([], 0))
        service = team_flows.flows_service
        for patcher in (
            patch.object(public_list.registration_service, "build_public_registration_list", self.build),
            patch.object(team_flows.tournament_flows_service, "get", AsyncMock()),
            patch.object(service.teams, "get_all", self.page),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await cache.clear()

    @staticmethod
    async def _registration_list(tournament_id: int):
        return await public_list.build_registration_list(_no_session, tournament_id)

    @staticmethod
    async def _teams_page(tournament_id: int):
        params = schemas.TeamFilterParams(tournament_id=tournament_id)
        return await team_flows.flows_service.get_all(object(), params, workspace_id=5)

    async def test_each_family_writes_its_v2_key_and_never_reads_the_pre_bump_one(self) -> None:
        for read, upstream, prefix in (
            (self._registration_list, self.build, "fastapi::registration_list:v2:7:"),
            (self._teams_page, self.page, "fastapi::teams:v3:5:7:"),
        ):
            fresh = await read(7)
            (key,) = await _stored()
            self.assertTrue(key.startswith(prefix), key)
            self.assertEqual(fresh, await read(7))
            self.assertEqual(1, upstream.await_count, f"{key!r} is not the key the read looks up")

            # A warm entry under the old name, as a pre-cutover deploy left it in Redis.
            await cache.delete(key)
            await cache.set(_pre_bump(key), "stale")
            self.assertEqual(fresh, await read(7), f"{_pre_bump(key)!r} was served")
            self.assertEqual(2, upstream.await_count)
            await cache.clear()

    async def test_a_tournament_write_misses_its_reads_but_no_other_tournaments(self) -> None:
        for resources, read, upstream in (
            (
                (Resource.TOURNAMENT_REGISTRATIONS, Resource.TOURNAMENT_REGISTRATION_FORM),
                self._registration_list,
                self.build,
            ),
            ((Resource.TOURNAMENT_TEAMS, Resource.TOURNAMENT_STRUCTURE), self._teams_page, self.page),
        ):
            for resource in resources:
                for tournament_id in (7, 70):
                    await read(tournament_id)
                before = upstream.await_count

                await invalidate_from_event(
                    CacheInvalidatedEvent(scope_kind="tournament", scope_id=7, resources=[str(resource)])
                )

                for tournament_id in (7, 70):
                    await read(tournament_id)
                self.assertEqual(before + 1, upstream.await_count, f"{resource}: not exactly tournament 7 rebuilt")
