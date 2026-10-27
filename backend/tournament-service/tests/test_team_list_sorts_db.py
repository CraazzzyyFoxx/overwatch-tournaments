"""``list_teams`` sorted by group or placement: a page of teams like any other sort.

Both sorts read a value off the teams' standings. A team without one (no group yet, no final place) still lists --
last, whichever way the order runs -- a team with several standings lists once, and LIMIT/OFFSET count teams, so the
pages agree with ``total``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache

from shared.core import enums
from shared.core.pagination import SortOrder
from shared.models.tournament.stage import StageItem
from shared.models.tournament.standings import Standing
from src import schemas
from src.services.team import flows as team_flows
from src.services.team.service import team_service
from tests._encounter_layer import EncounterLayerCase


class TeamListSortTests(EncounterLayerCase):
    """Teams ``t0``..``t3`` in groups B (``t0``), A and C (``t2``) and C (``t1``); final places ``t3`` 1st and ``t1``
    2nd (and 5th in group C). ``t3`` has no group, ``t0`` and ``t2`` no place."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        t0, t1, t2, t3 = self.teams
        async with self.Session() as s:
            groups = {
                name: StageItem(stage_id=self.stage_id, name=name, type=enums.StageItemType.GROUP, order=order)
                for order, name in enumerate("ABC", 1)
            }
            s.add_all(groups.values())
            await s.flush()
            s.add_all(
                Standing(
                    tournament_id=self.tournament_id,
                    team_id=team_id,
                    stage_id=self.stage_id,
                    stage_item_id=item_id,
                    position=1,
                    overall_position=overall_position,
                    matches=0,
                    points=0.0,
                )
                for team_id, item_id, overall_position in (
                    (t0, groups["B"].id, 0),
                    (t2, groups["A"].id, 0),
                    (t2, groups["C"].id, 0),
                    (t1, groups["C"].id, 5),
                    (t1, self.item_id, 2),
                    (t3, self.item_id, 1),
                )
            )
            await s.commit()

    async def page(self, **values: Any) -> tuple[list[str], int]:
        params = schemas.TeamFilterParams(tournament_id=self.tournament_id, **values)
        async with self.Session() as s:
            rows, total = await team_service.get_all(s, params)
        return [row.name for row in rows], total

    async def test_group_pages_every_team_and_puts_the_groupless_last(self) -> None:
        self.assertEqual((["t2", "t0"], 4), await self.page(sort="group", per_page=2, page=1))
        self.assertEqual((["t1", "t3"], 4), await self.page(sort="group", per_page=2, page=2))
        self.assertEqual(
            (["t1", "t0", "t2", "t3"], 4), await self.page(sort="group", order=SortOrder.DESC, per_page=10)
        )

    async def test_placement_pages_every_team_and_puts_the_unplaced_last(self) -> None:
        self.assertEqual((["t3", "t1", "t0"], 4), await self.page(sort="placement", per_page=3, page=1))
        self.assertEqual((["t2"], 4), await self.page(sort="placement", per_page=3, page=2))

    async def test_a_count_only_read_returns_the_total_and_no_rows(self) -> None:
        self.assertEqual(([], 4), await self.page(sort="group", only_count=True))


class TeamListCacheKeyTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await cache.clear()

    async def test_a_count_only_read_is_not_a_one_row_page(self) -> None:
        # ``getCount`` asks for the total alone; a first page of one row under the default sort is another answer.
        load = AsyncMock(side_effect=[([], 4), ([SimpleNamespace()], 4)])
        params = {"tournament_id": 7, "per_page": 1}
        with (
            patch.object(team_flows.flows_service.teams, "get_all", load),
            patch.object(team_flows.flows_service, "to_pydantic_many", AsyncMock(return_value=[])),
        ):
            await team_flows.flows_service.get_all(object(), schemas.TeamFilterParams(only_count=True, **params))
            await team_flows.flows_service.get_all(object(), schemas.TeamFilterParams(**params))
        self.assertEqual(2, load.await_count)
