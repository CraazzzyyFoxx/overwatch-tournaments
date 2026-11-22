"""A player of an individual Swiss stage has no ``tournament.player``: the profile reads find them through the
team-less seat's roster snapshot. Needs the test Postgres.

One team-less lobby, 2:0: m0 (tank) beats m1 (support) and m3, who has no individual Swiss row at all. m2 sits on
m0's seat as a substitute, which never counts. The lobby's one observed map is logged.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, pagination
from shared.core.errors import ApiHTTPException
from shared.division_grid import DEFAULT_GRID
from shared.models.encounter import Encounter, EncounterTeam
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import PlayerStanding, Stage, Tournament
from shared.services.encounter import participants
from shared.services.encounter.participants import MemberSnapshot
from shared.tests.encounter_writer_case import EncounterWriterCase
from src import schemas
from src.services.map.service import maps
from src.services.statistics.queries import StatisticsQueries
from src.services.user.queries.profile import UserProfileQueries
from src.services.user.service import UserService
from tests.encounter_seed import add_observed_game

OW = "overwatch"
#: ``(member, rank, substitute)`` per seat, with the seat's ``(score, placement)``.
LOBBY = (
    ((("m0", 3100, False), ("m2", 2000, True)), (2.0, 1)),
    ((("m1", 2900, False), ("m3", 2500, False)), (0.0, 2)),
)


async def seat_lobby(session: AsyncSession, encounter: Encounter, ids: dict[str, int], lobby) -> None:
    """Seat ``lobby`` (``LOBBY``'s shape) in ``encounter`` as team-less seats and set their result."""
    for slot, (seated, (score, placement)) in enumerate(lobby, start=1):
        await participants.place_team(
            session,
            encounter,
            slot=slot,
            team_id=None,
            name=f"Lobby {encounter.id}-{slot}",
            seed=None,
            members=[
                MemberSnapshot(
                    workspace_member_id=ids[member],
                    display_name=member,
                    rank=rank,
                    is_substitute=substitute,
                    roles=(),
                )
                for member, rank, substitute in seated
            ],
        )
        await session.execute(
            sa.update(EncounterTeam)
            .where(EncounterTeam.encounter_id == encounter.id, EncounterTeam.slot == slot)
            .values(score=score, placement=placement)
        )


class IndividualSwissProfileReadsTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.ids["t"],
                name="Qualifications",
                stage_type=enums.StageType.INDIVIDUAL_SWISS,
                scoring_rule_id=self.ids["rule"],
            )
            s.add(stage)
            await s.flush()
            encounter = await self.encounter(s)
            await seat_lobby(s, encounter, self.ids, LOBBY)
            game_map = models.CatalogEntity(
                discipline=OW, kind="map", slug=f"iswiss-{self.ids['t']}", name="Lobby map", attrs={}
            )
            s.add(game_map)
            await s.flush()
            self.map_id = game_map.id
            await s.run_sync(
                lambda db: add_observed_game(
                    db,
                    encounter_id=self.ids["e"],
                    map_entity_id=self.map_id,
                    position=1,
                    duration_s=600,
                    scores=(1, 0),
                    observations=[
                        (self.ids["m0"], 1, None, enums.LogStatsName.ImpactRank, 1.0),
                        (self.ids["m1"], 2, None, enums.LogStatsName.ImpactRank, 2.0),
                        (self.ids["m3"], 2, None, enums.LogStatsName.ImpactRank, 4.0),
                    ],
                )
            )
            for member, role, start_rank, wins, losses in (("m0", "tank", 3100, 1, 0), ("m1", "support", 2900, 0, 1)):
                s.add(
                    PlayerStanding(
                        tournament_id=self.ids["t"],
                        stage_id=stage.id,
                        workspace_member_id=self.ids[member],
                        display_name=member,
                        role=role,
                        start_rank=start_rank,
                        rank=start_rank,
                        wins=wins,
                        losses=losses,
                        matches_played=1,
                    )
                )
            await s.commit()
        self.queries = UserProfileQueries.of(OW)
        self.service = UserService.of(OW)

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:  # the workspace's matches name the map: they go first
            await s.execute(sa.delete(Workspace).where(Workspace.id.in_(self.workspaces)))
            await s.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.id == self.map_id))
            await s.commit()
        await super().asyncTearDown()

    async def test_the_tournaments_tab_lists_the_tournament_without_a_team(self) -> None:
        async with self.Session() as s:
            read = await self.service.get_tournaments(s, self.users[0], workspace_id=self.ids["ws"], grid=DEFAULT_GRID)
        [row] = read.results
        self.assertEqual(
            (self.ids["t"], None, None, [], "tank", 2, 0, 1, 0, 0),
            (row.id, row.team_id, row.team, row.players, row.role.role, row.maps_won, row.maps_lost)
            + (row.won, row.lost, row.draw),
        )
        # A live stage has no final result: nothing for the placement timeline to read as a finish.
        self.assertEqual((None, 0), (row.placement, row.count_teams))

    async def test_the_profile_counts_the_tournament_and_its_maps(self) -> None:
        async with self.Session() as s:
            profile = await self.service.get_profile(s, self.users[0], workspace_id=self.ids["ws"], grid=DEFAULT_GRID)
        self.assertEqual((1, 2, 2), (profile.tournaments_count, profile.maps_total, profile.maps_won))
        self.assertEqual([self.ids["t"]], [tournament.id for tournament in profile.tournaments])
        self.assertEqual([("tank", 1, 2)], [(r.role.role, r.tournaments, r.maps) for r in profile.roles])

    async def test_the_card_of_an_all_loss_run_counts_its_maps(self) -> None:
        async with self.Session() as s:
            card = await self.service.get_tournament_with_stats(s, self.users[1], self.ids["t"], grid=DEFAULT_GRID)
        self.assertEqual(("support", 2, 0), (card.role.role, card.maps, card.maps_won))
        self.assertEqual((None, None), (card.group_placement, card.playoff_placement))

    async def test_a_seat_without_an_individual_swiss_row_still_gets_the_card(self) -> None:
        async with self.Session() as s:
            card = await self.service.get_tournament_with_stats(s, self.users[3], self.ids["t"], grid=DEFAULT_GRID)
        self.assertEqual((None, None, 2), (card.role, card.division, card.maps))

    async def test_a_substitute_has_neither_history_nor_card(self) -> None:
        async with self.Session() as s:
            rows = await self.queries.get_tournaments_with_stats(s, self.users[2], self.ids["ws"])
            played = await self.queries.get_teamless_tournaments(s, self.users[2], self.ids["ws"])
            with self.assertRaises(ApiHTTPException) as raised:
                await self.service.get_tournament_with_stats(s, self.users[2], self.ids["t"], grid=DEFAULT_GRID)
        self.assertEqual(([], [], 404), (list(rows), list(played), raised.exception.status_code))

    async def test_the_winrate_ranks_every_lobby_player(self) -> None:
        async with self.Session() as s:
            tournament = await s.get_one(Tournament, self.ids["t"])
            row = await StatisticsQueries.of(OW).get_tournament_winrate(s, tournament, self.users[1])
        # m0 1.0 first; m1 and m3 share 0.0 second.
        self.assertEqual((self.users[1], 0, 2, 2), (row[0], float(row[1]), row[2], row[3]))

    async def test_the_maps_tab_counts_the_lobby_map(self) -> None:
        params = schemas.UserMapsSearchParams(per_page=100, sort="count", order="desc")
        async with self.Session() as s:
            winner = await maps.get_top_user(s, self.users[0], params, discipline=OW, workspace_id=self.ids["ws"])
            loser = await maps.get_top_user(s, self.users[1], params, discipline=OW, workspace_id=self.ids["ws"])
        self.assertEqual(
            [(self.map_id, 1, 1, 0), (self.map_id, 1, 0, 1)],
            [(row.map.id, row.count, row.win, row.loss) for read in (winner, loser) for row in read.results],
        )

    async def test_the_matches_sidebar_names_the_lobby_opponent(self) -> None:
        async with self.Session() as s:
            summary = await self.service.get_matches_summary(s, self.users[1], self.ids["ws"])
        self.assertEqual(
            [(f"Lobby {self.ids['e']}-1", 0, 1, 0)], [(o.name, o.wins, o.losses, o.draws) for o in summary.opponents]
        )

    async def test_the_result_filter_finds_the_lobby(self) -> None:
        params = pagination.PaginationSortParams(per_page=10, sort="played_at", order="desc")
        async with self.Session() as s:
            totals = [
                (
                    await self.service.get_encounters_by_user(
                        s, self.users[1], params, self.ids["ws"], result_filter=result
                    )
                ).total
                for result in ("loss", "win")
            ]
        self.assertEqual([1, 0], totals)

    async def test_a_lobby_teammate_across_two_tournaments_is_a_best_teammate(self) -> None:
        async with self.Session() as s:  # m1 and m3 share a lobby again, and win it 2:1
            other = Tournament(
                workspace_id=self.ids["ws"],
                discipline=OW,
                name="Second",
                slug=f"iswiss-second-{self.ids['t']}",
                status=enums.TournamentStatus.LIVE,
            )
            s.add(other)
            await s.flush()
            encounter = Encounter(
                workspace_id=self.ids["ws"],
                discipline=OW,
                tournament_id=other.id,
                scoring_rule_id=self.ids["rule"],
                name="Second lobby",
                slot_count=2,
                best_of=3,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(encounter)
            await s.flush()
            together = (("m1", 2900, False), ("m3", 2500, False))
            await seat_lobby(s, encounter, self.ids, ((together, (2.0, 1)), ((), (1.0, 2))))
            await s.commit()
            read = await self.service.get_best_teammates(
                s, self.users[1], pagination.PaginationSortParams(per_page=10, sort="winrate", order="desc")
            )
        # Maps 0:2 then 2:1; one logged map together, where m3 placed 4th.
        self.assertEqual(
            [(self.users[3], 0.4, 2, 1, 4.0)],
            [
                (t.user.id, t.winrate, t.tournaments, t.maps, t.stats[enums.LogStatsName.ImpactRank])
                for t in read.results
            ],
        )
