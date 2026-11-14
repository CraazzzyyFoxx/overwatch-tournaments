"""``participant_result`` is written when a tournament completes and on a standings correction of a finished one
(spec §4.7). Needs the test Postgres."""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.messaging.config import ACHIEVEMENT_EVALUATE_QUEUE
from shared.models.platform.outbox import EventOutbox
from shared.models.tournament import Player, Standing, Tournament
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.domain.bracket import engine
from src.services.flow.lifecycle import flow_node_service
from tests.test_elimination_standings import _PlayoffTableCase, _round

PR = models.ParticipantResult


async def _placements(session, tournament_id: int) -> dict[int, int | None]:
    rows = await session.execute(
        sa.select(PR.workspace_member_id, PR.placement).where(PR.tournament_id == tournament_id)
    )
    return dict(rows.all())


async def _evaluations(session, tournament_id: int) -> list[tuple[int, dict]]:
    """This tournament's queued achievement evaluations, oldest first."""
    rows = await session.execute(
        sa.select(EventOutbox.id, EventOutbox.payload_json)
        .where(EventOutbox.routing_key == ACHIEVEMENT_EVALUATE_QUEUE.name)
        .order_by(EventOutbox.id)
    )
    return [(row_id, payload) for row_id, payload in rows.all() if payload.get("tournament_id") == tournament_id]


class CompletionTests(EncounterWriterCase):
    async def test_completing_writes_results_and_reopening_removes_them(self) -> None:
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
            await s.commit()
        async with self.Session() as s:
            stage = models.Stage(
                tournament_id=self.ids["t"],
                name="S",
                stage_type=enums.StageType.ROUND_ROBIN,
                scoring_rule_id=self.ids["rule"],
            )
            s.add(stage)
            await s.flush()
            node = models.FlowNode(
                tournament_id=self.ids["t"], kind="stage", name="S", status="live", stage_id=stage.id, config={}
            )
            s.add(node)
            await s.commit()
            node_id = node.id
        for target in (enums.FlowNodeStatus.COMPLETED, enums.FlowNodeStatus.LIVE):
            async with self.Session() as s:
                await flow_node_service.transition(s, node_id, target, actor=None)
                await s.commit()
            if target is enums.FlowNodeStatus.COMPLETED:
                async with self.Session() as s:
                    completed = await _placements(s, self.ids["t"])
        async with self.Session() as s:
            reopened = await _placements(s, self.ids["t"])
            evaluations = await _evaluations(s, self.ids["t"])
            await s.execute(sa.delete(EventOutbox).where(EventOutbox.id.in_([row_id for row_id, _ in evaluations])))
            await s.commit()

        self.assertEqual({self.ids["m0"]: 1}, completed)
        self.assertEqual({}, reopened)
        # One evaluation per flip of ``is_finished``: the completion, then the reopen.
        self.assertEqual(
            [["tournament.participant_result"], ["tournament.participant_result"]],
            [payload["changed_tables"] for _, payload in evaluations],
        )


class CorrectionTests(_PlayoffTableCase):
    async def test_a_result_on_a_finished_tournament_rewrites_the_results(self) -> None:
        async with self.Session() as s:
            for index in range(self.team_count):
                s.add(
                    Player(
                        tournament_id=self.ids["t"],
                        team_id=self.ids[f"team{index}"],
                        workspace_member_id=self.ids[f"m{index}"],
                        name=f"p{index}",
                    )
                )
            await s.commit()
        skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        ids = await self.persisted(skeleton)
        semi_losers = await self.play(_round(skeleton, ids, 1))
        async with self.Session() as s:
            await s.execute(
                sa.update(Tournament)
                .where(Tournament.id == self.ids["t"])
                .values(status=enums.TournamentStatus.COMPLETED, is_finished=True)
            )
            await s.commit()
        (final_loser,) = await self.play(_round(skeleton, ids, 2))
        await self.table()  # the recalculation the standings worker runs after the final's result
        async with self.Session() as s:
            placements = await _placements(s, self.ids["t"])

        member_of = {self.ids[f"team{i}"]: self.ids[f"m{i}"] for i in range(self.team_count)}
        expected = {
            member_of[team]: 3 if team in semi_losers else 2 if team == final_loser else 1 for team in self.team_ids
        }
        self.assertEqual(expected, placements)
