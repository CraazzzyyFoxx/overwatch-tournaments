"""A merge that moves roster rows carries their tournament results to the target member. Needs the test Postgres."""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.models.tournament import Player, Standing, Tournament
from shared.services.participant_result import write_participant_results
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.services.admin.user_merge import UserMergeService

PR = models.ParticipantResult


class MergeRewritesResultsTests(EncounterWriterCase):
    async def test_a_moved_roster_row_carries_its_result(self) -> None:
        async with self.Session() as s:
            s.add(
                Player(
                    tournament_id=self.ids["t"],
                    team_id=self.ids["team0"],
                    workspace_member_id=self.ids["m0"],
                    name="p0",
                )
            )
            s.add(
                Standing(
                    tournament_id=self.ids["t"],
                    team_id=self.ids["team0"],
                    position=1,
                    overall_position=1,
                    matches=1,
                    points=3.0,
                )
            )
            await s.execute(
                sa.update(Tournament)
                .where(Tournament.id == self.ids["t"])
                .values(status=enums.TournamentStatus.COMPLETED, is_finished=True)
            )
            await write_participant_results(s, self.ids["t"])
            await s.commit()
        async with self.Session() as s:
            await UserMergeService()._repoint_player_workspace_members(
                s, source_user_id=self.users[0], target_user_id=self.users[1]
            )
            await s.commit()
        async with self.Session() as s:
            rows = (
                await s.execute(
                    sa.select(PR.workspace_member_id, PR.final_team_id, PR.placement).where(
                        PR.tournament_id == self.ids["t"]
                    )
                )
            ).all()
        self.assertEqual([(self.ids["m1"], self.ids["team0"], 1)], [tuple(row) for row in rows])
