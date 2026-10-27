"""The bracket engine on positions and slots. Needs the test Postgres.

An advancement edge means "whoever finished at ``source_position`` takes ``target_slot``". These cases persist real
skeletons and play them out through the participation and result writers, because the seat swap a correction
performs -- a retired participation, its unplayed games cancelled, a new occupant in the same slot -- is exactly what
an in-memory double gets wrong.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Sequence
from unittest import TestCase

import sqlalchemy as sa

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.encounter import (
    Encounter,
    EncounterGame,
    EncounterGameTeam,
    EncounterTeam,
    EncounterTeamMember,
)
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.encounter_link import EncounterLink
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.services.encounter import participants, result
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.domain.bracket import engine, template
from src.services.bracket import advancement, persist, usability

#: ``players.user.name`` is globally unique, so the extra players a deep
#: bracket needs are tagged per test, like the writer case's own.
_TAG = itertools.count()


def _member(member_id: int, name: str) -> participants.MemberSnapshot:
    return participants.MemberSnapshot(
        workspace_member_id=member_id,
        display_name=name,
        rank=2500,
        is_substitute=False,
        roles=(("player_role", "tank"),),
    )


class BracketCase(EncounterWriterCase):
    """The writer case plus a published stage to hang a bracket on.

    ``team_count`` past the four the writer case seeds adds users, members and
    teams of its own -- an eight-team bracket is three rounds deep, which is
    what a cascade has to be proven against.
    """

    stage_type = enums.StageType.SINGLE_ELIMINATION
    grand_final_type = "no_reset"
    team_count = 4

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="Playoff",
                stage_type=self.stage_type,
                order=1,
                is_published=True,
                de_grand_final_type=self.grand_final_type,
            )
            s.add(stage)
            await s.flush()
            item = StageItem(stage_id=stage.id, name="A", type=enums.StageItemType.SINGLE_BRACKET, order=1)
            s.add(item)
            await self._seed_more_teams(s)
            await s.commit()
            self.ids["stage"] = stage.id
            self.ids["item"] = item.id

    async def _seed_more_teams(self, session) -> None:
        tag = f"brk-{os.getpid()}-{next(_TAG)}"
        for index in range(4, self.team_count):
            user = User(name=f"{tag}-{index}")
            session.add(user)
            await session.flush()
            self.users.append(user.id)
            member = WorkspaceMember(workspace_id=self.ids["ws"], player_id=user.id)
            team = Team(tournament_id=self.ids["t"], name=f"T{index}", balancer_name=f"{tag}-T{index}")
            session.add_all([member, team])
            await session.flush()
            self.ids[f"m{index}"] = member.id
            self.ids[f"team{index}"] = team.id

    @property
    def team_ids(self) -> list[int]:
        return [self.ids[f"team{index}"] for index in range(self.team_count)]

    def seat_teams(self) -> dict[int, persist.SeatTeam]:
        return {
            self.ids[f"team{index}"]: persist.SeatTeam(
                name=f"T{index}",
                seed=index + 1,
                members=[_member(self.ids[f"m{index}"], f"m{index}")],
            )
            for index in range(self.team_count)
        }

    async def build(self, session, skeleton) -> list[Encounter]:
        stage = await session.get_one(Stage, self.ids["stage"])
        return await persist.persist_skeleton(
            session,
            stage=stage,
            skeleton=skeleton,
            stage_item_id=self.ids["item"],
            teams_by_id=self.seat_teams(),
            best_of_for_round=lambda _round, *, is_final: 1,
            is_elimination=True,
        )

    async def rounds(self, session, encounters: Sequence[Encounter]) -> dict[int, int]:
        """``encounter id -> bracket round``."""
        rows = await session.execute(
            sa.select(BracketEncounter.encounter_id, BracketEncounter.round).where(
                BracketEncounter.encounter_id.in_([encounter.id for encounter in encounters])
            )
        )
        return dict(rows.all())

    async def links(self, session, encounters: Sequence[Encounter]) -> list[EncounterLink]:
        rows = await session.execute(
            sa.select(EncounterLink)
            .where(EncounterLink.target_encounter_id.in_([encounter.id for encounter in encounters]))
            .order_by(EncounterLink.target_encounter_id, EncounterLink.target_slot)
        )
        return list(rows.scalars().all())

    async def seats_of(self, session, encounter_id: int) -> list[EncounterTeam]:
        rows = await session.execute(
            sa.select(EncounterTeam)
            .where(EncounterTeam.encounter_id == encounter_id)
            .order_by(EncounterTeam.slot, EncounterTeam.id)
        )
        return list(rows.scalars().all())

    async def win(self, session, encounter: Encounter, winner_slot: int) -> None:
        """Confirm ``encounter`` with ``winner_slot`` first and the rest second."""
        seats = await participants.active_teams(session, encounter.id)
        await result.apply_result(
            session,
            encounter,
            source=enums.EncounterResultSource.ADMIN,
            totals={seat.id: (1.0 if seat.slot == winner_slot else 0.0) for seat in seats},
            placements={seat.id: (1 if seat.slot == winner_slot else 2) for seat in seats},
            action=enums.EncounterResultAuditAction.CONFIRM,
            audit_source="admin",
            actor_user_id=self.users[0],
            reason="test",
        )

    async def draw(self, session, encounter: Encounter) -> None:
        seats = await participants.active_teams(session, encounter.id)
        await result.apply_result(
            session,
            encounter,
            source=enums.EncounterResultSource.ADMIN,
            totals={seat.id: 1.0 for seat in seats},
            placements={seat.id: 1 for seat in seats},
            action=enums.EncounterResultAuditAction.CONFIRM,
            audit_source="admin",
            actor_user_id=self.users[0],
            reason="test",
        )


class SingleEliminationSkeletonTests(BracketCase):
    async def test_the_skeleton_persists_two_slot_encounters_rounds_and_positions(self) -> None:
        skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        async with self.Session() as s:
            encounters = await self.build(s, skeleton)
            await s.commit()

            self.assertEqual([2, 2, 2], [encounter.slot_count for encounter in encounters])
            rounds = await self.rounds(s, encounters)
            self.assertEqual([1, 1, 2], sorted(rounds.values()))
            self.assertEqual(
                {(self.ids["stage"], self.ids["item"])},
                {
                    (row.stage_id, row.stage_item_id)
                    for row in (await s.execute(sa.select(BracketEncounter))).scalars().all()
                    if row.encounter_id in rounds
                },
            )

            final = next(encounter for encounter in encounters if rounds[encounter.id] == 2)
            semis = [encounter for encounter in encounters if rounds[encounter.id] == 1]
            self.assertEqual(
                {(semis[0].id, 1, 1), (semis[1].id, 1, 2)},
                {
                    (link.source_encounter_id, link.source_position, link.target_slot)
                    for link in await self.links(s, [final])
                },
            )
            # The first round is seated; the final waits for two positions.
            self.assertEqual(
                [(1, "T0"), (2, "T3")],
                [(seat.slot, seat.name) for seat in await self.seats_of(s, semis[0].id)],
            )
            self.assertEqual([], await self.seats_of(s, final.id))
            self.assertEqual("TBD vs TBD", final.name)

    async def test_a_published_stage_makes_the_persisted_encounter_live(self) -> None:
        skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        async with self.Session() as s:
            encounters = await self.build(s, skeleton)
            await s.commit()
            first_id = encounters[0].id
            self.assertTrue(await usability.is_encounter_live(s, encounters[0]))
            await s.execute(sa.update(Stage).where(Stage.id == self.ids["stage"]).values(is_published=False))
            s.expire_all()
            self.assertFalse(await usability.is_encounter_live(s, await s.get_one(Encounter, first_id)))


class DoubleEliminationSkeletonTests(BracketCase):
    stage_type = enums.StageType.DOUBLE_ELIMINATION

    async def test_second_place_drops_into_a_negative_round(self) -> None:
        skeleton = engine.generate_bracket(enums.StageType.DOUBLE_ELIMINATION, self.team_ids)
        async with self.Session() as s:
            encounters = await self.build(s, skeleton)
            await s.commit()

            rounds = await self.rounds(s, encounters)
            links = await self.links(s, encounters)
            self.assertEqual({1, 2}, {link.source_position for link in links})
            self.assertEqual({1, 2}, {link.target_slot for link in links})
            # Every drop of a second place lands in the lower bracket.
            self.assertEqual(
                {True},
                {rounds[link.target_encounter_id] < 0 for link in links if link.source_position == 2},
            )
            # Each target slot is fed once, and no slot is past the card.
            self.assertEqual(len(links), len({(link.target_encounter_id, link.target_slot) for link in links}))
            for link in links:
                target = await s.get_one(Encounter, link.target_encounter_id)
                self.assertLessEqual(link.target_slot, target.slot_count)


class AdvancementTests(BracketCase):
    async def _bracket(self, session) -> tuple[list[Encounter], Encounter]:
        skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
        encounters = await self.build(session, skeleton)
        rounds = await self.rounds(session, encounters)
        semis = [encounter for encounter in encounters if rounds[encounter.id] == 1]
        final = next(encounter for encounter in encounters if rounds[encounter.id] == 2)
        return semis, final

    async def test_the_first_place_takes_the_slot_its_link_names(self) -> None:
        async with self.Session() as s:
            semis, final = await self._bracket(s)
            await self.win(s, semis[0], winner_slot=1)
            outcome = await advancement.advance_after_result(s, semis[0])
            await s.commit()

            self.assertEqual([(final.id, 1)], outcome.placed)
            self.assertEqual([], outcome.blocked_positions)
            seats = await self.seats_of(s, final.id)
            self.assertEqual([(1, "T0", True)], [(seat.slot, seat.name, seat.active) for seat in seats])
            self.assertEqual("T0 vs TBD", final.name)
            # The roster rides along with the seat.
            roster = await s.execute(
                sa.select(EncounterTeamMember.display_name_snapshot).where(
                    EncounterTeamMember.encounter_team_id == seats[0].id
                )
            )
            self.assertEqual(["m0"], list(roster.scalars().all()))

    async def test_advancing_twice_is_the_same_bracket(self) -> None:
        async with self.Session() as s:
            semis, final = await self._bracket(s)
            await self.win(s, semis[0], winner_slot=1)
            await advancement.advance_after_result(s, semis[0])
            outcome = await advancement.advance_after_result(s, semis[0])
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertEqual(1, len(await self.seats_of(s, final.id)))

    async def test_seating_over_another_team_is_refused_instead_of_guessed(self) -> None:
        """A caller that skipped ``reset_downstream`` is told so, loudly."""
        async with self.Session() as s:
            semis, _final = await self._bracket(s)
            await self.win(s, semis[0], winner_slot=1)
            await advancement.advance_after_result(s, semis[0])
            await s.commit()

        async with self.Session() as s:
            semi = await result.lock_encounter(s, semis[0].id)
            await result.reopen(s, semi, actor_user_id=self.users[0], reason="wrong team")
            await self.win(s, semi, winner_slot=2)
            with self.assertRaises(BaseAPIException):
                await advancement.advance_after_result(s, semi)

    async def test_a_tie_at_a_linked_position_blocks_and_reports_it(self) -> None:
        async with self.Session() as s:
            semis, final = await self._bracket(s)
            await self.draw(s, semis[0])
            outcome = await advancement.advance_after_result(s, semis[0])
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertEqual([1], outcome.blocked_positions)
            self.assertEqual([], await self.seats_of(s, final.id))

    async def test_an_unconfirmed_result_advances_nobody(self) -> None:
        async with self.Session() as s:
            semis, final = await self._bracket(s)
            outcome = await advancement.advance_after_result(s, semis[0])
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertEqual([], outcome.blocked_positions)
            self.assertEqual([], await self.seats_of(s, final.id))

    async def test_correcting_a_result_retires_the_downstream_seat_and_seats_the_new_team(self) -> None:
        async with self.Session() as s:
            semis, final = await self._bracket(s)
            await self.win(s, semis[0], winner_slot=1)
            await advancement.advance_after_result(s, semis[0])
            await self.win(s, semis[1], winner_slot=1)
            await advancement.advance_after_result(s, semis[1])
            await s.commit()

        async with self.Session() as s:
            final = await s.get_one(Encounter, final.id)
            seats = await participants.active_teams(s, final.id)
            played = EncounterGame(
                encounter_id=final.id,
                position=1,
                state=enums.EncounterGameState.CONFIRMED,
                result_source=enums.EncounterGameResultSource.ADMIN,
                confirmed_at=sa.func.now(),
            )
            planned = EncounterGame(encounter_id=final.id, position=2, state=enums.EncounterGameState.PLANNED)
            s.add_all([played, planned])
            await s.flush()
            for index, seat in enumerate(seats):
                s.add(
                    EncounterGameTeam(
                        game_id=played.id, encounter_id=final.id, encounter_team_id=seat.id, score=1 - index
                    )
                )
            await result.refresh_from_games(
                s,
                final,
                action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                audit_source="system",
                actor_user_id=None,
            )
            await s.commit()
            self.assertEqual(enums.EncounterStatus.COMPLETED, final.status)
            old_seat_id = seats[0].id

        # The admin corrects the first semifinal: T3 won it, not T0.
        async with self.Session() as s:
            semi = await result.lock_encounter(s, semis[0].id)
            await result.reopen(s, semi, actor_user_id=self.users[0], reason="wrong team")
            await advancement.reset_downstream(s, semi, actor_user_id=self.users[0])
            await self.win(s, semi, winner_slot=2)
            outcome = await advancement.advance_after_result(s, semi)
            await s.commit()

            final = await s.get_one(Encounter, final.id)
            self.assertEqual([(final.id, 1)], outcome.placed)
            self.assertEqual(
                [(1, "T0", False), (1, "T3", True), (2, "T1", True)],
                [(seat.slot, seat.name, seat.active) for seat in await self.seats_of(s, final.id)],
            )
            self.assertEqual("T3 vs T1", final.name)
            # The old occupant's unplayed position is cancelled; the played one
            # stays on record but no longer counts, so the final re-opens.
            states = dict(
                (
                    await s.execute(
                        sa.select(EncounterGame.position, EncounterGame.state).where(
                            EncounterGame.encounter_id == final.id
                        )
                    )
                ).all()
            )
            self.assertEqual(enums.EncounterGameState.CANCELLED, states[2])
            self.assertEqual(enums.EncounterGameState.CONFIRMED, states[1])
            self.assertEqual(enums.EncounterStatus.OPEN, final.status)
            self.assertEqual(enums.EncounterResultStatus.NONE, final.result_status)
            self.assertIsNone(final.result_source)
            retired = await s.get_one(EncounterTeam, old_seat_id)
            self.assertFalse(retired.active)

    async def test_the_reader_sees_which_position_fills_a_slot(self) -> None:
        async with self.Session() as s:
            semis, final = await self._bracket(s)
            await s.commit()
            sources = await advancement.resolve_slot_sources(s, [final.id])
            self.assertEqual(
                [
                    advancement.SlotSource(encounter_id=semis[0].id, source_position=1, slot=1),
                    advancement.SlotSource(encounter_id=semis[1].id, source_position=1, slot=2),
                ],
                sorted(sources[final.id], key=lambda source: source.slot),
            )


class DeepCascadeTests(BracketCase):
    """A correction in round 1 has to reach round 3, not just round 2."""

    team_count = 8

    async def _target_of(self, session, encounter_id: int) -> tuple[int, int]:
        """``(target encounter id, slot)`` the first place of ``encounter_id`` feeds."""
        row = await session.execute(
            sa.select(EncounterLink.target_encounter_id, EncounterLink.target_slot).where(
                EncounterLink.source_encounter_id == encounter_id,
                EncounterLink.source_position == 1,
            )
        )
        return row.one()

    async def test_a_round_one_correction_empties_every_round_below_it(self) -> None:
        async with self.Session() as s:
            skeleton = engine.generate_bracket(enums.StageType.SINGLE_ELIMINATION, self.team_ids)
            encounters = await self.build(s, skeleton)
            rounds = await self.rounds(s, encounters)
            self.assertEqual([1] * 4 + [2] * 2 + [3], sorted(rounds.values()))

            # Play the whole bracket out, slot 1 winning everywhere.
            for round_number in (1, 2, 3):
                for encounter in [item for item in encounters if rounds[item.id] == round_number]:
                    await self.win(s, encounter, winner_slot=1)
                    await advancement.advance_after_result(s, encounter)
            await s.commit()

            quarter = next(item for item in encounters if rounds[item.id] == 1)
            semi_id, semi_slot = await self._target_of(s, quarter.id)
            final_id, final_slot = await self._target_of(s, semi_id)
            self.assertEqual(3, rounds[final_id])
            self.assertEqual(enums.EncounterStatus.COMPLETED, (await s.get_one(Encounter, final_id)).status)

        async with self.Session() as s:
            corrected = await result.lock_encounter(s, quarter.id)
            await result.reopen(s, corrected, actor_user_id=self.users[0], reason="wrong team")
            await advancement.reset_downstream(s, corrected, actor_user_id=self.users[0])
            await s.commit()

            for encounter_id, emptied_slot in ((semi_id, semi_slot), (final_id, final_slot)):
                encounter = await s.get_one(Encounter, encounter_id)
                live = {seat.slot: seat for seat in await participants.active_teams(s, encounter_id)}
                self.assertNotIn(emptied_slot, live, f"slot {emptied_slot} of {encounter.name} is still taken")
                # Vacated, renamed and re-stated -- in that order, all three.
                self.assertEqual("TBD", encounter.name.split(" vs ")[emptied_slot - 1])
                self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)
                self.assertEqual(enums.EncounterResultStatus.NONE, encounter.result_status)
                self.assertIsNone(encounter.result_source)
                # The occupant is retired with its old standing, not deleted.
                retired = [seat for seat in await self.seats_of(s, encounter_id) if not seat.active]
                self.assertEqual([emptied_slot], [seat.slot for seat in retired])
                self.assertTrue(all(seat.placement is not None for seat in retired))


class GrandFinalResetTests(BracketCase):
    """The reset is still lazy: it exists only once the lower bracket wins."""

    stage_type = enums.StageType.DOUBLE_ELIMINATION
    grand_final_type = "with_reset"

    async def _grand_final(self, session, *, lower_slot: int = 2, lower_round: int = -1) -> tuple[Encounter, Encounter]:
        """A final feeding ``lower_slot`` of a grand final, both seated."""
        made: list[Encounter] = []
        for name, round_number in (("LB Final", lower_round), ("Grand Final", 2)):
            encounter = Encounter(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name=name,
                slot_count=2,
                best_of=1,
            )
            session.add(encounter)
            await session.flush()
            session.add(
                BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=self.ids["t"],
                    stage_id=self.ids["stage"],
                    stage_item_id=self.ids["item"],
                    round=round_number,
                )
            )
            made.append(encounter)
        lower, grand_final = made
        session.add(
            EncounterLink(
                tournament_id=self.ids["t"],
                source_encounter_id=lower.id,
                source_position=1,
                target_encounter_id=grand_final.id,
                target_slot=lower_slot,
            )
        )
        await session.flush()
        for slot, index in ((1, 0), (2, 1)):
            await participants.place_team(
                session,
                grand_final,
                slot=slot,
                team_id=self.ids[f"team{index}"],
                name=f"T{index}",
                seed=slot,
                members=[_member(self.ids[f"m{index}"], f"m{index}")],
            )
        return lower, grand_final

    async def test_the_lower_champion_winning_materialises_the_reset(self) -> None:
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s)
            await self.win(s, grand_final, winner_slot=2)
            outcome = await advancement.advance_after_result(s, grand_final)
            await s.commit()

            links = (
                (await s.execute(sa.select(EncounterLink).where(EncounterLink.source_encounter_id == grand_final.id)))
                .scalars()
                .all()
            )
            self.assertEqual({(1, 2), (2, 1)}, {(link.source_position, link.target_slot) for link in links})
            reset_id = links[0].target_encounter_id
            reset = await s.get_one(Encounter, reset_id)
            self.assertEqual(3, (await s.get_one(BracketEncounter, reset_id)).round)
            self.assertEqual(grand_final.best_of, reset.best_of)
            self.assertEqual(
                [(1, "T0"), (2, "T1")],
                [(seat.slot, seat.name) for seat in await participants.active_teams(s, reset_id)],
            )
            self.assertEqual({(reset_id, 1), (reset_id, 2)}, set(outcome.placed))

    async def test_the_upper_champion_winning_leaves_no_reset(self) -> None:
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s)
            await self.win(s, grand_final, winner_slot=1)
            outcome = await advancement.advance_after_result(s, grand_final)
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertEqual(
                [],
                (
                    (
                        await s.execute(
                            sa.select(EncounterLink).where(EncounterLink.source_encounter_id == grand_final.id)
                        )
                    )
                    .scalars()
                    .all()
                ),
            )

    async def test_the_lower_champion_in_the_first_slot_still_creates_the_reset(self) -> None:
        """The rule follows the slot the lower-bracket link names, not a fixed seat."""
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s, lower_slot=1)
            await self.win(s, grand_final, winner_slot=1)
            await advancement.advance_after_result(s, grand_final)
            await s.commit()

            links = (
                (await s.execute(sa.select(EncounterLink).where(EncounterLink.source_encounter_id == grand_final.id)))
                .scalars()
                .all()
            )
            self.assertEqual({(1, 1), (2, 2)}, {(link.source_position, link.target_slot) for link in links})

    async def test_the_created_reset_never_spawns_a_second_reset(self) -> None:
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s)
            await self.win(s, grand_final, winner_slot=2)
            await advancement.advance_after_result(s, grand_final)
            reset_id = await s.scalar(
                sa.select(EncounterLink.target_encounter_id).where(EncounterLink.source_encounter_id == grand_final.id)
            )
            reset = await result.lock_encounter(s, reset_id)
            await self.win(s, reset, winner_slot=2)
            outcome = await advancement.advance_after_result(s, reset)
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertEqual(
                [],
                list(
                    (await s.execute(sa.select(EncounterLink).where(EncounterLink.source_encounter_id == reset_id)))
                    .scalars()
                    .all()
                ),
            )

    async def test_a_final_fed_only_from_upper_rounds_is_never_a_grand_final(self) -> None:
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s, lower_round=1)
            await self.win(s, grand_final, winner_slot=2)
            outcome = await advancement.advance_after_result(s, grand_final)
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertIsNone(
                await s.scalar(sa.select(EncounterLink.id).where(EncounterLink.source_encounter_id == grand_final.id))
            )

    async def test_a_no_reset_stage_ends_at_the_grand_final(self) -> None:
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s)
            (await s.get_one(Stage, self.ids["stage"])).de_grand_final_type = "no_reset"
            await self.win(s, grand_final, winner_slot=2)
            outcome = await advancement.advance_after_result(s, grand_final)
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertIsNone(
                await s.scalar(sa.select(EncounterLink.id).where(EncounterLink.source_encounter_id == grand_final.id))
            )

    async def test_correcting_the_grand_final_drops_the_untouched_reset(self) -> None:
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s)
            await self.win(s, grand_final, winner_slot=2)
            await advancement.advance_after_result(s, grand_final)
            await s.commit()
            reset_id = await s.scalar(
                sa.select(EncounterLink.target_encounter_id).where(EncounterLink.source_encounter_id == grand_final.id)
            )
            self.assertIsNotNone(reset_id)

        async with self.Session() as s:
            grand_final = await result.lock_encounter(s, grand_final.id)
            await result.reopen(s, grand_final, actor_user_id=self.users[0], reason="wrong team")
            await advancement.reset_downstream(s, grand_final, actor_user_id=self.users[0])
            await self.win(s, grand_final, winner_slot=1)
            outcome = await advancement.advance_after_result(s, grand_final)
            await s.commit()

            self.assertEqual([], outcome.placed)
            self.assertIsNone(await s.get(Encounter, reset_id))
            self.assertEqual(
                [],
                list(
                    (
                        await s.execute(
                            sa.select(EncounterLink).where(EncounterLink.source_encounter_id == grand_final.id)
                        )
                    )
                    .scalars()
                    .all()
                ),
            )

    async def test_correcting_the_grand_final_keeps_a_reset_that_was_played(self) -> None:
        """A played position is history; the cascade behind the row would eat it."""
        async with self.Session() as s:
            _lower, grand_final = await self._grand_final(s)
            await self.win(s, grand_final, winner_slot=2)
            await advancement.advance_after_result(s, grand_final)
            await s.commit()
            reset_id = await s.scalar(
                sa.select(EncounterLink.target_encounter_id).where(EncounterLink.source_encounter_id == grand_final.id)
            )
            played = EncounterGame(
                encounter_id=reset_id,
                position=1,
                state=enums.EncounterGameState.CONFIRMED,
                result_source=enums.EncounterGameResultSource.ADMIN,
                confirmed_at=sa.func.now(),
            )
            s.add(played)
            await s.flush()
            for index, seat in enumerate(await participants.active_teams(s, reset_id)):
                s.add(
                    EncounterGameTeam(
                        game_id=played.id, encounter_id=reset_id, encounter_team_id=seat.id, score=1 - index
                    )
                )
            await s.commit()
            played_id = played.id

        async with self.Session() as s:
            grand_final = await result.lock_encounter(s, grand_final.id)
            await result.reopen(s, grand_final, actor_user_id=self.users[0], reason="wrong team")
            await advancement.reset_downstream(s, grand_final, actor_user_id=self.users[0])
            await self.win(s, grand_final, winner_slot=1)
            await advancement.advance_after_result(s, grand_final)
            await s.commit()

            reset = await s.get(Encounter, reset_id)
            self.assertIsNotNone(reset, "a Reset with a played position must survive the correction")
            survivor = await s.get(EncounterGame, played_id)
            self.assertEqual(enums.EncounterGameState.CONFIRMED, survivor.state)
            # Each slot keeps the line-up that played the position, retired,
            # beside the occupant the corrected result seated.
            self.assertEqual(
                [(1, False), (1, True), (2, False), (2, True)],
                [(seat.slot, seat.active) for seat in await self.seats_of(s, reset_id)],
            )


class TemplateSlotTests(TestCase):
    """A template names slots and positions, and round-trips the generator."""

    def test_a_generated_bracket_round_trips_through_its_template(self) -> None:
        skeleton = engine.placeholder_bracket(enums.StageType.DOUBLE_ELIMINATION, 4)
        drawn = template.skeleton_to_template(skeleton, upper_seeds=4, lower_seeds=0)

        self.assertEqual([], template.validate_template(drawn, enums.StageType.DOUBLE_ELIMINATION))
        self.assertEqual(
            [[1, 2]] * len(drawn.matches),
            [[slot.slot for slot in match.slots] for match in drawn.matches],
        )
        rebuilt = template.template_to_skeleton(drawn)
        self.assertEqual(
            [pairing.team_ids for pairing in skeleton.pairings],
            [pairing.team_ids for pairing in rebuilt.pairings],
        )
        self.assertEqual(set(skeleton.advancement_edges), set(rebuilt.advancement_edges))

    def test_a_single_elimination_template_may_not_move_a_second_place(self) -> None:
        skeleton = engine.placeholder_bracket(enums.StageType.SINGLE_ELIMINATION, 4)
        drawn = template.skeleton_to_template(skeleton, upper_seeds=4, lower_seeds=0)
        final = max(drawn.matches, key=lambda match: match.round)
        final.slots[1].source_position = 2

        codes = {problem.code for problem in template.validate_template(drawn, enums.StageType.SINGLE_ELIMINATION)}
        self.assertIn("se_shape", codes)
