"""The browse's quick toggles, the overview's counts, the insights and the saved views (``services/encounter``).

Against the real Postgres: every toggle is a correlated EXISTS that has to compose inside the overview's aggregate
``FILTER`` clauses, and a page's serialization must cost the same statements at any page size.
"""

from __future__ import annotations

import inspect
import itertools
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event as sa_event

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.encounter import Encounter
from shared.models.identity.auth_user import AuthUser
from shared.models.identity.user import User
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Player
from shared.models.tournament.tournament import Tournament
from src import schemas
from src.services.encounter.flows import flows_service
from src.services.encounter.games import encounter_game_service
from src.services.encounter.service import SAVED_VIEW_LIMIT, encounter_service
from tests._encounter_layer import EncounterLayerCase

_TAG = itertools.count()
_PAGE_ENTITIES = ["tournament", "stage", "stage_item", "teams", "matches", "matches.map"]


async def _uncached(method: Any, *args: Any, **kwargs: Any) -> Any:
    """The flow under its cache decorator: the real SQL and serializer, no cache backend."""
    return await inspect.unwrap(method.__func__)(method.__self__, *args, **kwargs)


def _codes(exc: BaseAPIException) -> list[str]:
    return [item["code"] for item in exc.detail]


async def _date_the_tournament(case: EncounterLayerCase) -> None:
    """A nested ``TournamentRead`` needs its dates; around now, so a result confirmed now is a play date."""
    now = datetime.now(UTC)
    async with case.Session() as s:
        await s.execute(
            sa.update(Tournament)
            .where(Tournament.id == case.tournament_id)
            .values(start_date=now - timedelta(days=1), end_date=now + timedelta(days=1))
        )
        await s.commit()


