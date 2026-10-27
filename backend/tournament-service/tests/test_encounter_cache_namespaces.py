"""The encounter list and overview caches embed ``MatchRead``; the native match cutover renamed their namespaces.

Their values are pickled in a Redis that outlives a deploy, and cashews hands an unpickled value back without
re-validating its nested models, so a warm pre-cutover entry would serve match documents without ``participants``.
The names changed instead (``native_encounters*``): nothing asks for an old entry any more. These tests pin the new
names against the keys cashews really renders, and that every tournament write still misses them.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache
from cashews.key import get_cache_key

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


flows = importlib.import_module("src.services.encounter.flows")
schemas = importlib.import_module("src.schemas")

from shared.schemas.events import CacheInvalidatedEvent  # noqa: E402
from shared.services.realtime import Resource  # noqa: E402
from shared.services.realtime.consumer import invalidate_from_event  # noqa: E402
from shared.testing.cache import configure_test_cache  # noqa: E402

_PRE_CUTOVER = ("encounters", "encounters_overview")


def _key(template: str, function, *, workspace_id: int | None, tournament_id: int | None) -> str:
    """The stored key's prefix: cashews renders ``prefix`` + ``:`` + template (``fastapi::...``), then the
    tournament's generations."""
    kwargs = {
        "workspace_id": workspace_id,
        "params": schemas.EncounterSearchParams(tournament_id=tournament_id),
        "viewer_auth_user_id": None,
    }
    return "fastapi::" + get_cache_key(inspect.unwrap(function), template, kwargs=kwargs)


async def _write(tournament_id: int, *resources: Resource) -> None:
    await invalidate_from_event(
        CacheInvalidatedEvent(scope_kind="tournament", scope_id=tournament_id, resources=[str(r) for r in resources])
    )


_EMPTY_OVERVIEW = {
    "counts": dict.fromkeys(("all", "live", "upcoming", "completed", "finals", "upsets", "with_logs", "my_team"), 0),
    "completed_with_logs": 0,
    "recent_completed": 0,
    "live": [],
}
_EMPTY_INSIGHTS = {
    "completed": 0,
    "avg_closeness": None,
    "avg_series_seconds": None,
    "multi_map": 0,
    "sweeps": 0,
    "went_distance": 0,
    "closeness_histogram": [],
    "stage_kinds": [],
    "score_lines": [],
    "hot_maps": [],
    "closest": [],
}


class EncounterCacheNamespaceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        configure_test_cache()
        await cache.clear()

    def test_every_family_moved_off_its_pre_cutover_name(self) -> None:
        for template, function, name in (
            (flows.ENCOUNTERS_CACHE_KEY, flows.EncounterFlowsService.encounters_page, "native_encounters:v5"),
            (
                flows.ENCOUNTERS_OVERVIEW_CACHE_KEY,
                flows.EncounterFlowsService.overview_page,
                "native_encounters_overview:v5",
            ),
            (
                flows.ENCOUNTERS_INSIGHTS_CACHE_KEY,
                flows.EncounterFlowsService.insights_page,
                "native_encounters_insights:v2",
            ),
        ):
            key = _key(template, function, workspace_id=5, tournament_id=7)
            self.assertTrue(key.startswith(f"fastapi::{name}:5:7:"), key)
            for old in _PRE_CUTOVER:
                self.assertFalse(key.startswith(f"fastapi::{old}:"), f"{key!r} is still in the pre-cutover namespace")

    async def test_the_decorated_list_writes_the_native_key_and_a_tournament_write_misses_it(self) -> None:
        service = flows.flows_service
        read = AsyncMock(return_value=([], 0))
        with (
            patch.object(service.encounters, "get_all_encounters", read),
            patch.object(flows, "resolve_encounter_challonge", AsyncMock(return_value={})),
            patch.object(flows, "resolve_tournament_challonge", AsyncMock(return_value={})),
            patch.object(flows, "resolve_slot_sources", AsyncMock(return_value={})),
        ):
            for tournament_id in (7, 70):
                await service.encounters_page(
                    object(), schemas.EncounterSearchParams(tournament_id=tournament_id), workspace_id=5
                )
            stored = [key async for key in cache.scan("fastapi:*")]
            self.assertEqual(2, len(stored))
            for tournament_id in (7, 70):
                prefix = _key(
                    flows.ENCOUNTERS_CACHE_KEY,
                    flows.EncounterFlowsService.encounters_page,
                    workspace_id=5,
                    tournament_id=tournament_id,
                )
                self.assertEqual(1, sum(key.startswith(prefix) for key in stored), (prefix, stored))

            await _write(7, Resource.TOURNAMENT_ENCOUNTERS)

            # Tournament 7 is rebuilt and 70 is not: a generation names one tournament exactly.
            for tournament_id in (7, 70):
                await service.encounters_page(
                    object(), schemas.EncounterSearchParams(tournament_id=tournament_id), workspace_id=5
                )
        self.assertEqual(3, read.await_count, "the write did not force exactly one rebuild")

    async def test_the_decorated_overview_writes_the_native_key_and_a_tournament_write_misses_it(self) -> None:
        service = flows.flows_service
        read = AsyncMock(return_value=_EMPTY_OVERVIEW)
        with (
            patch.object(service.encounters, "get_overview_data", read),
            patch.object(flows, "resolve_encounter_challonge", AsyncMock(return_value={})),
            patch.object(flows, "resolve_tournament_challonge", AsyncMock(return_value={})),
        ):
            params = schemas.EncounterSearchParams(tournament_id=7)
            await service.overview_page(object(), params, workspace_id=5)
            expected = _key(
                flows.ENCOUNTERS_OVERVIEW_CACHE_KEY,
                flows.EncounterFlowsService.overview_page,
                workspace_id=5,
                tournament_id=7,
            )
            [stored] = [key async for key in cache.scan("fastapi:*")]
            self.assertTrue(stored.startswith(expected), stored)

            await service.overview_page(object(), params, workspace_id=5)
            await _write(7, Resource.TOURNAMENT_ENCOUNTERS)
            await service.overview_page(object(), params, workspace_id=5)
        self.assertEqual(2, read.await_count, "the write did not force a rebuild")

    async def test_every_resource_that_changes_an_encounter_misses_every_family(self) -> None:
        service = flows.flows_service
        page = AsyncMock(return_value=([], 0))
        overview = AsyncMock(return_value=_EMPTY_OVERVIEW)
        insights = AsyncMock(return_value=_EMPTY_INSIGHTS)
        with (
            patch.object(service.encounters, "get_all_encounters", page),
            patch.object(service.encounters, "get_overview_data", overview),
            patch.object(service.encounters, "get_insights_data", insights),
        ):

            async def read_all() -> None:
                for tournament_id in (7, 8):
                    params = schemas.EncounterSearchParams(tournament_id=tournament_id)
                    await service.encounters_page(object(), params, workspace_id=5)
                    await service.overview_page(object(), params, workspace_id=5)
                    await service.insights_page(object(), params, workspace_id=5)

            await read_all()
            for resource in (Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STRUCTURE):
                before = (page.await_count, overview.await_count, insights.await_count)
                await _write(7, resource)
                await read_all()
                # Tournament 7's three reads rebuilt once each; tournament 8's stayed cached.
                self.assertEqual(
                    (before[0] + 1, before[1] + 1, before[2] + 1),
                    (page.await_count, overview.await_count, insights.await_count),
                    resource,
                )
