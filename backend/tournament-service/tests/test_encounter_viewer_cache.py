"""The encounter browse's cached reads are shared between viewers, and built once per burst.

Only ``scope=my_team`` depends on who is asking, so only it keys a page by the viewer; every other scope is one
cache entry for every signed-in reader. The overview's ``my_team`` count is the one figure that always depends on the
viewer: the rest of the overview is cached without them and that count is added per request. Concurrent identical
reads on a cold cache share one build (``single_flight``).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache

from src import schemas
from src.services.encounter import flows

_EMPTY_OVERVIEW = {
    "counts": dict.fromkeys(("all", "live", "upcoming", "completed", "finals", "upsets", "with_logs", "my_team"), 0),
    "completed_with_logs": 0,
    "recent_completed": 0,
    "live": [],
}


@asynccontextmanager
async def _no_session():
    yield object()


class EncounterViewerCacheTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await cache.clear()
        self.service = flows.flows_service

    async def list_as(self, viewer: int | None, **values: Any) -> dict[str, Any]:
        params = schemas.EncounterSearchParams(tournament_id=7, **values)
        return await self.service.list_encounters(_no_session, params, workspace_id=5, viewer_auth_user_id=viewer)

    async def overview_as(self, viewer: int | None, **values: Any) -> dict[str, Any]:
        params = schemas.EncounterSearchParams(tournament_id=7, **values)
        return await self.service.encounters_overview(_no_session, params, workspace_id=5, viewer_auth_user_id=viewer)

    async def test_signed_in_readers_share_a_page_unless_it_is_their_team(self) -> None:
        load = AsyncMock(return_value=([], 0))
        with patch.object(self.service.encounters, "get_all_encounters", load):
            for viewer in (None, 11, 12):
                await self.list_as(viewer)
            self.assertEqual(1, load.await_count, "the viewer split a scope that does not read it")

            for viewer in (11, 12, 11):
                await self.list_as(viewer, scope="my_team")
            self.assertEqual(3, load.await_count, "my_team must be one page per viewer")
            self.assertEqual([11, 12], [call.kwargs["viewer_auth_user_id"] for call in load.await_args_list[1:]])

    async def test_the_overview_is_shared_and_only_my_team_is_counted_per_viewer(self) -> None:
        overview = AsyncMock(return_value=_EMPTY_OVERVIEW)
        mine = AsyncMock(
            side_effect=lambda _session, _params, *, workspace_id, viewer_auth_user_id: viewer_auth_user_id
        )
        with (
            patch.object(self.service.encounters, "get_overview_data", overview),
            patch.object(self.service.encounters, "get_my_team_count", mine),
        ):
            reads = {viewer: await self.overview_as(viewer) for viewer in (None, 11, 12)}

        self.assertEqual(1, overview.await_count)
        self.assertIsNone(overview.await_args.kwargs["viewer_auth_user_id"])
        self.assertEqual(
            {None: 0, 11: 11, 12: 12}, {viewer: read["counts"]["my_team"] for viewer, read in reads.items()}
        )
        # The shared entry keeps its own count: one viewer's never leaks into the next read.
        self.assertEqual(0, (await self.overview_as(None))["counts"]["my_team"])

    async def test_a_my_team_overview_is_the_viewers_own_entry(self) -> None:
        overview = AsyncMock(return_value=_EMPTY_OVERVIEW)
        mine = AsyncMock()
        with (
            patch.object(self.service.encounters, "get_overview_data", overview),
            patch.object(self.service.encounters, "get_my_team_count", mine),
        ):
            await self.overview_as(11, scope="my_team")
            await self.overview_as(12, scope="my_team")

        self.assertEqual([11, 12], [call.kwargs["viewer_auth_user_id"] for call in overview.await_args_list])
        mine.assert_not_awaited()

    async def test_a_burst_of_identical_cold_reads_builds_once(self) -> None:
        release = asyncio.Event()

        async def slow_page(*_args: Any, **_kwargs: Any) -> tuple[list[Any], int]:
            await release.wait()
            return [], 0

        load = AsyncMock(side_effect=slow_page)
        with patch.object(self.service.encounters, "get_all_encounters", load):
            burst = [asyncio.create_task(self.list_as(viewer)) for viewer in (None, 11, 12, 13)]
            await asyncio.sleep(0.05)
            release.set()
            pages = await asyncio.gather(*burst)

        self.assertEqual(1, load.await_count)
        self.assertTrue(all(page == pages[0] for page in pages))
