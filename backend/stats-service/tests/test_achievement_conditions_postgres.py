"""The series conditions' SQL on the real Postgres.

The SQLite suites run the same nodes against in-memory tables, which cannot say
whether Postgres accepts what the nodes build: a sum over a correlated scalar
subquery, a CASE over aliased seats, several aliases of one table joined in a
chain. Needs the test Postgres.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))


from shared.core import enums  # noqa: E402
from shared.models.encounter import Encounter  # noqa: E402
from shared.models.tournament.bracket_encounter import BracketEncounter  # noqa: E402
from shared.models.tournament.flow import FlowNode  # noqa: E402
from shared.models.tournament.player_role import assignment_of  # noqa: E402
from shared.models.tournament.stage import Stage, StageItem  # noqa: E402
from shared.models.tournament.team import Player  # noqa: E402
from shared.services.encounter import participants  # noqa: E402
from shared.services.encounter.result import apply_result  # noqa: E402
from shared.services.ontology import rated_leaf  # noqa: E402
from shared.tests.encounter_writer_case import EncounterWriterCase  # noqa: E402

models = importlib.import_module("shared.models")
evaluator = importlib.import_module("shared.services.achievements.evaluator")
eval_context = importlib.import_module("shared.domain.achievements.context")


class SeriesConditionsOnPostgresTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="Playoff",
                stage_type=enums.StageType.DOUBLE_ELIMINATION,
                order=1,
            )
            s.add(stage)
            await s.flush()
            s.add(
                FlowNode(
                    tournament_id=self.ids["t"], kind="stage", name="Playoff", status="completed", stage_id=stage.id
                )
            )
            upper = StageItem(stage_id=stage.id, name="U", type=enums.StageItemType.BRACKET_UPPER, order=0)
            lower = StageItem(stage_id=stage.id, name="L", type=enums.StageItemType.BRACKET_LOWER, order=1)
            s.add_all([upper, lower])
            for index in (0, 1):
                s.add(
                    Player(
                        tournament_id=self.ids["t"],
                        team_id=self.ids[f"team{index}"],
                        workspace_member_id=self.ids[f"m{index}"],
                        name=f"p{index}",
                        rank=3000,
                        assignments=[
                            assignment_of(
                                await rated_leaf(
                                    s, discipline="overwatch", workspace_id=None, role="damage", sub_role=None
                                )
                            )
                        ],
                    )
                )
            await s.flush()
            # Team 0 wins the upper round 2:0; team 1 wins the lower rematch 2:1.
            self.upper = await self._decided(s, ("team0", "team1"), (2, 0), stage.id, upper.id, 1)
            self.lower = await self._decided(s, ("team0", "team1"), (1, 2), stage.id, lower.id, -1)
            await s.commit()

    async def _decided(self, session, teams, scores, stage_id, item_id, round_number, *, slot_count=None) -> Encounter:
        encounter = Encounter(
            workspace_id=self.ids["ws"],
            discipline="overwatch",
            tournament_id=self.ids["t"],
            scoring_rule_id=self.ids["rule"],
            name="E",
            slot_count=slot_count or len(teams),
        )
        session.add(encounter)
        await session.flush()
        session.add(
            BracketEncounter(
                encounter_id=encounter.id,
                tournament_id=self.ids["t"],
                stage_id=stage_id,
                stage_item_id=item_id,
                round=round_number,
            )
        )
        seats = [
            await participants.place_team(
                session, encounter, slot=slot, team_id=self.ids[key], name=key, seed=None, members=()
            )
            for slot, key in enumerate(teams, 1)
        ]
        ranked = sorted(set(scores), reverse=True)
        await apply_result(
            session,
            encounter,
            source=enums.EncounterResultSource.ADMIN,
            totals={seat.id: float(score) for seat, score in zip(seats, scores, strict=True)},
            placements={seat.id: ranked.index(score) + 1 for seat, score in zip(seats, scores, strict=True)},
            action=enums.EncounterResultAuditAction.CONFIRM,
            audit_source="admin",
            actor_user_id=None,
            reason="test",
        )
        return encounter

    async def run_node(self, node: str, params: dict) -> set:
        async with self.Session() as s:
            tournament = await s.get_one(models.Tournament, self.ids["t"])
            context = eval_context.EvalContext(
                workspace_id=self.ids["ws"], discipline="overwatch", tournament=tournament
            )
            return await evaluator.execute_leaf(s, node, params, context)

    def user(self, index: int) -> int:
        return self.users[index]

    async def test_winrate_sums_the_team_score_over_every_seat(self) -> None:
        # Team 0 scored 3 of the 5 maps played, team 1 the other 2.
        self.assertEqual(
            {(self.user(0), self.ids["t"])}, await self.run_node("tournament_winrate", {"op": ">", "value": 0.5})
        )
        self.assertEqual({(self.user(0),)}, await self.run_node("global_winrate", {"op": ">", "value": 0.5}))
        self.assertEqual({(self.user(0),)}, await self.run_node("global_winrate", {"metric": "won_maps", "limit": 1}))

    async def test_revenge_goes_to_the_team_that_lost_first_and_won_the_rematch(self) -> None:
        self.assertEqual({(self.user(1), self.ids["t"])}, await self.run_node("encounter_revenge", {}))

    async def test_the_bracket_path_reads_rounds_from_the_bracket_position(self) -> None:
        both = {(self.user(0), self.ids["t"]), (self.user(1), self.ids["t"])}
        self.assertEqual(both, await self.run_node("bracket_path", {"played_lower_bracket": True}))
        self.assertEqual(
            {(self.user(1), self.ids["t"])},
            await self.run_node("bracket_path", {"played_lower_bracket": True, "min_lower_bracket_wins": 1}),
        )

    async def test_series_results_follow_the_seats(self) -> None:
        self.assertEqual(
            {(self.user(0), self.ids["t"])},
            await self.run_node("encounter_score", {"scores": [[2, 0]], "side": "winner"}),
        )
        sweep_losers = await self.run_node("encounter_result", {"outcome": "loss", "opponent_score": 0})
        self.assertEqual({(self.user(1), self.ids["t"], self.upper.id)}, sweep_losers)
        comeback = await self.run_node("encounter_comeback", {"min_deficit": 1})
        self.assertEqual(set(), comeback)  # no parsed maps behind either series

    async def test_a_lobby_is_not_a_duel(self) -> None:
        async with self.Session() as s:
            await self._decided(s, ("team0", "team1", "team2"), (5, 3, 1), None, None, 1, slot_count=3)
            await s.commit()

        # The lobby's first two seats finished 1st and 2nd, and still award nothing.
        self.assertEqual(
            {(self.user(1), self.ids["t"], self.upper.id)},
            await self.run_node("encounter_result", {"outcome": "loss", "opponent_score": 0}),
        )
        self.assertEqual(set(), await self.run_node("encounter_score", {"scores": [[5, 3]], "side": "winner"}))

    async def test_a_decided_mix_round_in_the_workspace_awards_nothing(self) -> None:
        async with self.Session() as s:
            mix = await self.mix_encounter(s)
            seats = (
                await s.scalars(
                    sa.select(models.EncounterTeam)
                    .where(models.EncounterTeam.encounter_id == mix.id)
                    .order_by(models.EncounterTeam.slot)
                )
            ).all()
            await apply_result(
                s,
                mix,
                source=enums.EncounterResultSource.ADMIN,
                totals={seats[0].id: 1.0, seats[1].id: 0.0},
                placements={seats[0].id: 1, seats[1].id: 2},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason="test",
            )
            await s.commit()

        # A 1:0 series exists only as the mix round: the tournament's are 2:0 and 1:2.
        self.assertEqual(set(), await self.run_node("encounter_score", {"scores": [[1, 0]], "side": "winner"}))
        self.assertEqual({(self.user(0),)}, await self.run_node("global_winrate", {"metric": "won_maps", "limit": 1}))
