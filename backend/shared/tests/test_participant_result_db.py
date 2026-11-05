"""``tournament.participant_result`` writer and the member's tournament row (spec §4.7, §11.3, §11.4). Needs the test
Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.models.tournament import Player, Stage, Standing, Tournament
from shared.repository.participant_result import is_member_tournament_row
from shared.repository.stream import StreamTargetRepository
from shared.repository.tournament import PlayerRepository
from shared.services.participant_result import write_participant_results
from shared.tests.encounter_writer_case import EncounterWriterCase

PR = models.ParticipantResult


class _ResultCase(EncounterWriterCase):
    async def roster(self, s, member: str, team: str, *, substitute: bool = False) -> int:
        player = Player(
            tournament_id=self.ids["t"],
            formation_node_id=await s.scalar(
                sa.select(models.Team.formation_node_id).where(models.Team.id == self.ids[team])
            ),
            team_id=self.ids[team],
            workspace_member_id=self.ids[member],
            name=f"{member}-{team}",
            rank=3000,
            is_substitution=substitute,
        )
        s.add(player)
        await s.flush()
        return player.id

    async def formations(self, s, **teams: tuple[str, ...]) -> dict[str, int]:
        """A formation node per keyword (completed in keyword order) and its teams moved onto it; ``Player`` rows
        written afterwards for those teams carry the node."""
        now = datetime(2026, 11, 5, tzinfo=UTC)
        nodes: dict[str, int] = {}
        for index, (name, members) in enumerate(teams.items()):
            node = models.FlowNode(
                tournament_id=self.ids["t"],
                kind="formation",
                name=name,
                status="completed",
                config={"mode": "manual"},
                completed_at=now + timedelta(hours=index),
            )
            s.add(node)
            await s.flush()
            nodes[name] = node.id
            for team in members:
                await s.execute(
                    sa.update(models.Team).where(models.Team.id == self.ids[team]).values(formation_node_id=node.id)
                )
        return nodes

    async def stage(self, s, order: int) -> int:
        stage = Stage(
            tournament_id=self.ids["t"],
            scoring_rule_id=self.ids["rule"],
            name=f"S{order}",
            stage_type=enums.StageType.ROUND_ROBIN,
            order=order,
        )
        s.add(stage)
        await s.flush()
        return stage.id

    def standing(self, s, team: str, overall: int, *, stage_id: int | None = None) -> None:
        s.add(
            Standing(
                tournament_id=self.ids["t"],
                team_id=self.ids[team],
                stage_id=stage_id,
                position=max(overall, 1),
                overall_position=overall,
                matches=1,
                points=0.0,
            )
        )

    async def finish(self, s, finished: bool = True) -> None:
        status = enums.TournamentStatus.COMPLETED if finished else enums.TournamentStatus.LIVE
        await s.execute(
            sa.update(Tournament).where(Tournament.id == self.ids["t"]).values(status=status, is_finished=finished)
        )

    async def results(self, s) -> dict[int, tuple[int | None, int | None, int]]:
        rows = await s.execute(
            sa.select(PR.workspace_member_id, PR.final_team_id, PR.placement, PR.field_size).where(
                PR.tournament_id == self.ids["t"]
            )
        )
        return {member: (team, placement, size) for member, team, placement, size in rows.all()}

    def result(self, s, member: str, team: str) -> None:
        s.add(
            PR(
                tournament_id=self.ids["t"],
                workspace_member_id=self.ids[member],
                final_team_id=self.ids[team],
                placement=1,
                field_size=4,
            )
        )


class WriteParticipantResultsTests(_ResultCase):
    async def test_a_member_on_two_teams_gets_one_row_of_the_later_team(self) -> None:
        async with self.Session() as s:
            await self.roster(s, "m0", "team0")
            await self.roster(s, "m0", "team1")
            await self.roster(s, "m1", "team2")
            self.standing(s, "team0", 3)
            self.standing(s, "team1", 1)
            self.standing(s, "team2", 2)
            await self.finish(s)
            written = await write_participant_results(s, self.ids["t"])
            await s.commit()
            self.assertEqual(2, written)
            self.assertEqual(
                {self.ids["m0"]: (self.ids["team1"], 1, 4), self.ids["m1"]: (self.ids["team2"], 2, 4)},
                await self.results(s),
            )

    async def test_the_latest_stage_with_a_place_decides_and_no_place_is_null(self) -> None:
        async with self.Session() as s:
            groups, playoff = await self.stage(s, 1), await self.stage(s, 2)
            for member, team in (("m0", "team0"), ("m1", "team1"), ("m2", "team2")):
                await self.roster(s, member, team)
            self.standing(s, "team0", 2, stage_id=groups)
            self.standing(s, "team0", 3, stage_id=playoff)  # the latest stage, not the best place
            self.standing(s, "team1", 5, stage_id=groups)
            self.standing(s, "team1", 0, stage_id=playoff)  # an unranked placeholder is skipped
            self.standing(s, "team2", 0, stage_id=groups)  # never ranked
            await self.finish(s)
            await write_participant_results(s, self.ids["t"])
            await s.commit()
            self.assertEqual(
                {
                    self.ids["m0"]: (self.ids["team0"], 3, 4),
                    self.ids["m1"]: (self.ids["team1"], 5, 4),
                    self.ids["m2"]: (self.ids["team2"], None, 4),
                },
                await self.results(s),
            )

    async def test_the_last_completed_formation_decides_and_the_field_is_its_output(self) -> None:
        async with self.Session() as s:
            await self.formations(s, early=("team0", "team1"), late=("team2",))  # team3 stays tournament-wide
            await self.roster(s, "m0", "team2")  # the lower Player.id, but the later formation
            await self.roster(s, "m0", "team0")
            await self.roster(s, "m1", "team3")  # a tournament-wide team comes after any formation's
            await self.roster(s, "m1", "team1")
            await self.roster(s, "m2", "team3")
            self.standing(s, "team0", 4)
            self.standing(s, "team1", 3)
            self.standing(s, "team2", 1)
            self.standing(s, "team3", 2)
            await self.finish(s)
            await write_participant_results(s, self.ids["t"])
            await s.commit()
            # A node's field is its teams plus the tournament-wide ones; a tournament-wide team's is every team.
            self.assertEqual(
                {
                    self.ids["m0"]: (self.ids["team2"], 1, 2),
                    self.ids["m1"]: (self.ids["team1"], 3, 3),
                    self.ids["m2"]: (self.ids["team3"], 2, 4),
                },
                await self.results(s),
            )

    async def test_the_formation_is_the_teams_not_the_players_column(self) -> None:
        async with self.Session() as s:
            await self.formations(s, early=("team0", "team1"), late=("team2",))
            await self.roster(s, "m0", "team0")
            await self.roster(s, "m1", "team2")
            await s.execute(sa.update(Player).values(formation_node_id=None))  # a player added without the node
            self.standing(s, "team0", 2)
            self.standing(s, "team2", 1)
            await self.finish(s)
            await write_participant_results(s, self.ids["t"])
            await s.commit()
            self.assertEqual(
                {self.ids["m0"]: (self.ids["team0"], 2, 3), self.ids["m1"]: (self.ids["team2"], 1, 2)},
                await self.results(s),
            )

    async def test_a_substitute_has_no_result(self) -> None:
        async with self.Session() as s:
            await self.roster(s, "m0", "team0", substitute=True)
            await self.roster(s, "m1", "team1")
            self.standing(s, "team0", 1)
            self.standing(s, "team1", 2)
            await self.finish(s)
            await write_participant_results(s, self.ids["t"])
            await s.commit()
            self.assertEqual({self.ids["m1"]: (self.ids["team1"], 2, 4)}, await self.results(s))

    async def test_an_unfinished_tournament_loses_its_rows(self) -> None:
        async with self.Session() as s:
            await self.roster(s, "m0", "team0")
            self.standing(s, "team0", 1)
            await self.finish(s)
            await write_participant_results(s, self.ids["t"])
            await self.finish(s, finished=False)
            written = await write_participant_results(s, self.ids["t"])
            await s.commit()
            self.assertEqual(0, written)
            self.assertEqual({}, await self.results(s))


class MemberTournamentRowTests(_ResultCase):
    async def _chosen(self, s, member: str) -> list[int]:
        query = sa.select(Player.id).where(
            Player.tournament_id == self.ids["t"],
            Player.workspace_member_id == self.ids[member],
            is_member_tournament_row(),
        )
        return list((await s.scalars(query)).all())

    async def test_the_final_team_row_wins_over_a_later_row(self) -> None:
        async with self.Session() as s:
            first = await self.roster(s, "m0", "team0")
            await self.roster(s, "m0", "team1")
            self.result(s, "m0", "team0")
            await s.flush()
            self.assertEqual([first], await self._chosen(s, "m0"))

    async def test_without_a_result_the_latest_non_substitute_row_wins(self) -> None:
        async with self.Session() as s:
            playing = await self.roster(s, "m0", "team0")
            await self.roster(s, "m0", "team1", substitute=True)
            self.assertEqual([playing], await self._chosen(s, "m0"))

    async def test_without_a_result_the_last_completed_formation_wins(self) -> None:
        async with self.Session() as s:
            await self.formations(s, early=("team0",), late=("team1",))
            await self.roster(s, "m0", "team1")
            await self.roster(s, "m0", "team0")
            await self.roster(s, "m1", "team2")  # tournament-wide
            await self.roster(s, "m1", "team0")
            ids = {
                m: await s.scalars(
                    sa.select(Player.id).where(Player.workspace_member_id == self.ids[m]).order_by(Player.id)
                )
                for m in ("m0", "m1")
            }
            m0, m1 = (list(ids["m0"]), list(ids["m1"]))
            self.assertEqual([m0[0]], await self._chosen(s, "m0"))  # team1, formed later than team0
            self.assertEqual([m1[1]], await self._chosen(s, "m1"))  # a formation's team before the tournament-wide one


class LookupTests(_ResultCase):
    async def test_the_repository_lookup_returns_the_final_team_row(self) -> None:
        async with self.Session() as s:
            first = await self.roster(s, "m0", "team0")
            await self.roster(s, "m0", "team1")
            self.result(s, "m0", "team0")
            await s.commit()
        async with self.Session() as s:
            player = await PlayerRepository().get_by_user_and_tournament(
                s, user_id=self.users[0], tournament_id=self.ids["t"]
            )
        self.assertEqual(first, player.id)

    async def test_the_stream_roster_has_one_row_per_user(self) -> None:
        async with self.Session() as s:
            await self.roster(s, "m0", "team0")
            await self.roster(s, "m0", "team1")
            await s.commit()
        async with self.Session() as s:
            rows = await StreamTargetRepository().list_roster(s, self.ids["t"], [self.users[0]])
        self.assertEqual([(self.users[0], self.ids["team1"])], [(row.user_id, row.team_id) for row in rows])
