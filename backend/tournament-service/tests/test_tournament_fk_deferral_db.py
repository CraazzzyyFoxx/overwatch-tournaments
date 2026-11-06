"""The tournament-composite FKs defer, so one transaction can move an encounter, its seats and its bracket rows.

The league merge (spec §15.3 step 3) re-points a day's encounters, ``encounter.team`` seats, teams, stages and bracket
rows to the target tournament. ``encounter.team`` references both ``encounter.encounter (id, tournament_id)`` and
``tournament.team (id, tournament_id)``: no statement order satisfies immediate checks.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from shared import models
from shared.core import enums
from shared.services.encounter.participants import place_team
from shared.tests.encounter_writer_case import EncounterWriterCase

_MOVES = (
    "UPDATE encounter.encounter SET tournament_id = :to WHERE tournament_id = :frm",
    "UPDATE encounter.team SET tournament_id = :to WHERE tournament_id = :frm",
    "UPDATE tournament.team SET tournament_id = :to WHERE tournament_id = :frm",
    "UPDATE tournament.stage SET tournament_id = :to WHERE tournament_id = :frm",
    "UPDATE tournament.bracket_encounter SET tournament_id = :to WHERE tournament_id = :frm",
    "UPDATE tournament.encounter_link SET tournament_id = :to WHERE tournament_id = :frm",
)


class TournamentFkDeferralTests(EncounterWriterCase):
    async def _seed_bracket(self) -> int:
        """A stage, a second encounter, a bracket row and a link on the seeded tournament; a second tournament."""
        async with self.Session() as s:
            stage = models.Stage(
                tournament_id=self.ids["t"], scoring_rule_id=self.ids["rule"], name="S", stage_type="round_robin"
            )
            s.add(stage)
            await s.flush()
            encounter = await self.encounter(s)
            await place_team(s, encounter, slot=1, team_id=self.ids["team0"], name="T0", seed=1, members=[])
            second = models.Encounter(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="E2",
                slot_count=2,
                best_of=3,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(second)
            await s.flush()
            s.add(
                models.BracketEncounter(
                    encounter_id=encounter.id, tournament_id=self.ids["t"], stage_id=stage.id, round=1
                )
            )
            s.add(
                models.EncounterLink(
                    tournament_id=self.ids["t"],
                    source_encounter_id=encounter.id,
                    source_position=1,
                    target_encounter_id=second.id,
                    target_slot=1,
                )
            )
            other = models.Tournament(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                name=f"{self.ids['t']}-b",
                slug=f"fkdefer-{self.ids['t']}-b",
                status=enums.TournamentStatus.LIVE,
            )
            s.add(other)
            await s.commit()
            return other.id

    async def test_deferred_the_whole_tournament_moves_in_one_transaction(self) -> None:
        target = await self._seed_bracket()
        async with self.Session() as s:
            await s.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
            for statement in _MOVES:
                await s.execute(sa.text(statement), {"to": target, "frm": self.ids["t"]})
            await s.commit()

        async with self.Session() as s:
            owners = {
                table: set(
                    (
                        await s.execute(
                            sa.text(f"SELECT DISTINCT tournament_id FROM {table} WHERE tournament_id IN (:a, :b)"),
                            {"a": target, "b": self.ids["t"]},
                        )
                    ).scalars()
                )
                for table in (
                    "encounter.encounter",
                    "encounter.team",
                    "tournament.bracket_encounter",
                    "tournament.encounter_link",
                )
            }
        self.assertEqual({table: {target} for table in owners}, owners)

    async def test_immediate_checks_still_refuse_a_half_move(self) -> None:
        target = await self._seed_bracket()
        async with self.Session() as s:
            with self.assertRaises(IntegrityError):
                await s.execute(sa.text(_MOVES[0]), {"to": target, "frm": self.ids["t"]})
            await s.rollback()
