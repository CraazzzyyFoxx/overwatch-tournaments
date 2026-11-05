"""Analytics reads a member who played for two teams of one tournament once (spec §11.2, §11.3). Needs the test
Postgres."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

import sqlalchemy as sa  # noqa: E402

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.models.encounter import Encounter  # noqa: E402
from shared.models.tournament import Player, Standing, Team, Tournament  # noqa: E402
from shared.models.tournament.player_role import assignment_of  # noqa: E402
from shared.services.encounter import participants  # noqa: E402
from shared.services.encounter.result import apply_result  # noqa: E402
from shared.services.ontology import rated_leaf  # noqa: E402
from shared.services.participant_result import write_participant_results  # noqa: E402
from shared.tests.encounter_writer_case import EncounterWriterCase  # noqa: E402
from tests.ow_analytics import module as ow_module  # noqa: E402

analytics_service = importlib.import_module("src.services.analytics.service").analytics_service
analytics_read_service = importlib.import_module("src.services.analytics.read_queries").analytics_read_service
evaluate = importlib.import_module("src.services.analytics.evaluate")
shift_features = ow_module("features.shift_features")


async def _damage(session) -> list:
    leaf = await rated_leaf(session, discipline="overwatch", workspace_id=None, role="damage", sub_role=None)
    return [assignment_of(leaf)]


class TwoTeamMemberAnalyticsTests(EncounterWriterCase):
    """m0 plays for team0 (rank 1000), then team1 (rank 3000, final, 1st)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            self.rows = []
            for team, rank, overall in (("team0", 1000, 2), ("team1", 3000, 1)):
                player = Player(
                    tournament_id=self.ids["t"],
                    team_id=self.ids[team],
                    workspace_member_id=self.ids["m0"],
                    name=f"m0-{team}",
                    rank=rank,
                    assignments=await _damage(s),
                )
                s.add(player)
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
                await s.flush()
                self.rows.append(player.id)
            await s.execute(
                sa.update(Tournament)
                .where(Tournament.id == self.ids["t"])
                .values(status=enums.TournamentStatus.COMPLETED, is_finished=True)
            )
            await write_participant_results(s, self.ids["t"])
            await s.commit()

    async def test_rank_history_has_one_row_per_member_tournament(self) -> None:
        async with self.Session() as s:
            df = await shift_features.load_player_rank_history(s, [self.ids["t"]], workspace_id=self.ids["ws"])
        self.assertEqual([self.rows[1]], df[df["user_id"] == self.users[0]]["player_id"].tolist())

    async def test_analytics_rows_carry_the_member_result(self) -> None:
        async with self.Session() as s:
            rows = await analytics_service.get_analytics(s, workspace_id=self.ids["ws"], discipline="overwatch")
        mine = {(r["team_id"], r["overall_position"], r["team_count"]) for r in rows if r["user_id"] == self.users[0]}
        self.assertEqual({(self.ids["team0"], 1, 4), (self.ids["team1"], 1, 4)}, mine)

    async def test_streak_history_counts_the_tournament_once(self) -> None:
        async with self.Session() as s:
            rows = await analytics_read_service.get_streaks(s, self.ids["t"])
        self.assertEqual([1], [place for user, *_rest, place in rows if user.id == self.users[0]])


class EvaluationChainTests(EncounterWriterCase):
    async def test_the_evaluation_chain_follows_the_final_team_row(self) -> None:
        async with self.Session() as s:
            prior = Tournament(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                name=f"prior-{self.ids['t']}",
                slug=f"prior-{self.ids['t']}",
                status=enums.TournamentStatus.COMPLETED,
                is_finished=True,
                start_date=datetime(2020, 1, 1, tzinfo=UTC),
            )
            s.add(prior)
            await s.flush()
            final_team, later_team = (Team(tournament_id=prior.id, name=n, balancer_name=n) for n in ("PA", "PB"))
            s.add_all([final_team, later_team])
            await s.flush()
            # The final team is the EARLIER roster row: a latest-id rule would pick rank 4000 instead.
            for team, rank in ((final_team, 1000), (later_team, 4000)):
                s.add(
                    Player(
                        tournament_id=prior.id,
                        team_id=team.id,
                        workspace_member_id=self.ids["m0"],
                        name=f"m0-{rank}",
                        rank=rank,
                        assignments=await _damage(s),
                    )
                )
            s.add(
                models.ParticipantResult(
                    tournament_id=prior.id,
                    workspace_member_id=self.ids["m0"],
                    final_team_id=final_team.id,
                    placement=1,
                    field_size=2,
                )
            )
            current = []
            for index in (0, 1):
                player = Player(
                    tournament_id=self.ids["t"],
                    team_id=self.ids[f"team{index}"],
                    workspace_member_id=self.ids[f"m{index}"],
                    name=f"p{index}",
                    rank=2500,
                    assignments=await _damage(s),
                )
                s.add(player)
                await s.flush()
                current.append(player.id)
            encounter = await s.get_one(Encounter, self.ids["e"])
            seats = [
                await participants.place_team(
                    s,
                    encounter,
                    slot=slot,
                    team_id=self.ids[f"team{slot - 1}"],
                    name=f"T{slot}",
                    seed=None,
                    members=(),
                )
                for slot in (1, 2)
            ]
            await apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={seats[0].id: 2.0, seats[1].id: 0.0},
                placements={seats[0].id: 1, seats[1].id: 2},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason="test",
            )
            await s.commit()
        async with self.Session() as s:
            frame = await evaluate.load_evaluation_frame(s, discipline="overwatch", workspace_id=self.ids["ws"])
        level = frame.levels.loc[current[0]]
        # Prior rank 1000 is a weaker (higher) division than the current 2500; rank 4000 would be stronger.
        self.assertGreater(level["no_moves"], level["organizer"])
