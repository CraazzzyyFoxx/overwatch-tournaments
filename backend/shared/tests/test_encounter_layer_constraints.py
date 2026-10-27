"""DB guarantees of the encounter layer (spec §13, D55–D66). Needs the test Postgres; skips otherwise."""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.core import enums
from shared.models.encounter import (
    Encounter,
    EncounterGame,
    EncounterGameClaim,
    EncounterGameClaimResult,
    EncounterGameTeam,
    EncounterTeam,
    EncounterTeamMember,
    ScoringRule,
)
from shared.models.encounter.pick_ban import PickBanEntry, PickBanSession
from shared.models.identity.user import User
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.stage import Stage
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

WINS_END = "games >= best_of or max_wins * 2 > best_of"

#: ``players.user.name`` is globally unique and survives its workspace, so the
#: tag has to be unique per TEST, not per process -- ``id(self)`` is reused by
#: CPython as soon as the previous case is collected.
_TAG = itertools.count()


class EncounterLayerConstraintTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        #: Workspaces this test created; every row they own goes with them.
        self.workspaces: list[int] = []
        #: Global player rows, which no workspace cascade reaches.
        self.users: list[int] = []
        self.ids = await self._seed()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            # Workspaces first: a member row is what anchors a roster snapshot,
            # and the player behind it cannot go while the member is still there.
            await s.execute(sa.delete(Workspace).where(Workspace.id.in_(self.workspaces)))
            await s.execute(sa.delete(User).where(User.id.in_(self.users)))
            await s.commit()
        await self.engine.dispose()

    async def _seed(self) -> dict[str, int]:
        tag = f"enc-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            ws = Workspace(slug=tag, name=tag)
            s.add(ws)
            await s.flush()
            self.workspaces.append(ws.id)
            users = [User(name=f"{tag}-{i}") for i in range(4)]
            s.add_all(users)
            await s.flush()
            self.users.extend(u.id for u in users)
            members = [WorkspaceMember(workspace_id=ws.id, player_id=u.id) for u in users]
            s.add_all(members)
            await s.flush()
            tournament = Tournament(
                workspace_id=ws.id, discipline="overwatch", name=tag, slug=tag, status=enums.TournamentStatus.LIVE
            )
            s.add(tournament)
            await s.flush()
            teams = [Team(tournament_id=tournament.id, name=f"T{i}", balancer_name=f"T{i}") for i in range(3)]
            rule = ScoringRule(workspace_id=ws.id, preset="wins", game_formula="win", end_formula=WINS_END)
            s.add_all([*teams, rule])
            await s.flush()
            stage = Stage(
                tournament_id=tournament.id,
                name="S",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=1,
                scoring_rule_id=rule.id,
            )
            s.add(stage)
            await s.flush()
            encounter = Encounter(
                workspace_id=ws.id,
                discipline="overwatch",
                tournament_id=tournament.id,
                scoring_rule_id=rule.id,
                name="E",
                slot_count=2,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(encounter)
            await s.flush()
            s.add(BracketEncounter(encounter_id=encounter.id, tournament_id=tournament.id, stage_id=stage.id, round=1))
            p1 = EncounterTeam(
                encounter_id=encounter.id, tournament_id=tournament.id, slot=1, team_id=teams[0].id, name="T0"
            )
            p2 = EncounterTeam(
                encounter_id=encounter.id, tournament_id=tournament.id, slot=2, team_id=teams[1].id, name="T1"
            )
            s.add_all([p1, p2])
            await s.flush()
            s.add_all(
                [
                    EncounterTeamMember(
                        encounter_id=encounter.id,
                        encounter_team_id=p1.id,
                        active=True,
                        workspace_member_id=members[0].id,
                        display_name_snapshot="a",
                    ),
                    EncounterTeamMember(
                        encounter_id=encounter.id,
                        encounter_team_id=p2.id,
                        active=True,
                        workspace_member_id=members[1].id,
                        display_name_snapshot="b",
                    ),
                ]
            )
            game = EncounterGame(encounter_id=encounter.id, position=1)
            s.add(game)
            await s.flush()
            s.add_all(
                [
                    EncounterGameTeam(game_id=game.id, encounter_id=encounter.id, encounter_team_id=p.id)
                    for p in (p1, p2)
                ]
            )
            await s.flush()
            claim = EncounterGameClaim(
                encounter_id=encounter.id, game_id=game.id, claimant_team_id=p1.id, basis_version=0
            )
            s.add(claim)
            await s.flush()
            s.add_all(
                [
                    EncounterGameClaimResult(claim_id=claim.id, game_id=game.id, encounter_team_id=p1.id, score=3),
                    EncounterGameClaimResult(claim_id=claim.id, game_id=game.id, encounter_team_id=p2.id, score=1),
                ]
            )
            await s.commit()
            return {
                "ws": ws.id,
                "t": tournament.id,
                "rule": rule.id,
                "e": encounter.id,
                "p1": p1.id,
                "p2": p2.id,
                "g": game.id,
                "c": claim.id,
                "team0": teams[0].id,
                "team2": teams[2].id,
                "m0": members[0].id,
                "m1": members[1].id,
            }

    # ── extra rows a single statement needs, built through the same models ──

    async def _second_encounter(self) -> dict[str, int]:
        """Another encounter of the same tournament, with one game of its own."""
        async with self.Session() as s:
            encounter = Encounter(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="E2",
                slot_count=2,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(encounter)
            await s.flush()
            game = EncounterGame(encounter_id=encounter.id, position=1)
            s.add(game)
            await s.commit()
            return {"e2": encounter.id, "g2": game.id}

    async def _third_participation(self) -> int:
        """A participation of the seeded encounter that sits in no game."""
        async with self.Session() as s:
            participation = EncounterTeam(
                encounter_id=self.ids["e"],
                tournament_id=self.ids["t"],
                slot=3,
                team_id=self.ids["team2"],
                name="T2",
            )
            s.add(participation)
            await s.commit()
            return participation.id

    async def _foreign_rule(self) -> int:
        """A scoring rule owned by a different workspace."""
        tag = f"enc-other-{os.getpid()}-{id(self)}"
        async with self.Session() as s:
            ws = Workspace(slug=tag, name=tag)
            s.add(ws)
            await s.flush()
            self.workspaces.append(ws.id)
            rule = ScoringRule(workspace_id=ws.id, preset="wins", game_formula="win", end_formula=WINS_END)
            s.add(rule)
            await s.commit()
            return rule.id

    async def _rejected(self, sql: str, constraint: str, **params: int) -> None:
        async with self.Session() as s:
            with self.assertRaises(DBAPIError) as ctx:  # IntegrityError is a DBAPIError
                await s.execute(sa.text(sql), {**self.ids, **params})
                await s.commit()  # deferred FKs fire at commit
            self.assertIn(constraint, str(ctx.exception))

    async def _scalar(self, sql: str, **params: int):
        async with self.Session() as s:
            return (await s.execute(sa.text(sql), {**self.ids, **params})).scalar_one()

    async def _execute(self, sql: str, **params: int) -> None:
        async with self.Session() as s:
            await s.execute(sa.text(sql), {**self.ids, **params})
            await s.commit()

    # ── 1–2: one occupant per slot, one seat per member ──

    async def test_slot_holds_one_active_participation(self) -> None:
        await self._rejected(
            "INSERT INTO encounter.team (encounter_id, tournament_id, slot, team_id, name)"
            " VALUES (:e, :t, 2, :team2, 'T2')",
            "uq_team_active_slot",
        )

    async def test_member_cannot_sit_in_two_active_participations(self) -> None:
        await self._rejected(
            "INSERT INTO encounter.team_member (encounter_id, encounter_team_id, active, workspace_member_id,"
            " display_name_snapshot) VALUES (:e, :p2, true, :m0, 'x')",
            "uq_team_member_active_member",
        )

    # ── 3: vacating a slot carries the roster with it and keeps the history ──

    async def test_vacating_a_participation_deactivates_its_roster(self) -> None:
        await self._execute("UPDATE encounter.team SET active = false WHERE id = :p2")

        self.assertIs(
            False,
            await self._scalar("SELECT active FROM encounter.team_member WHERE encounter_team_id = :p2"),
            msg="fk_team_member_team ON UPDATE CASCADE should have carried active = false to the roster",
        )
        self.assertEqual(
            1,
            await self._scalar("SELECT count(*) FROM encounter.game_team WHERE encounter_team_id = :p2"),
            msg="a vacated participation keeps the games it played (D55)",
        )

    # ── 4–7: belonging is a composite foreign key (D62) ──

    async def test_a_game_cannot_seat_another_encounters_participation(self) -> None:
        second = await self._second_encounter()
        await self._rejected(
            "INSERT INTO encounter.game_team (game_id, encounter_id, encounter_team_id) VALUES (:g2, :e2, :p1)",
            "fk_game_team_team",
            **second,
        )

    async def test_a_claim_result_cannot_name_a_participation_outside_the_game(self) -> None:
        p3 = await self._third_participation()
        await self._rejected(
            "INSERT INTO encounter.game_claim_result (claim_id, game_id, encounter_team_id) VALUES (:c, :g, :p3)",
            "fk_claim_result_participant",
            p3=p3,
        )

    async def test_a_claim_cannot_come_from_a_participation_outside_the_game(self) -> None:
        p3 = await self._third_participation()
        await self._rejected(
            "INSERT INTO encounter.game_claim (encounter_id, game_id, claimant_team_id, basis_version)"
            " VALUES (:e, :g, :p3, 0)",
            "fk_game_claim_claimant",
            p3=p3,
        )

    async def test_an_encounter_cannot_use_another_workspaces_rule(self) -> None:
        rule2 = await self._foreign_rule()
        await self._rejected(
            "INSERT INTO encounter.encounter (workspace_id, discipline, tournament_id, scoring_rule_id, name,"
            " slot_count, status) VALUES (:ws, 'overwatch', :t, :rule2, 'E3', 2, 'OPEN')",
            "fk_encounter_scoring_rule",
            rule2=rule2,
        )

    # ── 8–10: the shape of a result ──

    async def test_a_confirmed_result_requires_a_completed_encounter(self) -> None:
        await self._rejected(
            "UPDATE encounter.encounter SET result_status = 'confirmed', result_source = 'games' WHERE id = :e",
            "ck_encounter_confirmed_completed",
        )

    async def test_a_confirmed_result_requires_a_source(self) -> None:
        await self._rejected(
            "UPDATE encounter.encounter SET result_status = 'confirmed', status = 'COMPLETED' WHERE id = :e",
            "ck_encounter_confirmed_source",
        )

    async def test_a_participation_score_is_finite(self) -> None:
        await self._rejected(
            "UPDATE encounter.team SET score = 'NaN' WHERE id = :p1",
            "ck_team_score_finite",
        )

    # ── 11–13: what a delete may and may not take with it ──

    async def test_a_participation_cannot_be_deleted_on_its_own(self) -> None:
        # The roster goes first: both it and the game seat object to the delete,
        # and Postgres names whichever deferred constraint it checks first.
        # ``fk_team_member_workspace_member`` has its own case below; this one
        # is about the games the participation played.
        await self._execute("DELETE FROM encounter.team_member WHERE encounter_team_id = :p1")

        await self._rejected("DELETE FROM encounter.team WHERE id = :p1", "fk_game_team_team")

    async def test_a_workspace_member_in_a_roster_cannot_be_deleted(self) -> None:
        await self._rejected(
            "DELETE FROM workspace_member WHERE id = :m0",
            "fk_team_member_workspace_member",
        )

    async def test_deleting_the_source_team_keeps_the_participation(self) -> None:
        await self._execute("DELETE FROM tournament.team WHERE id = :team0")

        self.assertIsNone(await self._scalar("SELECT team_id FROM encounter.team WHERE id = :p1"))
        self.assertEqual("T0", await self._scalar("SELECT name FROM encounter.team WHERE id = :p1"))

    # ── 14–16: cascades from each owner ──

    async def test_deleting_the_encounter_takes_its_whole_layer(self) -> None:
        await self._execute("DELETE FROM encounter.encounter WHERE id = :e")

        for table, column in (
            ("team", "encounter_id"),
            ("team_member", "encounter_id"),
            ("game", "encounter_id"),
            ("game_team", "encounter_id"),
            ("game_claim", "encounter_id"),
            ("game_claim_result", "game_id"),
        ):
            with self.subTest(table=table):
                value = "g" if column == "game_id" else "e"
                self.assertEqual(
                    0,
                    await self._scalar(f"SELECT count(*) FROM encounter.{table} WHERE {column} = :{value}"),
                )

    async def test_deleting_the_encounter_takes_the_board_its_participations_acted_on(self) -> None:
        async with self.Session() as s:
            room = PickBanSession(
                encounter_id=self.ids["e"],
                kind=enums.PickBanKind.HERO,
                pool_json={},
                seed_source=enums.VetoSeedSource.FALLBACK_FIRST_SLOT,
                resolved_sequence_json=[],
                ruleset_json={},
            )
            s.add(room)
            await s.flush()
            team = enums.PickBanActorKind.TEAM
            s.add_all(
                [
                    PickBanEntry(
                        session_id=room.id,
                        encounter_id=self.ids["e"],
                        item_id=1,
                        status=enums.MapPoolEntryStatus.PICKED,
                        picked_by_kind=team,
                        picked_by_team_id=self.ids["p1"],
                    ),
                    PickBanEntry(
                        session_id=room.id,
                        encounter_id=self.ids["e"],
                        item_id=2,
                        status=enums.MapPoolEntryStatus.PROTECTED,
                        protected_by_kind=team,
                        protected_by_team_id=self.ids["p2"],
                    ),
                ]
            )
            await s.commit()

        # Postgres runs the encounter's cascades in trigger-name order, which
        # differs between databases: production reached the participations
        # before the room. Deleting them first in the same transaction is that
        # order -- and the ORM's, when the seats are loaded.
        async with self.Session() as s:
            await s.execute(sa.text("DELETE FROM encounter.team WHERE encounter_id = :e"), self.ids)
            await s.execute(sa.text("DELETE FROM encounter.encounter WHERE id = :e"), self.ids)
            await s.commit()

        self.assertEqual(0, await self._scalar("SELECT count(*) FROM encounter.pick_ban_entry WHERE encounter_id = :e"))

    async def test_deleting_the_tournament_takes_its_encounters(self) -> None:
        await self._execute("DELETE FROM tournament.tournament WHERE id = :t")

        self.assertEqual(0, await self._scalar("SELECT count(*) FROM encounter.encounter WHERE tournament_id = :t"))

    async def test_deleting_the_workspace_takes_its_encounters_and_rules(self) -> None:
        await self._execute("DELETE FROM workspace WHERE id = :ws")

        self.assertEqual(0, await self._scalar("SELECT count(*) FROM encounter.encounter WHERE workspace_id = :ws"))
        self.assertEqual(0, await self._scalar("SELECT count(*) FROM encounter.scoring_rule WHERE workspace_id = :ws"))
