"""A member who played for two teams in one tournament counts once (spec §11.2, §11.4). Needs the test Postgres.

m0 plays for team0, then team1 (final, 1st); m3 plays for team2, then team3 (final, 3rd); m1 is team2's, m2 team3's.
team0 also shows 1st, so a team-grain read would count m0 twice.
"""

from __future__ import annotations

import sqlalchemy as sa

from shared.core import enums, pagination
from shared.division_grid import DEFAULT_GRID
from shared.models.encounter import Encounter
from shared.models.tournament import Player, Standing, Tournament
from shared.services.encounter import participants
from shared.services.participant_result import write_participant_results
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.services.statistics.queries import StatisticsQueries
from src.services.user.queries.compare import UserCompareQueries
from src.services.user.queries.encounters import UserEncounterQueries
from src.services.user.queries.overview import UserOverviewQueries
from src.services.user.queries.profile import UserProfileQueries

OW = "overwatch"


class TwoTeamMemberReadsTests(EncounterWriterCase):
    slot_count = 4

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            for member, team in (
                ("m0", "team0"),
                ("m0", "team1"),
                ("m1", "team2"),
                ("m3", "team2"),
                ("m3", "team3"),
                ("m2", "team3"),
            ):
                s.add(
                    Player(
                        tournament_id=self.ids["t"],
                        team_id=self.ids[team],
                        workspace_member_id=self.ids[member],
                        name=f"{member}-{team}",
                        rank=3000,
                        is_substitution=False,
                    )
                )
                await s.flush()
            encounter = await self.encounter(s)
            for slot in range(1, 5):
                await participants.place_team(
                    s,
                    encounter,
                    slot=slot,
                    team_id=self.ids[f"team{slot - 1}"],
                    name=f"T{slot}",
                    seed=None,
                    members=(),
                )
            for team, overall in (("team0", 1), ("team1", 1), ("team2", 2), ("team3", 3)):
                s.add(
                    Standing(
                        tournament_id=self.ids["t"],
                        team_id=self.ids[team],
                        position=overall,
                        overall_position=overall,
                        matches=1,
                        points=0.0,
                    )
                )
            await s.execute(
                sa.update(Tournament)
                .where(Tournament.id == self.ids["t"])
                .values(status=enums.TournamentStatus.COMPLETED, is_finished=True)
            )
            await write_participant_results(s, self.ids["t"])
            await s.commit()

    async def _teams(self, user_index: int) -> list[int]:
        params = pagination.PaginationSortParams(page=1, per_page=-1, entities=["tournament"])
        async with self.Session() as s:
            teams, _ = await UserProfileQueries.of(OW).get_teams(
                s, self.users[user_index], params=params, workspace_id=self.ids["ws"]
            )
        return [team.id for team in teams]

    async def test_get_teams_lists_one_team_per_tournament(self) -> None:
        self.assertEqual([self.ids["team1"]], await self._teams(0))
        self.assertEqual([self.ids["team3"]], await self._teams(3))

    async def test_the_tournament_history_lists_the_final_team_once(self) -> None:
        async with self.Session() as s:  # the history reads duel seats only: one duel for each pair of teams
            for pair in ((0, 1), (2, 3)):
                duel = Encounter(
                    workspace_id=self.ids["ws"],
                    discipline="overwatch",
                    tournament_id=self.ids["t"],
                    scoring_rule_id=self.ids["rule"],
                    name="duel",
                    slot_count=2,
                    best_of=1,
                    status=enums.EncounterStatus.OPEN,
                )
                s.add(duel)
                await s.flush()
                for slot, team in enumerate(pair, start=1):
                    await participants.place_team(
                        s, duel, slot=slot, team_id=self.ids[f"team{team}"], name=f"T{team}", seed=None, members=()
                    )
            await s.commit()
            queries = UserProfileQueries.of(OW)
            for user_index, final_team in ((0, "team1"), (3, "team3")):
                rows = await queries.get_tournaments_with_stats(s, self.users[user_index], self.ids["ws"])
                self.assertEqual([self.ids[final_team]], [row[0].id for row in rows])

    async def test_placements_are_the_member_result(self) -> None:
        async with self.Session() as s:
            queries = UserProfileQueries.of(OW)
            self.assertEqual({self.ids["t"]: 1}, await queries.get_placements(s, self.users[0], self.ids["ws"]))
            self.assertEqual({self.ids["t"]: 3}, await queries.get_placements(s, self.users[3], self.ids["ws"]))

    async def test_overview_averages_count_the_tournament_once(self) -> None:
        async with self.Session() as s:
            averages = await UserOverviewQueries.of(OW).get_overview_averages(
                s, [self.users[0], self.users[3]], workspace_id=self.ids["ws"]
            )
        self.assertEqual((1.0, 1), (float(averages[self.users[0]][0]), averages[self.users[0]][4]))
        # A team-grain average would be (2 + 3) / 2 = 2.5 with best 2.
        self.assertEqual((3.0, 3), (float(averages[self.users[3]][0]), averages[self.users[3]][4]))

    async def test_compare_average_placement_counts_the_tournament_once(self) -> None:
        query = UserCompareQueries.of(OW)._compare_metrics_query_v2(
            user_ids=[self.users[3]], workspace_id=self.ids["ws"], grid=DEFAULT_GRID
        )
        async with self.Session() as s:
            row = (await s.execute(query)).mappings().one()
        self.assertEqual(3.0, float(row["avg_placement"]))

    async def test_a_title_counts_once(self) -> None:
        params = pagination.PaginationSortParams(per_page=100, sort="value", order="desc")
        async with self.Session() as s:
            rows, _ = await StatisticsQueries.of(OW).get_top_champions(s, params, workspace_id=self.ids["ws"])
        self.assertEqual({self.users[0]: 1}, {user.id: value for user, value in rows})

    async def test_the_single_row_lookup_is_the_final_team_row(self) -> None:
        async with self.Session() as s:
            player = await UserEncounterQueries.of(OW).get_player_by_user_and_tournament(
                s, self.users[0], self.ids["t"]
            )
        self.assertEqual(self.ids["team1"], player.team_id)
