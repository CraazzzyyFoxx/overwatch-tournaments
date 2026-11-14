"""Corrections and requalification over the flow: refused past ``ready``, ``ready`` stages re-seated (spec §8.4)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from shared import models
from shared.core.errors import BaseAPIException
from shared.models.platform.outbox import EventOutbox
from shared.models.tournament.flow import FlowEdge, FlowNode
from shared.models.tournament.standings import Standing
from src import schemas
from src.services.admin.stage import stage_service
from src.services.admin.standing import standing_service
from src.services.flow.corrections import (
    assert_encounter_correction_allowed,
    assert_stage_correction_allowed,
    started_cut,
)
from src.services.flow.engine import flow_engine
from tests._encounter_layer import add_encounter
from tests._flow_playoff import GroupsToPlayoffCase, Setup

_TOP_TWO: dict[str, Any] = {"mode": "per_item_top", "n": 2}


class FlowCorrectionsDbTests(GroupsToPlayoffCase):
    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            jobs = sa.select(models.TournamentComputationJob.id).where(
                models.TournamentComputationJob.tournament_id == self.tournament_id
            )
            await s.execute(sa.delete(EventOutbox).where(EventOutbox.payload_json["job_id"].as_integer().in_(jobs)))
            await s.commit()
        await super().asyncTearDown()

    async def _set_status(self, node_id: int, status: str) -> None:
        async with self.Session() as s:
            await s.execute(sa.update(FlowNode).where(FlowNode.id == node_id).values(status=status))
            await s.commit()

    async def _group_encounter(self, setup: Setup) -> models.Encounter:
        async with self.Session() as s:
            tournament = await s.get_one(models.Tournament, self.tournament_id)
            encounter = await add_encounter(
                s,
                tournament,
                self.rule_id,
                teams=[setup.teams["A1"], setup.teams["A2"]],
                stage_id=setup.groups_stage_id,
                stage_item_id=setup.group_a_item_id,
            )
            await s.commit()
            return encounter

    async def _refused(self, check) -> BaseAPIException:
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await check(s)
        return caught.exception

    async def _swap_group_places(self, setup: Setup, first: str, second: str, *, tie: int | None = None) -> None:
        """Trade the group places of two teams and let the flow follow."""
        t = setup.teams
        async with self.Session() as s:
            places = dict(
                (
                    await s.execute(
                        sa.select(Standing.team_id, Standing.position).where(
                            Standing.team_id.in_([t[first], t[second]])
                        )
                    )
                ).all()
            )
            for one, other in ((first, second), (second, first)):
                await s.execute(
                    sa.update(Standing)
                    .where(Standing.team_id == t[one])
                    .values(position=places[t[other]], tie_group=tie)
                )
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()

    async def _team_seats(self, setup: Setup) -> list[tuple[int, int]]:
        return [(slot, team) for slot, team, _, _ in (await self._seats(setup.playoff_stage_id))["Bracket"]]

    async def _reseat(self) -> int:
        async with self.Session() as s:
            moved = await stage_service.reseat_ready_stages(s, self.tournament_id)
            await s.commit()
            return moved

    async def test_correction_allowed_while_playoff_is_draft_or_ready(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        encounter = await self._group_encounter(setup)

        async with self.Session() as s:
            await assert_encounter_correction_allowed(s, encounter)  # draft: no raise
        await self._ready(setup)
        async with self.Session() as s:
            await assert_encounter_correction_allowed(s, encounter)  # ready: no raise

    async def test_correction_refused_once_playoff_is_live(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        encounter = await self._group_encounter(setup)
        await self._ready(setup)
        await self._set_status(setup.playoff_node_id, "live")

        refused = await self._refused(lambda s: assert_encounter_correction_allowed(s, encounter))

        self.assertEqual(409, refused.status_code)
        self.assertEqual("downstream_started", refused.detail[0]["code"])
        self.assertEqual(
            "Downstream Playoff already started; correct it there or reopen it first", refused.detail[0]["msg"]
        )

    async def test_correction_refused_once_formation_is_forming(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        async with self.Session() as s:
            top = await s.get_one(FlowNode, setup.filter_node_id)
            formation = FlowNode(tournament_id=self.tournament_id, kind="formation", name="Draft", status="forming")
            s.add(formation)
            await s.flush()
            s.add(
                FlowEdge(
                    tournament_id=self.tournament_id,
                    source_node_id=top.id,
                    source_port="passed",
                    target_node_id=formation.id,
                    target_port="players",
                )
            )
            await s.commit()

        refused = await self._refused(lambda s: assert_stage_correction_allowed(s, setup.groups_stage_id))

        self.assertEqual("downstream_started", refused.detail[0]["code"])
        self.assertIn("Draft", refused.detail[0]["msg"])

    async def test_started_cut_counts_a_formation_that_left_draft(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        async with self.Session() as s:
            formation = FlowNode(tournament_id=self.tournament_id, kind="formation", name="Draft", status="draft")
            s.add(formation)
            await s.flush()
            s.add(
                FlowEdge(
                    tournament_id=self.tournament_id,
                    source_node_id=setup.filter_node_id,
                    source_port="passed",
                    target_node_id=formation.id,
                    target_port="players",
                )
            )
            await s.commit()
        async with self.Session() as s:
            self.assertIsNone(await started_cut(s, setup.group_a_item_id))  # a draft formation consumed nothing yet
        await self._set_status(formation.id, "forming")
        async with self.Session() as s:
            self.assertEqual(2, await started_cut(s, setup.group_a_item_id))  # A1, A2 reached the formation

    async def test_correction_allowed_with_only_pure_nodes_downstream(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        async with self.Session() as s:
            group_node = await s.scalar(sa.select(FlowNode.id).where(FlowNode.stage_id == setup.groups_stage_id))
            aggregate = FlowNode(
                tournament_id=self.tournament_id, kind="aggregate", name="Sum", status="tentative", config={}
            )
            board = FlowNode(tournament_id=self.tournament_id, kind="leaderboard", name="Board", status="tentative")
            s.add_all([aggregate, board])
            await s.flush()
            s.add_all(
                [
                    FlowEdge(
                        tournament_id=self.tournament_id,
                        source_node_id=group_node,
                        source_port="ranking",
                        target_node_id=aggregate.id,
                        target_port="inputs",
                    ),
                    FlowEdge(
                        tournament_id=self.tournament_id,
                        source_node_id=aggregate.id,
                        source_port="ranking",
                        target_node_id=board.id,
                        target_port="ranking",
                    ),
                ]
            )
            await s.commit()
        # The playoff is live, but only through the filter: cut that wire so the group's reach is the pure chain.
        async with self.Session() as s:
            await s.execute(sa.delete(FlowEdge).where(FlowEdge.target_node_id == setup.playoff_node_id))
            await s.commit()
        await self._set_status(setup.playoff_node_id, "live")

        async with self.Session() as s:
            await assert_stage_correction_allowed(s, setup.groups_stage_id)  # stage → aggregate → leaderboard: no raise

    async def test_scoring_edit_uses_the_same_rule(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        async with self.Session() as s:
            await assert_stage_correction_allowed(s, setup.groups_stage_id)  # draft: no raise
        await self._ready(setup)
        await self._set_status(setup.playoff_node_id, "completed")

        refused = await self._refused(lambda s: assert_stage_correction_allowed(s, setup.groups_stage_id))

        self.assertEqual((409, "downstream_started"), (refused.status_code, refused.detail[0]["code"]))

    async def test_started_cut_is_the_deepest_seated_place(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        await self._ready(setup)
        async with self.Session() as s:
            self.assertIsNone(await started_cut(s, setup.group_a_item_id))  # ready: not started
        await self._set_status(setup.playoff_node_id, "live")

        async with self.Session() as s:
            self.assertEqual(2, await started_cut(s, setup.group_a_item_id))  # A1, A2 seated

    async def test_pins_below_the_cut_still_pass(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO, per_group=4)
        await self._ready(setup)
        await self._set_status(setup.playoff_node_id, "live")
        t = setup.teams

        async def pin(pins: dict[str, int]) -> None:
            async with self.Session() as s:
                stage = await s.get_one(models.Stage, setup.groups_stage_id)
                await standing_service.set_pins(
                    s,
                    stage,
                    schemas.StandingPinsUpdate(
                        stage_item_id=setup.group_a_item_id,
                        pins=[{"team_id": t[name], "position": place} for name, place in pins.items()],
                    ),
                )

        with self.assertRaises(BaseAPIException) as refused:
            await pin({"A2": 3})  # A2 is seated: a pin across the cut of 2
        self.assertEqual(409, refused.exception.status_code)
        await pin({"A3": 4, "A4": 3})  # A3 <-> A4 below the cut

        async with self.Session() as s:
            pins = dict((await s.execute(sa.select(models.StandingPin.team_id, models.StandingPin.position))).all())
        self.assertEqual({t["A3"]: 4, t["A4"]: 3}, pins)

    async def test_reseat_moves_seats_of_a_ready_playoff(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        await self._ready(setup)
        t = setup.teams
        before = await self._team_seats(setup)
        slot_of_a2 = next(slot for slot, team in before if team == t["A2"])
        async with self.Session() as s:
            tournament = await s.get_one(models.Tournament, self.tournament_id)
            await add_encounter(
                s,
                tournament,
                self.rule_id,
                teams=[t["A1"], t["A2"]],
                stage_id=setup.playoff_stage_id,
                stage_item_id=setup.playoff_item_id,
                name="old pairing",
            )
            await s.commit()

        await self._swap_group_places(setup, "A2", "A3")  # A3 is second now

        self.assertEqual(1, await self._reseat())
        after = await self._team_seats(setup)
        self.assertEqual([(slot, t["A3"] if slot == slot_of_a2 else team) for slot, team in before], after)
        results = await self._result_ids(setup.filter_node_id)
        seats = (await self._seats(setup.playoff_stage_id))["Bracket"]
        self.assertEqual([results[team] for _, team, _, _ in seats], [source for _, _, _, source in seats])
        async with self.Session() as s:
            names = list(
                await s.scalars(
                    sa.select(models.Encounter.name).where(models.Encounter.tournament_id == self.tournament_id)
                )
            )
        self.assertEqual(1, len(names))
        self.assertIn("A3", names[0])
        self.assertNotIn("A2", names[0])

    async def test_reseat_skips_a_stage_whose_filter_is_tied(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        await self._ready(setup)
        before = await self._team_seats(setup)

        await self._swap_group_places(setup, "A2", "A3", tie=2)  # A2 and A3 share place 2/3: the cut is tied

        self.assertEqual(0, await self._reseat())
        self.assertEqual(before, await self._team_seats(setup))

    async def test_reseat_leaves_a_live_playoff_alone(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        await self._ready(setup)
        before = await self._team_seats(setup)
        await self._set_status(setup.playoff_node_id, "live")

        await self._swap_group_places(setup, "A2", "A3")

        self.assertEqual(0, await self._reseat())
        self.assertEqual(before, await self._team_seats(setup))

    async def _hand_seat(self, setup: Setup, old: str, new: str) -> None:
        """An admin seats ``new`` over ``old``'s seat: the stamp the admin writers leave."""
        async with self.Session() as s:
            await s.execute(
                sa.update(models.StageItemInput)
                .where(models.StageItemInput.team_id == setup.teams[old])
                .values(team_id=setup.teams[new], source_result_id=None, seat_source="manual")
            )
            await s.commit()

    async def test_reseat_never_moves_a_manual_seat(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        await self._ready(setup)
        t = setup.teams
        before = await self._team_seats(setup)
        await self._hand_seat(setup, "B2", "B2")  # an admin's own seat for a team that is in the input

        await self._swap_group_places(setup, "A2", "A3")

        self.assertEqual(1, await self._reseat())
        slot_of_a2 = next(slot for slot, team in before if team == t["A2"])
        self.assertEqual(
            [(slot, t["A3"] if slot == slot_of_a2 else team) for slot, team in before], await self._team_seats(setup)
        )
        seats = (await self._seats(setup.playoff_stage_id))["Bracket"]
        self.assertIsNone(next(source for _, team, _, source in seats if team == t["B2"]))

    async def test_reseat_keeps_a_manual_seat_of_a_team_outside_the_input(self) -> None:
        setup = await self._groups_to_playoff(filter_config=_TOP_TWO)
        await self._ready(setup)
        t = setup.teams
        before = await self._team_seats(setup)
        await self._hand_seat(setup, "B2", "B3")  # a replacement the input does not hold

        await self._swap_group_places(setup, "A2", "A3")

        self.assertEqual(1, await self._reseat())
        expected = {t["A2"]: t["A3"], t["B2"]: t["B3"]}
        self.assertEqual([(slot, expected.get(team, team)) for slot, team in before], await self._team_seats(setup))
