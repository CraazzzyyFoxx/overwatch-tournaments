"""The /statistics almanac reads (players table, records, maps) on real PostgreSQL, one rolled-back transaction.

Every read is scoped to this test's own workspace, so the shared test database's other rows never leak in.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.testing import create_test_async_engine, ensure_test_postgres
from src import schemas
from src.services.statistics.service import statistics
from tests.encounter_seed import seed_encounter, seed_scoring_rule

OW = "overwatch"
DAY = datetime(2025, 1, 1, tzinfo=UTC)


class StatisticsAlmanacTest(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        self.tag = uuid.uuid4().hex[:10]
        self.ws = models.Workspace(slug=f"alm-{self.tag}", name=f"alm-{self.tag}", disciplines_enabled=[OW])
        self.session.add(self.ws)
        await self.session.flush()
        self.rule_id = await seed_scoring_rule(self.session, self.ws.id)
        self.members: dict[str, models.WorkspaceMember] = {}
        self.users: dict[str, models.User] = {}

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    # ---- seeding ----------------------------------------------------------------

    async def _member(self, key: str) -> models.WorkspaceMember:
        if key not in self.members:
            user = models.User(name=f"zz{self.tag}-{key}")
            self.session.add(user)
            await self.session.flush()
            member = models.WorkspaceMember(workspace_id=self.ws.id, player_id=user.id)
            self.session.add(member)
            await self.session.flush()
            self.users[key], self.members[key] = user, member
        return self.members[key]

    async def _tournament(self, label: str, start: datetime = DAY) -> models.Tournament:
        tournament = models.Tournament(
            workspace_id=self.ws.id,
            discipline=OW,
            name=f"{label} {self.tag}",
            slug=f"{label}-{self.tag}",
            status=enums.TournamentStatus.COMPLETED,
            is_finished=True,
            start_date=start,
            end_date=start + timedelta(days=1),
        )
        self.session.add(tournament)
        await self.session.flush()
        return tournament

    async def _team(self, tournament: models.Tournament, name: str, *roster: tuple[str, int | None]) -> models.Team:
        team = models.Team(tournament_id=tournament.id, name=f"{name} {self.tag}", balancer_name=name)
        self.session.add(team)
        await self.session.flush()
        for key, rank in roster:
            member = await self._member(key)
            self.session.add(
                models.Player(
                    tournament_id=tournament.id,
                    team_id=team.id,
                    workspace_member_id=member.id,
                    name=f"{key}{self.tag}",
                    rank=rank,
                    is_substitution=False,
                    is_newcomer=False,
                    is_newcomer_role=False,
                )
            )
        await self.session.flush()
        return team

    async def _series(
        self, tournament: models.Tournament, home: models.Team, away: models.Team, score: tuple[int, int], **columns
    ) -> models.Encounter:
        return await seed_encounter(
            self.session,
            tournament,
            self.rule_id,
            [(home, score[0]), (away, score[1])],
            name=f"{home.name} vs {away.name}",
            **columns,
        )

    async def _title(self, tournament: models.Tournament, team: models.Team) -> None:
        self.session.add(
            models.Standing(
                tournament_id=tournament.id, team_id=team.id, position=1, overall_position=1, matches=1, points=3.0
            )
        )
        members = await self.session.scalars(
            sa.select(models.Player.workspace_member_id).where(
                models.Player.team_id == team.id, models.Player.is_substitution.is_(False)
            )
        )
        self.session.add_all(
            models.ParticipantResult(
                tournament_id=tournament.id,
                workspace_member_id=member_id,
                final_team_id=team.id,
                placement=1,
                field_size=2,
            )
            for member_id in members
        )
        await self.session.flush()

    async def _duel(self, label: str, home: str, away: str, score: tuple[int, int], title: str | None) -> None:
        tournament = await self._tournament(label)
        teams = {key: await self._team(tournament, f"{label}{key}", (key, 1000)) for key in (home, away)}
        await self._series(tournament, teams[home], teams[away], score)
        if title is not None:
            await self._title(tournament, teams[title])

    async def _entity(self, kind: str, name: str, parent: models.CatalogEntity | None = None) -> models.CatalogEntity:
        entity = models.CatalogEntity(
            discipline=OW,
            kind=kind,
            slug=f"{name}-{self.tag}",
            name=f"{name} {self.tag}",
            parent_id=parent.id if parent is not None else None,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    # ---- players ------------------------------------------------------------------

    async def _players(self, **query: object) -> list[schemas.PlayerLeaderboardRow]:
        page = await statistics.get_players(
            self.session, schemas.PlayerLeaderboardQueryParams(**query), discipline=OW, workspace_id=self.ws.id
        )
        self.assertEqual(page.total, len(page.results))
        return page.results

    async def _seed_players(self) -> None:
        # Titles a 2, b 1, c 1, d 0; tournaments a 4, b 3, c 2, d 1; maps a 5-5, b 4-3, c 3-3, d 1-2.
        await self._duel("t1", "a", "b", (2, 0), title="a")
        await self._duel("t2", "a", "c", (2, 1), title="a")
        await self._duel("t3", "a", "b", (0, 2), title="b")
        await self._duel("t4", "a", "c", (1, 2), title="c")
        await self._duel("t5", "d", "b", (1, 2), title=None)

    async def test_players_share_a_rank_on_a_tie_and_a_search_never_renumbers(self) -> None:
        await self._seed_players()
        rows = await self._players()
        expected = [(self.users[key].id, rank) for key, rank in zip("abcd", (1, 2, 2, 4), strict=True)]
        self.assertEqual([(row.id, row.rank) for row in rows], expected)
        # Inside a shared rank the better win rate leads: b (4-3) before c (3-3).
        a, b, c, d = rows
        self.assertEqual((a.titles, a.tournaments, a.maps_won, a.maps_lost, a.winrate), (2, 4, 5, 5, 0.5))
        self.assertAlmostEqual(b.winrate, 4 / 7)
        self.assertEqual([row.low_sample for row in rows], [False, True, True, True])

        (found,) = await self._players(query=f"{self.tag}-D")
        self.assertEqual((found.id, found.rank, found.titles), (self.users["d"].id, 4, 0))

    async def test_the_winrate_sort_ranks_only_players_above_the_low_sample_threshold(self) -> None:
        await self._seed_players()
        (only,) = await self._players(sort="winrate")
        self.assertEqual((only.id, only.rank, only.low_sample), (self.users["a"].id, 1, False))
        # The other sorts keep the low-sample players.
        self.assertEqual(len(await self._players(sort="tournaments", order="asc")), 4)

    # ---- records ------------------------------------------------------------------

    async def _records(self, discipline: str | None = OW) -> dict[str, schemas.StatRecord]:
        result = await statistics.get_records(self.session, discipline=discipline, workspace_id=self.ws.id)
        return {record.code: record for record in result.records}

    async def test_upsets_and_underdogs_compare_sr_only_within_their_own_tournament(self) -> None:
        # Low scale: A (100) beats B (200) -- half the loser's SR.
        low = await self._tournament("low", DAY)
        a = await self._team(low, "A", ("u1", 100), ("u2", 100))
        b = await self._team(low, "B", ("u3", 200), ("u4", 200))
        upset = await self._series(low, a, b, (2, 1))
        await self._title(low, b)
        # High scale: C (2000) beats D (3000) -- a bigger gap, a smaller share -- and wins the title as the weakest
        # of three rated rosters. F has an unranked player: no average, so its "upset" of D never counts.
        high = await self._tournament("high", DAY + timedelta(days=30))
        c = await self._team(high, "C", ("u5", 2000), ("u6", 2000))
        d = await self._team(high, "D", ("u7", 3000), ("u8", 3000))
        await self._team(high, "E", ("u9", 2500), ("u10", 2500))
        f = await self._team(high, "F", ("u11", None), ("u12", 100))
        await self._series(high, c, d, (2, 0))
        await self._series(high, f, d, (2, 0))
        await self._title(high, c)

        records = await self._records()
        biggest = records["biggest_upset"]
        self.assertEqual((biggest.team.id, biggest.opponent.id, biggest.tournament.id), (a.id, b.id, low.id))
        self.assertEqual(
            (biggest.value, biggest.relative, biggest.score, biggest.encounter_id), (100, 0.5, (2, 1), upset.id)
        )
        underdog = records["underdog_champion"]
        self.assertEqual((underdog.team.id, underdog.value, underdog.of_total), (c.id, 3, 3))

    async def test_a_loss_ends_a_win_streak_across_tournaments(self) -> None:
        first = await self._tournament("s1", DAY)
        second = await self._tournament("s2", DAY + timedelta(days=7))
        mine = await self._team(first, "S", ("s", 1000))
        rival = await self._team(first, "O", ("o", 1000))
        for hour, score in enumerate([(2, 0), (2, 0), (0, 2), (2, 0)]):
            await self._series(first, mine, rival, score, ended_at=DAY + timedelta(hours=hour))
        mine_again = await self._team(second, "S2", ("s", 1000))
        rival_again = await self._team(second, "O2", ("o2", 1000))
        late = DAY + timedelta(days=7)
        for hour in range(2):
            await self._series(second, mine_again, rival_again, (2, 1), ended_at=late + timedelta(hours=hour))

        streak = (await self._records(None))["win_streak"]
        self.assertEqual((streak.player.id, streak.value), (self.users["s"].id, 3))
        self.assertEqual((streak.started_at, streak.ended_at), (DAY + timedelta(hours=3), late + timedelta(hours=1)))

    async def test_a_record_without_data_is_omitted(self) -> None:
        self.assertEqual(await self._records(), {})
        tournament = await self._tournament("plain")
        strong = await self._team(tournament, "Strong", ("p", 2000))
        weak = await self._team(tournament, "Weak", ("q", 1000))
        await self._series(tournament, strong, weak, (2, 0))
        # No upset, title, final or parsed log: only the streak has data, in either game scope.
        self.assertEqual(list(await self._records()), ["win_streak"])
        self.assertEqual(list(await self._records(None)), ["win_streak"])

    # ---- maps ---------------------------------------------------------------------

    async def test_maps_count_official_games_else_parsed_maps_and_average_parsed_lengths(self) -> None:
        mode_x, mode_y = await self._entity("mode", "mx"), await self._entity("mode", "my")
        m1, m2 = await self._entity("map", "m1", mode_x), await self._entity("map", "m2", mode_x)
        m3, m4 = await self._entity("map", "m3", mode_y), await self._entity("map", "m4")
        tournament = await self._tournament("maps")
        home = await self._team(tournament, "H", ("h", 1000))
        away = await self._team(tournament, "W", ("w", 1000))

        def game(encounter: models.Encounter, position: int, entity: models.CatalogEntity) -> models.EncounterGame:
            return models.EncounterGame(
                encounter_id=encounter.id,
                position=position,
                map_id=entity.id,
                mode_id=entity.parent_id,
                state=enums.EncounterGameState.CONFIRMED,
                result_source=enums.EncounterGameResultSource.ADMIN,
                confirmed_at=DAY,
            )

        def parsed(encounter: models.Encounter, entity: models.CatalogEntity, seconds: float) -> models.StatsMatch:
            return models.StatsMatch(
                workspace_id=self.ws.id,
                discipline=OW,
                encounter_id=encounter.id,
                map_entity_id=entity.id,
                mode_entity_id=entity.parent_id,
                duration_s=seconds,
            )

        # Official games: M1, M1, M2. Its parsed M1 map is only a length, never a second count.
        official = await self._series(tournament, home, away, (2, 1))
        # No game rows (imported history): its parsed maps are the games.
        imported = await self._series(tournament, home, away, (2, 1))
        # An unfinished series counts nothing.
        live = await self._series(tournament, home, away, (0, 0), completed=False)
        self.session.add_all([game(official, 1, m1), game(official, 2, m1), game(official, 3, m2), game(live, 1, m3)])
        self.session.add_all(
            [
                parsed(official, m1, 600),
                parsed(imported, m2, 300),
                parsed(imported, m3, 900),
                parsed(imported, m4, 100),
            ]
        )
        await self.session.flush()

        result = await statistics.get_maps(self.session, discipline=OW, workspace_id=self.ws.id)
        self.assertEqual(result.total_games, 6)
        shape = [
            (
                mode.mode.id if mode.mode else None,
                mode.games,
                [(row.map.id, row.games, row.share, row.avg_duration_s) for row in mode.maps],
            )
            for mode in result.modes
        ]
        self.assertEqual(
            shape,
            [
                (mode_x.id, 4, [(m1.id, 2, 0.5, 600), (m2.id, 2, 0.5, 300)]),
                (mode_y.id, 1, [(m3.id, 1, 1.0, 900)]),
                (None, 1, [(m4.id, 1, 1.0, 100)]),
            ],
        )