class BoardTests(EncounterLayerCase):
    """A single elimination (two semis, a final still to play) and a group stage beside it.

    Standings in the bracket item put ``t0`` first and ``t3`` last, so ``t3`` beating ``t2`` is the one upset.
    ``t1`` is the viewer's team: a linked player of theirs is rostered on it.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await _date_the_tournament(self)
        self.semi_one = await self.encounter(0, 1, round_number=1, scores=[2, 1])
        self.semi_two = await self.encounter(2, 3, round_number=1, scores=[0, 2])
        self.final = await self.encounter(0, 3, round_number=2)
        tag = f"board-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            groups = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Groups",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=0,
            )
            s.add(groups)
            await s.flush()
            group = StageItem(stage_id=groups.id, name="G", type=enums.StageItemType.GROUP, order=0)
            s.add(group)
            await s.flush()
            self.groups_id, self.group_id = groups.id, group.id
            s.add_all(
                Standing(
                    tournament_id=self.tournament_id,
                    team_id=team_id,
                    stage_id=self.stage_id,
                    stage_item_id=self.item_id,
                    position=position,
                    matches=1,
                    points=0.0,
                )
                for position, team_id in enumerate(self.teams, 1)
            )
            account = AuthUser(email=f"{tag}@example.test", username=tag, is_active=True)
            s.add(account)
            await s.flush()
            user = User(name=f"{tag}-zarya", auth_user_id=account.id)
            s.add(user)
            await s.flush()
            member = WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
            s.add(member)
            await s.flush()
            s.add(
                Player(
                    name=user.name,
                    tournament_id=self.tournament_id,
                    workspace_member_id=member.id,
                    team_id=self.teams[1],
                )
            )
            await s.commit()
            self.auth_user_id, self.user_id, self.player_name = account.id, user.id, user.name
        # A group's last round is no final: only an elimination stage has one.
        self.group = await self.encounter(
            1, 2, stage_id=self.groups_id, item_id=self.group_id, round_number=3, scores=[2, 0]
        )

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            # The workspace first: its member anchors the player row the user is.
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.execute(sa.delete(User).where(User.id == self.user_id))
            await s.execute(sa.delete(AuthUser).where(AuthUser.id == self.auth_user_id))
            await s.commit()
        await self.engine.dispose()

    def params(self, **values: Any) -> schemas.EncounterSearchParams:
        return schemas.EncounterSearchParams(per_page=50, tournament_id=self.tournament_id, **values)

    async def ids(self, viewer: int | None = None, **values: Any) -> set[int]:
        async with self.Session() as s:
            rows, total = await encounter_service.get_all_encounters(
                s, self.params(**values), viewer_auth_user_id=viewer
            )
        self.assertEqual(len(rows), total)
        return {row.id for row in rows}

    async def overview(self, viewer: int | None = None, **values: Any) -> dict[str, Any]:
        async with self.Session() as s:
            return await encounter_service.get_overview_data(s, self.params(**values), viewer_auth_user_id=viewer)

    async def set(self, encounter_id: int, **values: Any) -> None:
        async with self.Session() as s:
            await s.execute(sa.update(Encounter).where(Encounter.id == encounter_id).values(**values))
            await s.commit()

    async def test_the_final_is_the_last_positive_round_of_an_elimination_stage(self) -> None:
        self.assertEqual({self.final}, await self.ids(is_final=True))
        self.assertEqual({self.semi_one, self.semi_two, self.group}, await self.ids(is_final=False))
        async with self.Session() as s:
            page = await _uncached(flows_service.get_all_encounters, s, self.params(entities=["stage"]))
        self.assertEqual({self.final}, {row.id for row in page.results if row.is_final})

    async def test_an_upset_is_won_by_the_lower_standing(self) -> None:
        self.assertEqual({self.semi_two}, await self.ids(is_upset=True))
        self.assertEqual({self.semi_one, self.final, self.group}, await self.ids(is_upset=False))

    async def test_a_search_reads_the_seats_and_their_rosters(self) -> None:
        # Every encounter is named "E": these hits come from the seats and the roster, not the title.
        self.assertEqual({self.semi_two, self.final}, await self.ids(query="t3", fields=["name"]))
        self.assertEqual({self.semi_one, self.group}, await self.ids(query=self.player_name, fields=["name"]))

    async def test_my_team_is_the_viewers_roster_and_nothing_for_an_anonymous_one(self) -> None:
        self.assertEqual({self.semi_one, self.group}, await self.ids(viewer=self.auth_user_id, scope="my_team"))
        self.assertEqual(set(), await self.ids(scope="my_team"))
        self.assertEqual(2, (await self.overview(viewer=self.auth_user_id))["counts"]["my_team"])
        self.assertEqual(0, (await self.overview())["counts"]["my_team"])

    async def test_the_viewers_count_alone_is_the_overviews_my_team(self) -> None:
        # The cached overview leaves the viewer out and adds this count per request: the two must agree.
        for values in ({}, {"status": "completed"}, {"is_upset": False}, {"scope": "my_team"}):
            async with self.Session() as s:
                alone = await encounter_service.get_my_team_count(
                    s, self.params(**values), viewer_auth_user_id=self.auth_user_id
                )
            with self.subTest(values=values):
                self.assertEqual((await self.overview(viewer=self.auth_user_id, **values))["counts"]["my_team"], alone)

    async def test_the_counts_compose_the_status_and_the_toggles(self) -> None:
        await self.set(self.final, started_at=datetime.now(UTC) - timedelta(minutes=5))
        plain = await self.overview()
        self.assertEqual(
            {
                "all": 4,
                "live": 1,
                "upcoming": 0,
                "completed": 3,
                "finals": 1,
                "upsets": 1,
                "with_logs": 0,
                "my_team": 0,
            },
            plain["counts"],
        )
        # No tournament dates bound it, so the confirmation is the play date: all three were played just now.
        self.assertEqual((0, 3), (plain["completed_with_logs"], plain["recent_completed"]))
        self.assertEqual([self.final], [row.id for row in plain["live"]])

        # A toggle narrows every segment; the status filter never does.
        upsets = await self.overview(is_upset=True, status="live")
        self.assertEqual((1, 0, 1), tuple(upsets["counts"][key] for key in ("all", "live", "completed")))
        # A toggle's own count is the total with it forced on, under the status and the other toggles.
        for toggle, count in (("is_final", "finals"), ("is_upset", "upsets")):
            for status in (None, "completed", "live"):
                counts = (await self.overview(status=status, is_final=False))["counts"]
                forced = await self.ids(status=status, **{"is_final": False, toggle: True})
                with self.subTest(toggle=toggle, status=status):
                    self.assertEqual(len(forced), counts[count])

    async def test_the_insights_read_the_completed_encounters(self) -> None:
        await self.set(self.semi_one, closeness=0.8)
        await self.set(self.semi_two, closeness=0.5)
        await self.set(self.group, closeness=1.0)
        await self.set(self.final, closeness=0.9)  # not completed: never counted
        # A decided Bo1 is 1:0 -- "a sweep" and "the distance" at once -- so it is neither, and not in their base.
        bo1 = await self.encounter(0, 2, round_number=1, best_of=1, scores=[1, 0])
        await self.set(bo1, closeness=None)
        async with self.Session() as s:
            data = await encounter_service.get_insights_data(s, self.params(status="live"))
            read = await _uncached(flows_service.get_encounters_insights, s, self.params())

        self.assertEqual(4, data["completed"])
        self.assertAlmostEqual((0.8 + 0.5 + 1.0) / 3, data["avg_closeness"])
        self.assertEqual([(2, 0, 2), (2, 1, 1), (1, 0, 1)], data["score_lines"])
        self.assertEqual((3, 2, 1), (data["multi_map"], data["sweeps"], data["went_distance"]))
        self.assertEqual((3, 2, 1), (read.multi_map, read.sweeps, read.went_distance))
        self.assertEqual([("playoffs", 3), ("groups", 1)], data["stage_kinds"])
        self.assertEqual([], data["hot_maps"])
        self.assertIsNone(data["avg_series_seconds"])
        histogram = {round(start, 1): count for start, _, count in data["closeness_histogram"]}
        self.assertEqual({0.5: 1, 0.8: 1, 0.9: 1}, {start: count for start, count in histogram.items() if count})
        self.assertEqual(10, len(data["closeness_histogram"]))
        # A bucket's bounds filter the list to exactly what it counted.
        for start, end, count in data["closeness_histogram"]:
            with self.subTest(start=start):
                self.assertEqual(count, len(await self.ids(status="completed", closeness_min=start, closeness_max=end)))

        self.assertEqual([self.group, self.semi_one, self.semi_two], [row.id for row in read.closest])
        self.assertEqual(self.tournament_id, read.closest[0].tournament.id)
        self.assertEqual("Groups", read.closest[0].stage.name)
        self.assertEqual(["t1", "t2"], [seat.team.name for seat in read.closest[0].teams])

    async def test_a_saved_view_name_and_count_are_capped(self) -> None:
        async def save(name: str) -> None:
            async with self.Session() as s:
                await encounter_service.create_saved_view(
                    s, workspace_id=self.workspace_id, auth_user_id=self.auth_user_id, name=name, filters={}
                )

        await save("Finals")
        with self.assertRaises(BaseAPIException) as taken:
            await save("Finals")
        self.assertEqual((409, ["saved_view_exists"]), (taken.exception.status_code, _codes(taken.exception)))

        for index in range(1, SAVED_VIEW_LIMIT):
            await save(f"view {index}")
        with self.assertRaises(BaseAPIException) as full:
            await save("one too many")
        self.assertEqual((409, ["saved_view_limit"]), (full.exception.status_code, _codes(full.exception)))

    def test_a_saved_view_under_the_retired_order_reads_as_the_upcoming_segment(self) -> None:
        filters = schemas.EncounterFiltersRead.model_validate(
            {"sort": "upcoming", "tournament_id": 7, "is_final": True}
        )
        self.assertEqual(
            ("date", "upcoming", 7, True), (filters.sort, filters.status, filters.tournament_id, filters.is_final)
        )


class PageStatementTests(EncounterLayerCase):
    """A page's serialization batches every per-row read: the statement count does not grow with its size."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await _date_the_tournament(self)
        for first, second in ((0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)):
            encounter_id = await self.encounter(first, second)
            async with self.Session() as s:
                encounter = await s.get_one(Encounter, encounter_id)
                await encounter_game_service.open_game(s, encounter, position=1)
                await s.commit()
        self.statements: list[str] = []
        sa_event.listen(self.engine.sync_engine, "before_cursor_execute", self._record)

    async def asyncTearDown(self) -> None:
        sa_event.remove(self.engine.sync_engine, "before_cursor_execute", self._record)
        await super().asyncTearDown()

    def _record(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(statement)

    async def statements_for(self, per_page: int) -> int:
        params = schemas.EncounterSearchParams(
            per_page=per_page, tournament_id=self.tournament_id, entities=list(_PAGE_ENTITIES)
        )
        async with self.Session() as s:
            self.statements.clear()
            page = await _uncached(flows_service.get_all_encounters, s, params)
            count = len(self.statements)
        self.assertEqual(per_page, len(page.results))
        self.assertTrue(all(len(row.games) == 1 and row.stage is not None for row in page.results))
        return count

    async def test_a_page_costs_the_same_statements_at_any_size(self) -> None:
        self.assertEqual(await self.statements_for(2), await self.statements_for(6))
