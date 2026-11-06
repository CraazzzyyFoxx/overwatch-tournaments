"""User reads bound to one game never mix another game's rows (P7 8b review, findings 2, 3, 5).

Real PostgreSQL, one rolled-back transaction. Users a, b, c in one workspace that runs both games:

- Overwatch: T1 (a+b beat c 2-1), T2 (a+b beat c 3-0) — a and b share two tournaments; everyone played two.
- League: L1 (a+b lose to c 0-2), L2 (c alone) — c played two, a and b one.
- Achievements: an Overwatch rule earned by b, a League rule earned by c.

A read that mixes games shows a's all-workspaces maps as 5-3 (not 5-1), b as a teammate across three tournaments,
c's League award in the Overwatch count, or the cached Overwatch tournaments order on the League board.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, pagination
from shared.division_grid import DEFAULT_GRID
from shared.models.achievements.achievement import AchievementEvaluationResult, AchievementRule
from shared.testing import create_test_async_engine, ensure_test_postgres
from src import schemas
from src.services.achievement_reads.service import achievements as achievement_service
from src.services.user.queries.overview import UserOverviewQueries
from src.services.user.queries.profile import UserProfileQueries
from src.services.user.service import UserService
from tests.encounter_seed import seed_encounter, seed_scoring_rule

OW, LOL = "overwatch", "lol"


class UserReadsOneGameTest(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        self.tag = uuid.uuid4().hex[:10]
        self.ws = models.Workspace(slug=f"one-{self.tag}", name=f"one-{self.tag}", disciplines_enabled=[OW, LOL])
        self.session.add(self.ws)
        await self.session.flush()
        self.users: dict[str, models.User] = {}
        self.members: dict[str, models.WorkspaceMember] = {}
        for key in ("a", "b", "c"):
            user = models.User(name=f"zz{self.tag}-{key}")
            self.session.add(user)
            await self.session.flush()
            member = models.WorkspaceMember(workspace_id=self.ws.id, player_id=user.id)
            self.session.add(member)
            await self.session.flush()
            self.users[key], self.members[key] = user, member
        self.rule_id = await seed_scoring_rule(self.session, self.ws.id)
        self.tournaments: dict[str, models.Tournament] = {}

        await self._tournament(OW, "t1", [("a", "b")], ("c",), (2, 1))
        await self._tournament(OW, "t2", [("a", "b")], ("c",), (3, 0))
        await self._tournament(LOL, "l1", [("a", "b")], ("c",), (0, 2))
        await self._tournament(LOL, "l2", [], ("c",), None)
        await self._award(OW, "b")
        await self._award(LOL, "c")

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _tournament(
        self,
        discipline: str,
        label: str,
        home: list[tuple[str, ...]],
        away: tuple[str, ...],
        score: tuple[int, int] | None,
    ) -> None:
        day = datetime(2026, 1, 10, tzinfo=UTC)
        tournament = models.Tournament(
            workspace_id=self.ws.id,
            discipline=discipline,
            name=f"{label} {self.tag}",
            slug=f"{label}-{self.tag}",
            status=enums.TournamentStatus.COMPLETED,
            is_finished=True,
            start_date=day,
            end_date=day,
        )
        self.session.add(tournament)
        await self.session.flush()
        self.tournaments[label] = tournament
        teams = []
        for index, keys in enumerate([*home, away]):
            team = models.Team(
                tournament_id=tournament.id, name=f"{label}{index} {self.tag}", balancer_name=f"{label}{index}"
            )
            self.session.add(team)
            await self.session.flush()
            for key in keys:
                self.session.add(
                    models.Player(
                        tournament_id=tournament.id,
                        team_id=team.id,
                        workspace_member_id=self.members[key].id,
                        name=f"{key}{self.tag}",
                        rank=1000,
                        is_substitution=False,
                        is_newcomer=False,
                        is_newcomer_role=False,
                    )
                )
            teams.append(team)
        await self.session.flush()
        if score is not None:
            await seed_encounter(
                self.session, tournament, self.rule_id, list(zip(teams, score, strict=True)), name=f"{label} {self.tag}"
            )

    async def _award(self, discipline: str, key: str) -> None:
        rule = AchievementRule(
            workspace_id=self.ws.id,
            slug=f"r-{discipline}-{self.tag}",
            name=f"r-{discipline}",
            description_ru="ru",
            description_en="en",
            discipline=discipline,
            category="overall",
            scope="global",
            grain="user",
            condition_tree={},
            depends_on=[],
            enabled=True,
            rule_version=1,
        )
        self.session.add(rule)
        await self.session.flush()
        self.session.add(
            AchievementEvaluationResult(
                achievement_rule_id=rule.id,
                workspace_member_id=self.members[key].id,
                qualified_at=datetime.now(UTC),
                rule_version=1,
            )
        )
        await self.session.flush()

    def _ids(self, *keys: str) -> list[int]:
        return [self.users[key].id for key in keys]

    async def _board(self, discipline: str | None, sort: str) -> list[int]:
        params = schemas.UserOverviewParams(per_page=50, sort=sort, order="desc")
        users, _total = await UserOverviewQueries.of(discipline).get_overview_users(
            self.session, params, DEFAULT_GRID, workspace_id=self.ws.id
        )
        return [user.id for user in users]

    async def test_all_workspaces_profile_totals_and_teammates_are_one_games(self) -> None:
        profile = UserProfileQueries.of(OW)
        won, lost, _closeness = await profile.get_overall_statistics(self.session, self.users["a"].id, None)
        self.assertEqual((won, lost), (5, 1))

        rows, total = await profile.get_best_teammates(
            self.session, self.users["a"].id, pagination.PaginationSortParams(per_page=10, sort="id"), None
        )
        self.assertEqual(total, 1)
        teammate, winrate, tournaments, *_rest = rows[0]
        self.assertEqual(teammate.id, self.users["b"].id)
        self.assertEqual(tournaments, 2)
        self.assertAlmostEqual(float(winrate), 5 / 6)

    async def test_overview_achievement_counts_are_the_games_rules(self) -> None:
        ids = self._ids("a", "b", "c")
        self.assertEqual(
            await UserOverviewQueries.of(OW).get_overview_achievements_count(self.session, ids, self.ws.id),
            {self.users["b"].id: 1},
        )
        self.assertEqual(
            await UserOverviewQueries.of(LOL).get_overview_achievements_count(self.session, ids, self.ws.id),
            {self.users["c"].id: 1},
        )
        # The unfiltered sort reads the same one-game aggregate.
        self.assertEqual(await self._board(OW, "achievements_count"), self._ids("b", "a", "c"))
        self.assertEqual(await self._board(LOL, "achievements_count"), self._ids("c", "a", "b"))

    async def test_cached_overview_order_is_per_game(self) -> None:
        # Same workspace, sort and direction: the League board is its own cached order, not Overwatch's.
        self.assertEqual(await self._board(OW, "tournaments_count"), self._ids("a", "b", "c"))
        self.assertEqual(await self._board(LOL, "tournaments_count"), self._ids("c", "a", "b"))

    async def test_tournament_stats_carry_the_tournaments_owner_scope(self) -> None:
        read = await UserService.of(LOL).get_tournament_with_stats(
            self.session, self.users["a"].id, self.tournaments["l1"].id, grid=DEFAULT_GRID
        )
        self.assertEqual((read.workspace_id, read.discipline), (self.ws.id, LOL))

    async def test_profile_achievements_list_only_the_games_rules_earned_and_locked(self) -> None:
        async def slugs(key: str, discipline: str | None) -> dict[str, int]:
            rows = await achievement_service.get_user_achievements(
                self.session,
                self.users[key].id,
                [],
                workspace_id=self.ws.id,
                include_locked=True,
                discipline=discipline,
            )
            return {row.slug: row.count for row in rows}

        ow_rule, lol_rule = f"r-{OW}-{self.tag}", f"r-{LOL}-{self.tag}"
        # b earned the Overwatch rule: its League profile shows only League's (locked) rule, never the OW one.
        self.assertEqual(await slugs("b", LOL), {lol_rule: 0})
        self.assertEqual(await slugs("b", OW), {ow_rule: 1})
        # c earned the League rule; its Overwatch profile lists Overwatch's rule locked.
        self.assertEqual(await slugs("c", OW), {ow_rule: 0})
        self.assertEqual(await slugs("c", LOL), {lol_rule: 1})
        # Without a game (the admin person hub) every game's rules are listed, as before.
        self.assertEqual(await slugs("b", None), {ow_rule: 1, lol_rule: 0})

    async def test_overview_without_a_game_reads_every_game(self) -> None:
        # a and b played T1, T2 and L1; c played all four: the tournaments of both games count.
        self.assertEqual(await self._board(None, "tournaments_count"), self._ids("c", "a", "b"))
        # b's Overwatch award and c's League award both count; a has none.
        self.assertEqual(await self._board(None, "achievements_count"), self._ids("b", "c", "a"))
        records = await UserOverviewQueries.of(None).get_overview_map_records(self.session, self._ids("a"), self.ws.id)
        # Overwatch 5-1 plus League 0-2, three decided encounters.
        self.assertEqual(records[self.users["a"].id], (5, 3, 3))

    async def test_overview_rows_name_the_games_played_and_carry_no_game_bound_fields(self) -> None:
        ids = self._ids("a", "b", "c")
        every_game = {user_id: [OW, LOL] for user_id in ids}
        # Both modes name every game the player played, in installed order.
        self.assertEqual(
            await UserOverviewQueries.of(None).get_overview_disciplines(self.session, ids, self.ws.id), every_game
        )
        self.assertEqual(
            await UserOverviewQueries.of(LOL).get_overview_disciplines(self.session, ids, self.ws.id), every_game
        )
        # Roles, divisions and characters belong to one game: there are none without one.
        unbound = UserOverviewQueries.of(None)
        self.assertEqual(await unbound.get_overview_role_divisions(self.session, ids, self.ws.id), {})
        self.assertEqual(await unbound.get_overview_top_heroes(self.session, ids, workspace_id=self.ws.id), {})

    async def test_overview_without_a_game_needs_no_grid_even_when_the_first_game_has_none(self) -> None:
        from src.core.workspace import resolve_workspace_context
        from src.services.user.service import _overview_role_divisions

        # League first and without a division grid in this workspace: a no-game read never asks for one (R13).
        self.ws.disciplines_enabled = [LOL, OW]
        await self.session.flush()
        ctx = await resolve_workspace_context(self.session, self.ws.id, discipline=None)
        self.assertIsNone(ctx.grid)

        unbound = UserOverviewQueries.of(None)
        params = schemas.UserOverviewParams(per_page=50, sort="tournaments_count", order="desc")
        users, _total = await unbound.get_overview_users(self.session, params, ctx.grid, workspace_id=ctx.id)
        self.assertEqual([user.id for user in users], self._ids("c", "a", "b"))
        # The rows' roles step: no roles without a game, so nothing is resolved on the absent grid.
        raw_roles = await unbound.get_overview_role_divisions(self.session, self._ids("c", "a", "b"), ctx.id)
        self.assertEqual(
            await _overview_role_divisions(
                self.session, raw_roles, grid=ctx.grid, normalizer=ctx.normalizer, workspace_id=ctx.id
            ),
            ({}, []),
        )
        _letters, total, _available = await unbound.get_catalog_users(
            self.session,
            role=None,
            divisions=[],
            has_logs=False,
            query=None,
            letter=None,
            per_letter=12,
            max_letters=27,
            grid=ctx.grid,
            workspace_id=ctx.id,
        )
        self.assertEqual(total, 3)
        stats = await UserService.of(None).get_overview_stats(
            self.session, schemas.UserOverviewStatsQueryParams(), grid=ctx.grid, workspace_id=ctx.id
        )
        self.assertEqual(stats.total_players, 3)

    async def test_overview_stats_without_a_game_span_every_game_without_role_or_division_facets(self) -> None:
        stats = await UserService.of(None).get_overview_stats(
            self.session, schemas.UserOverviewStatsQueryParams(), grid=DEFAULT_GRID, workspace_id=self.ws.id
        )

        self.assertEqual(stats.total_players, 3)
        # a 3, b 3, c 4 finished tournaments across both games.
        self.assertEqual(stats.avg_tournaments_per_player, 3.3)
        self.assertEqual(stats.median_tournaments_per_player, 3.0)
        self.assertEqual(
            (stats.role_counts, stats.division_counts, stats.flex_count, stats.flex_declared_count), ({}, [], 0, 0)
        )

    async def test_profile_without_a_game_summarises_each_game_played(self) -> None:
        await self._tournament(LOL, "l3", [("a",)], ("c",), (1, 0))
        await self._tournament(LOL, "l4", [("b",)], ("c",), (0, 2))
        unbound = UserService.of(None)

        profile_a = await unbound.get_profile(
            self.session, self.users["a"].id, workspace_id=self.ws.id, grid=DEFAULT_GRID
        )
        # a: T1, T2 (Overwatch) and L1, L3 (League) -- a tie, which the installed order breaks.
        self.assertEqual([(game.discipline, game.tournaments_count) for game in profile_a.games], [(OW, 2), (LOL, 2)])
        # The header spans both games: four tournaments; Overwatch 5-1, L1 0-2, L3 1-0.
        self.assertEqual(profile_a.tournaments_count, 4)
        self.assertEqual((profile_a.maps_won, profile_a.maps_total), (6, 9))
        self.assertEqual({tournament.discipline for tournament in profile_a.tournaments}, {OW, LOL})
        # Roles and characters are one game's: none in the cross-game header.
        self.assertEqual((profile_a.roles, profile_a.character_statistics), ([], []))
        self.assertIsNone(profile_a.most_played_character)
        self.assertEqual(profile_a.characters_count, 0)

        profile_c = await unbound.get_profile(
            self.session, self.users["c"].id, workspace_id=self.ws.id, grid=DEFAULT_GRID
        )
        # c: League L1, L3, L4 outnumber Overwatch T1, T2 (L2 had no encounter: not a played event).
        self.assertEqual([(game.discipline, game.tournaments_count) for game in profile_c.games], [(LOL, 3), (OW, 2)])

    async def test_profile_without_a_game_needs_no_grid_even_when_the_first_game_has_none(self) -> None:
        from src.core.workspace import resolve_workspace_context

        # League first and without a division grid here: the cross-game profile never asks for one (R13).
        self.ws.disciplines_enabled = [LOL, OW]
        await self.session.flush()
        ctx = await resolve_workspace_context(self.session, self.ws.id, discipline=None)
        self.assertIsNone(ctx.grid)

        profile = await UserService.of(None).get_profile(
            self.session, self.users["a"].id, workspace_id=ctx.id, grid=ctx.grid
        )
        # a: T1, T2 (Overwatch) and L1 (League); League's card reads its roles on League's own in-code ladder.
        self.assertEqual(profile.tournaments_count, 3)
        self.assertEqual([(game.discipline, game.tournaments_count) for game in profile.games], [(OW, 2), (LOL, 1)])
        self.assertEqual([(r.division, r.division_grid_version) for r in profile.games[1].roles], [(21, None)])

    async def test_profile_across_communities_reads_a_games_roles_on_their_own_grid_without_a_system_grid(self) -> None:
        from src.core.workspace import get_division_grid

        # Across communities League falls back to its own ladder, never Overwatch's ...
        self.assertEqual((await get_division_grid(self.session, None, discipline=LOL)).tiers[0].slug, "challenger")
        # ... but L1 pinned a League grid of this community, which a's League role is read on.
        version = models.DivisionGridVersion(
            grid=models.DivisionGrid(workspace_id=self.ws.id, discipline=LOL, slug=f"lol-{self.tag}", name="lol"),
            version=1,
            label="lol",
            status="published",
            tiers=[
                models.DivisionGridTier(
                    slug="lol", number=9, name="lol", sort_order=0, rank_min=0, rank_max=None, icon_url=""
                )
            ],
        )
        self.session.add(version)
        await self.session.flush()
        self.tournaments["l1"].division_grid_version_id = version.id
        await self.session.flush()

        profile = await UserService.of(None).get_profile(self.session, self.users["a"].id, workspace_id=None, grid=None)

        league = next(game for game in profile.games if game.discipline == LOL)
        self.assertEqual(
            [(role.division, role.division_grid_version and role.division_grid_version.id) for role in league.roles],
            [(9, version.id)],
        )

    async def test_profile_in_one_game_has_no_game_list_and_tags_its_tournaments(self) -> None:
        profile = await UserService.of(OW).get_profile(
            self.session, self.users["c"].id, workspace_id=self.ws.id, grid=DEFAULT_GRID
        )

        self.assertEqual(profile.games, [])
        self.assertEqual([tournament.discipline for tournament in profile.tournaments], [OW, OW])
