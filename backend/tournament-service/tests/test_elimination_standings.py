"""Playoff standings while the bracket is still running. Needs the test Postgres.

An eliminated team holds the best place it can still end on -- a beaten semi-finalist
is 3rd while the final is unplayed -- and a team still alive has none yet (0).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from shared.core import enums
from shared.models.encounter import Encounter
from shared.models.tournament import Standing
from shared.services.encounter import participants
from shared.services.encounter.result import reopen
from src.domain.bracket import engine
from src.domain.bracket.types import AdvancementEdge, BracketSkeleton, Pairing
from src.services.bracket import advancement
from src.services.encounter.service import encounter_service
from src.services.standings.service import standings_service
from tests.test_bracket_positions import BracketCase


class _PlayoffTableCase(BracketCase):
    async def persisted(self, skeleton: BracketSkeleton) -> list[int]:
        async with self.Session() as s:
            ids = [encounter.id for encounter in await self.build(s, skeleton)]
            await s.commit()
        return ids

    async def play(self, encounter_ids: Sequence[int]) -> set[int]:
        """Slot 1 wins each encounter and advances; returns the losers."""
        losers: set[int] = set()
        async with self.Session() as s:
            for encounter_id in encounter_ids:
                encounter = await s.get_one(Encounter, encounter_id)
                seats = await participants.active_teams(s, encounter_id)
                losers.update(seat.team_id for seat in seats if seat.slot != 1)
                await self.win(s, encounter, winner_slot=1)
                await advancement.advance_after_result(s, encounter)
            await s.commit()
        return losers

    async def table(self) -> dict[int, tuple[int, int]]:
        """``team -> (position, overall_position)`` after a recalculation."""
        async with self.Session() as s:
            await standings_service.recalculate_for_tournament(s, self.ids["t"])
            rows = await s.execute(
                sa.select(Standing.team_id, Standing.position, Standing.overall_position).where(
                    Standing.stage_id == self.ids["stage"]
                )
            )
            return {team_id: (position, overall) for team_id, position, overall in rows.all()}


def _round(skeleton: BracketSkeleton, ids: Sequence[int], round_number: int) -> list[int]:
    return [ids[pairing.local_id] for pairing in skeleton.pairings if pairing.round_number == round_number]


class SingleEliminationMidBracketTests(_PlayoffTableCase):
    async def test_a_beaten_semi_finalist_is_third_while_the_final_is_unplayed(self) -> None:
        skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        ids = await self.persisted(skeleton)
        semi_losers = await self.play(_round(skeleton, ids, 1))

        self.assertEqual(
            {team_id: (3, 3) if team_id in semi_losers else (0, 0) for team_id in self.team_ids},
            await self.table(),
        )

        (final_loser,) = await self.play(_round(skeleton, ids, 2))
        self.assertEqual(
            {
                team_id: (3, 3) if team_id in semi_losers else (2, 2) if team_id == final_loser else (1, 1)
                for team_id in self.team_ids
            },
            await self.table(),
        )


class SingleEliminationQuarterFinalTests(_PlayoffTableCase):
    team_count = 8

    async def test_quarter_final_losers_share_fifth_while_the_semis_are_unplayed(self) -> None:
        skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        ids = await self.persisted(skeleton)
        quarter_losers = await self.play(_round(skeleton, ids, 1))

        self.assertEqual(
            {team_id: (5, 5) if team_id in quarter_losers else (0, 0) for team_id in self.team_ids},
            await self.table(),
        )


class SingleEliminationThirdPlaceTests(_PlayoffTableCase):
    async def test_the_third_place_match_decides_third_and_fourth_not_the_title(self) -> None:
        # A Challonge "hold third place match" bracket: the semi losers meet in
        # a match that shares the final's round, wired to their LOSING places.
        plain = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        semis = [pairing for pairing in plain.pairings if pairing.round_number == 1]
        bronze = Pairing(team_ids=(None, None), round_number=2, local_id=len(plain.pairings))
        skeleton = BracketSkeleton(
            pairings=[*plain.pairings, bronze],
            total_rounds=plain.total_rounds,
            advancement_edges=[
                *plain.advancement_edges,
                *(
                    AdvancementEdge(
                        source_local_id=semi.local_id,
                        source_position=2,
                        target_local_id=bronze.local_id,
                        target_slot=slot,
                    )
                    for slot, semi in enumerate(semis, 1)
                ),
            ],
        )
        ids = await self.persisted(skeleton)
        (final_id,) = (ids[pairing.local_id] for pairing in plain.pairings if pairing.round_number == 2)
        semi_losers = await self.play(_round(plain, ids, 1))

        (fourth,) = await self.play([ids[bronze.local_id]])
        (third,) = semi_losers - {fourth}
        self.assertEqual(
            {team_id: {third: (3, 3), fourth: (4, 4)}.get(team_id, (0, 0)) for team_id in self.team_ids},
            await self.table(),
        )

        (second,) = await self.play([final_id])
        (first,) = set(self.team_ids) - semi_losers - {second}
        self.assertEqual(
            {first: (1, 1), second: (2, 2), third: (3, 3), fourth: (4, 4)},
            await self.table(),
        )


class DoubleEliminationMidBracketTests(_PlayoffTableCase):
    stage_type = enums.StageType.DOUBLE_ELIMINATION
    team_count = 8

    async def test_lower_seeds_knocked_out_first_are_seventh_while_the_upper_bracket_is_unplayed(self) -> None:
        upper, lower = self.team_ids[:4], self.team_ids[4:]
        skeleton = engine.generate_bracket(enums.StageType.DOUBLE_ELIMINATION, upper, lower_bracket_team_ids=lower)
        ids = await self.persisted(skeleton)
        knocked_out = await self.play(_round(skeleton, ids, -1))

        # The upper seeds have not played: no row yet, let alone a place.
        self.assertEqual(
            {team_id: (7, 7) if team_id in knocked_out else (0, 0) for team_id in lower},
            await self.table(),
        )


class DoubleEliminationThirdPlaceTests(_PlayoffTableCase):
    stage_type = enums.StageType.DOUBLE_ELIMINATION

    async def test_bronze_overrides_both_lower_bracket_placements(self) -> None:
        plain = engine.generate_bracket(self.stage_type, self.team_ids)
        earlier, lower_final = (
            next(pairing for pairing in plain.pairings if pairing.round_number == round_number)
            for round_number in (-1, -2)
        )
        bronze = Pairing(team_ids=(None, None), round_number=3, local_id=len(plain.pairings))
        ids = await self.persisted(
            BracketSkeleton(
                pairings=[*plain.pairings, bronze],
                total_rounds=plain.total_rounds,
                advancement_edges=[
                    *plain.advancement_edges,
                    AdvancementEdge(earlier.local_id, 2, bronze.local_id, 1),
                    AdvancementEdge(lower_final.local_id, 2, bronze.local_id, 2),
                ],
            )
        )
        await self.play(_round(plain, ids, 1))
        (fourth,) = await self.play([ids[earlier.local_id]])
        await self.play(_round(plain, ids, 2))
        (third,) = await self.play([ids[lower_final.local_id]])

        (second,) = await self.play(_round(plain, ids, 3))
        (first,) = set(self.team_ids) - {second, third, fourth}
        self.assertEqual({first: (1, 1), second: (2, 2), third: (3, 3), fourth: (4, 4)}, await self.table())
        async with self.Session() as s:
            outcome = await standings_service.recalculate_for_tournament(s, self.ids["t"])
            self.assertNotIn(self.ids["stage"], outcome.completed_stage_ids)

        self.assertEqual({third}, await self.play([ids[bronze.local_id]]))
        self.assertEqual({first: (1, 1), second: (2, 2), fourth: (3, 3), third: (4, 4)}, await self.table())
        async with self.Session() as s:
            outcome = await standings_service.recalculate_for_tournament(s, self.ids["t"])
            self.assertIn(self.ids["stage"], outcome.completed_stage_ids)

        # Reversing the lower final swaps its loser with a finalist. The old
        # bronze result must not silently award its placement to the new team.
        async with self.Session() as s:
            corrected = await s.get_one(Encounter, ids[lower_final.local_id])
            await reopen(s, corrected, actor_user_id=self.users[0], reason="wrong winner")
            await advancement.reset_downstream(s, corrected, actor_user_id=self.users[0])
            await self.win(s, corrected, winner_slot=2)
            await advancement.advance_after_result(s, corrected)
            await s.commit()
            replay = await s.get_one(Encounter, ids[bronze.local_id])
            seats = await participants.active_teams(s, replay.id)
            self.assertEqual({fourth, second}, {seat.team_id for seat in seats})
            self.assertEqual(enums.EncounterResultStatus.NONE, replay.result_status)
        self.assertEqual((4, 4), (await self.table())[fourth])


class DoubleEliminationThirdPlaceResetTests(_PlayoffTableCase):
    stage_type = enums.StageType.DOUBLE_ELIMINATION
    grand_final_type = "with_reset"

    async def test_bronze_waits_independently_of_the_grand_final_reset(self) -> None:
        skeleton = engine.generate_bracket(self.stage_type, self.team_ids, third_place_match=True)
        ids = await self.persisted(skeleton)
        (bronze_local_id,) = skeleton.third_place_ids
        bronze_id = ids[bronze_local_id]
        (final_id,) = set(_round(skeleton, ids, 3)) - {bronze_id}
        for number in (1, -1, 2, -2):
            await self.play(_round(skeleton, ids, number))

        async with self.Session() as s:
            final = await s.get_one(Encounter, final_id)
            await self.win(s, final, winner_slot=2)
            (reset_id,) = {target for target, _ in (await advancement.advance_after_result(s, final)).placed}
            await s.commit()
            self.assertEqual(
                {final_id: False, bronze_id: False, reset_id: True},
                await encounter_service.is_final_by_encounter(s, [final_id, bronze_id, reset_id]),
            )
        self.assertNotIn(1, {position for position, _ in (await self.table()).values()})
        await self.play([reset_id])
        async with self.Session() as s:
            outcome = await standings_service.recalculate_for_tournament(s, self.ids["t"])
            self.assertNotIn(self.ids["stage"], outcome.completed_stage_ids)
        await self.play([bronze_id])
        async with self.Session() as s:
            outcome = await standings_service.recalculate_for_tournament(s, self.ids["t"])
            self.assertIn(self.ids["stage"], outcome.completed_stage_ids)
