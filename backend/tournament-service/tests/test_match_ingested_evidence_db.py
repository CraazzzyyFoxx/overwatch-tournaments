"""The match layer's decision on ingest evidence, against the real Postgres (P5 Task 5, D95).

``apply_match_evidence`` is the only thing that may turn an observed log into an official result, so every case
here drives it with real sessions and reads what actually landed in ``encounter.*``: the game, its version, the
roster, the journal receipt and the outbox. A ``before_cursor_execute`` hook asserts that no statement ever
touches a ``stats.`` table -- the match layer knows evidence only as an opaque id and revision.
"""

from __future__ import annotations

import ast
import asyncio
import itertools
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy import event as sa_event
from sqlalchemy.exc import DBAPIError

from shared.core import enums
from shared.models import MemberRank
from shared.models.encounter import EncounterGame
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.room_event import EncounterRoomEvent
from shared.models.encounter.team import EncounterTeamMember, EncounterTeamMemberRole
from shared.models.platform.outbox import EventOutbox
from shared.models.platform.realtime import WorkspaceEvent
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.computation import TournamentComputationJob
from shared.models.tournament.player_role import PlayerRole
from shared.models.tournament.stage import Stage
from shared.models.tournament.team import Player
from shared.models.tournament.tournament import Tournament
from shared.repository import CatalogRoleRepository
from shared.schemas.events import MatchIngestedEvent, MatchIngestExtraParticipant, MatchIngestPlacement
from shared.schemas.role import RoleRef
from shared.services.encounter import participants
from shared.services.encounter.result import apply_result
from shared.services.member_rank import member_rank_service
from shared.services.realtime import Resource, Scope, emit
from shared.tests.encounter_writer_case import EncounterWriterCase
from src import schemas
from src.services.admin.tournament import tournament_service
from src.services.encounter import log_evidence, log_evidence_events, room_reconcile
from src.services.encounter.game_correction import game_correction_service
from src.services.encounter.games import GameResultIn, encounter_game_service
from src.services.encounter.log_evidence import ForeignEvidenceError, apply_match_evidence
from src.services.encounter.room_journal import room_history_service

_TAG = itertools.count()
EVIDENCE = 7001
_SERVICE_DIR = Path(log_evidence.__file__).parent


def _outbox_about(ids: dict) -> sa.ColumnElement[bool]:
    """This test's outbox rows: parallel workers write the same ``event_outbox``, so a global count is not ours."""
    pattern = rf'"tournament_id":\s*{ids["t"]}\M|"encounter_id":\s*{ids["e"]}\M'
    return sa.cast(EventOutbox.payload_json, sa.Text).op("~")(pattern)


class _DriverError(Exception):
    """What the asyncpg adapter surfaces: an exception carrying its SQLSTATE."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class EvidenceCase(EncounterWriterCase):
    """Two seated teams (one member each), one open game, ``logs_official`` on."""

    best_of = 1
    logs_official = True

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.statements: list[str] = []
        sa_event.listen(self.engine.sync_engine, "before_cursor_execute", self._record_statement)
        async with self.Session() as s:
            encounter = await self.encounter(s)
            for slot in (1, 2):
                await participants.place_team(
                    s,
                    encounter,
                    slot=slot,
                    team_id=self.ids[f"team{slot - 1}"],
                    name=f"T{slot - 1}",
                    seed=slot,
                    members=[
                        participants.MemberSnapshot(
                            workspace_member_id=self.ids[f"m{slot - 1}"],
                            display_name=f"m{slot - 1}",
                            rank=2500,
                            is_substitute=False,
                            roles=(("player_role", "tank"),),
                        )
                    ],
                )
            game = await encounter_game_service.open_game(s, encounter, position=1)
            (await s.get_one(Tournament, self.ids["t"])).logs_official = self.logs_official
            await s.commit()
            self.game_id = game.id
            self.teams = [seat.id for seat in await participants.active_teams(s, encounter.id)]

    def _record_statement(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(statement)

    async def asyncTearDown(self) -> None:
        sa_event.remove(self.engine.sync_engine, "before_cursor_execute", self._record_statement)
        # Every ORM read of ``Encounter`` carries the model's own ``has_logs`` EXISTS over ``stats.match``; that
        # derived column is the only statement text allowed to name a stats table.
        has_logs = re.compile(r"EXISTS \(SELECT 1\s+FROM stats\.match\s+WHERE[^)]*\)")
        touched = [sql for sql in self.statements if re.search(r"\bstats\.", has_logs.sub("", sql))]
        await super().asyncTearDown()
        self.assertEqual([], touched, "the match layer must never read or write a stats table")

    # -- builders / readers ------------------------------------------------
    def event(
        self,
        revision: int = 1,
        *,
        placements: tuple[int | None, ...] | None = (1, 2),
        extras: tuple[MatchIngestExtraParticipant, ...] = (),
        basis: int = 0,
        evidence_id: int = EVIDENCE,
        encounter_id: int | None = None,
        game_id: int | None = None,
        **overrides,
    ) -> MatchIngestedEvent:
        rows = (
            []
            if placements is None
            else [
                MatchIngestPlacement(encounter_team_id=team, placement=place)
                for team, place in zip(self.teams, placements, strict=True)
            ]
        )
        fields = {
            "event_id": f"match.ingested:{evidence_id}:{revision}",
            "workspace_id": self.ids["ws"],
            "discipline": "overwatch",
            "encounter_id": encounter_id or self.ids["e"],
            "encounter_game_id": game_id or self.game_id,
            "evidence_id": evidence_id,
            "revision": revision,
            "ingest_job_id": 1,
            "basis_game_result_version": basis,
            "placements": rows,
            "extra_participants": list(extras),
        }
        return MatchIngestedEvent(**{**fields, **overrides})

    def extra(
        self, member_key: str, team_index: int = 0, *, role: RoleRef | None | str = "tank", handle: str | None = None
    ):
        if role == "tank":
            role = RoleRef(dimension="player_role", role="tank")
        return MatchIngestExtraParticipant(
            encounter_team_id=self.teams[team_index],
            workspace_member_id=self.ids[member_key],
            handle_snapshot=handle or member_key,
            observed_role=role,
        )

    async def deliver(self, evidence: MatchIngestedEvent) -> str:
        """One consumer transaction: apply, then commit."""
        async with self.Session() as s:
            outcome = await apply_match_evidence(s, evidence)
            await s.commit()
        return outcome

    async def game(self) -> EncounterGame:
        async with self.Session() as s:
            return await s.get_one(EncounterGame, self.game_id, populate_existing=True)

    async def receipts(self, encounter_id: int | None = None) -> list[EncounterRoomEvent]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(EncounterRoomEvent)
                    .where(
                        EncounterRoomEvent.encounter_id == (encounter_id or self.ids["e"]),
                        EncounterRoomEvent.action == "match_ingested",
                    )
                    .order_by(EncounterRoomEvent.id)
                )
            )

    async def roster(self, encounter_id: int | None = None) -> list[EncounterTeamMember]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(EncounterTeamMember)
                    .where(EncounterTeamMember.encounter_id == (encounter_id or self.ids["e"]))
                    .order_by(EncounterTeamMember.id)
                )
            )

    async def outcomes(self) -> list[str]:
        return [row.data["outcome"] for row in await self.receipts()]

    async def assert_untouched(self) -> None:
        game = await self.game()
        self.assertNotEqual(enums.EncounterGameState.CONFIRMED, game.state)
        self.assertEqual(0, game.result_version)
        self.assertIsNone(game.result_source)


class PolicyTests(EvidenceCase):
    logs_official = False

    async def test_logs_official_false_records_a_receipt_and_changes_nothing_official(self) -> None:
        outcome = await self.deliver(self.event())

        self.assertEqual("logs_disabled", outcome)
        await self.assert_untouched()
        (receipt,) = await self.receipts()
        self.assertEqual("stats-service", receipt.source)
        self.assertEqual(
            {
                "game_id": self.game_id,
                "evidence_id": EVIDENCE,
                "revision": 1,
                "event_id": f"match.ingested:{EVIDENCE}:1",
                "basis_game_result_version": 0,
                "accepted_game_result_version": 0,
                "outcome": "logs_disabled",
            },
            receipt.data,
        )
        self.assertEqual("logs_official_off", receipt.reason)
        self.assertEqual(2, len(await self.roster()))

    async def test_logs_official_false_still_seats_a_substitute_but_decides_nothing(self) -> None:
        # The roster is owner policy independent of ``logs_official`` (P4 seated log substitutes always).
        async with self.Session() as s:
            await member_rank_service.set_ranks(
                s,
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                workspace_member_id=self.ids["m2"],
                ranks={"tank": 2500},
            )
            await s.commit()
        outcome = await self.deliver(self.event(extras=(self.extra("m2"),)))

        self.assertEqual("applied_roster_only", outcome)
        await self.assert_untouched()
        (receipt,) = await self.receipts()
        self.assertEqual("logs_official_off", receipt.reason)
        (added,) = [row for row in await self.roster() if row.workspace_member_id == self.ids["m2"]]
        self.assertTrue(added.is_substitute)
        self.assertEqual(self.teams[0], added.encounter_team_id)

    async def test_a_later_toggle_does_not_replay_rejected_evidence(self) -> None:
        await self.deliver(self.event())
        async with self.Session() as s:
            (await s.get_one(Tournament, self.ids["t"])).logs_official = True
            await s.commit()

        self.assertEqual("duplicate", await self.deliver(self.event()))
        await self.assert_untouched()
        self.assertEqual(["logs_disabled"], await self.outcomes())

    async def test_a_lower_revision_is_stale_even_after_a_disabled_receipt(self) -> None:
        await self.deliver(self.event(2))
        self.assertEqual("stale_revision", await self.deliver(self.event(1)))
        self.assertEqual(["logs_disabled"], await self.outcomes())

    async def test_the_journal_reads_a_receipt_with_the_systems_voice(self) -> None:
        await self.deliver(self.event())
        async with self.Session() as s:
            history = await room_history_service.list_history(s, self.ids["e"])
        (entry,) = [row for row in history.entries if row.action == "match_ingested"]
        self.assertEqual("system", entry.source)
        self.assertEqual("logs_disabled", entry.data["outcome"])
        self.assertEqual(1, entry.data["revision"])


class AcceptanceTests(EvidenceCase):
    async def test_valid_evidence_confirms_the_game_as_admin_log_with_the_normal_cascade(self) -> None:
        jobs_before = await self._jobs()
        outbox_before = await self._outbox_routing_keys()

        outcome = await self.deliver(self.event(placements=(2, 1)))

        self.assertEqual("accepted", outcome)
        game = await self.game()
        self.assertEqual(enums.EncounterGameState.CONFIRMED, game.state)
        self.assertEqual(enums.EncounterGameResultSource.ADMIN_LOG, game.result_source)
        self.assertEqual(1, game.result_version)
        async with self.Session() as s:
            encounter = await s.get_one(Encounter, self.ids["e"], populate_existing=True)
            seats = {seat.id: seat for seat in await participants.active_teams(s, self.ids["e"])}
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, encounter.result_status)
        self.assertEqual(
            {self.teams[0]: 2, self.teams[1]: 1}, {team_id: seat.placement for team_id, seat in seats.items()}
        )
        # one version step, the recalculation job and the completion announcement the normal confirm owes
        self.assertEqual(jobs_before + 1, await self._jobs())
        self.assertIn(
            "tournament.encounter.completed",
            (await self._outbox_routing_keys())[len(outbox_before) :],
        )
        (receipt,) = await self.receipts()
        self.assertEqual("accepted", receipt.data["outcome"])
        self.assertEqual(1, receipt.data["accepted_game_result_version"])
        self.assertEqual(0, receipt.data["basis_game_result_version"])

    async def test_a_game_result_audit_row_names_the_log_source(self) -> None:
        await self.deliver(self.event())
        async with self.Session() as s:
            history = await room_history_service.list_history(s, self.ids["e"])
        sources = {row.action: row.source for row in history.entries if row.origin == "result"}
        self.assertEqual("system", sources["game_confirm"])

    async def _jobs(self) -> int:
        async with self.Session() as s:
            return await s.scalar(
                sa.select(sa.func.count())
                .select_from(TournamentComputationJob)
                .where(TournamentComputationJob.tournament_id == self.ids["t"])
            )

    async def _outbox_routing_keys(self) -> list[str]:
        async with self.Session() as s:
            query = sa.select(EventOutbox.routing_key).where(_outbox_about(self.ids)).order_by(EventOutbox.id)
            return list(await s.scalars(query))


class PrecedenceTests(EvidenceCase):
    async def test_an_admin_result_is_never_overwritten_even_when_the_numbers_agree(self) -> None:
        await self._record(enums.EncounterGameResultSource.ADMIN)
        outcome = await self.deliver(self.event(basis=1, placements=(1, 2)))

        self.assertEqual("result_locked", outcome)
        game = await self.game()
        self.assertEqual(enums.EncounterGameResultSource.ADMIN, game.result_source)
        self.assertEqual(1, game.result_version)

    async def test_a_captain_agreement_stands(self) -> None:
        await self._record(enums.EncounterGameResultSource.CAPTAIN_AGREEMENT)
        self.assertEqual("result_locked", await self.deliver(self.event(basis=1)))
        self.assertEqual(enums.EncounterGameResultSource.CAPTAIN_AGREEMENT, (await self.game()).result_source)

    async def test_a_confirmed_encounter_blocks_an_unplayed_game(self) -> None:
        """An import (or admin series result) decides the encounter itself, with no confirmed game."""
        async with self.Session() as s:
            encounter = await self.encounter(s)
            await apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.IMPORT,
                totals={self.teams[0]: 1.0, self.teams[1]: 0.0},
                placements={self.teams[0]: 1, self.teams[1]: 2},
                action=enums.EncounterResultAuditAction.IMPORT,
                audit_source="import",
                actor_user_id=None,
                reason="test",
            )
            await s.commit()

        self.assertEqual("result_locked", await self.deliver(self.event()))
        await self.assert_untouched()

    async def test_a_corrected_game_takes_a_fresh_reparse_on_its_new_basis(self) -> None:
        await self.deliver(self.event(1, placements=(1, 2)))
        async with self.Session() as s:
            await game_correction_service.correct_game(
                s,
                self.ids["e"],
                game_id=self.game_id,
                results=[
                    GameResultIn(encounter_team_id=self.teams[0], score=0),
                    GameResultIn(encounter_team_id=self.teams[1], score=3),
                ],
                actor_user_id=None,
                reason="wrong winner",
                audit=AsyncMock(),
            )
        # the correction is an organizer decision on an accepted game: still locked for evidence
        self.assertEqual("result_locked", await self.deliver(self.event(2, placements=(1, 2), basis=2)))
        self.assertEqual(2, (await self.game()).result_version)

    async def test_a_cancelled_game_cannot_take_evidence(self) -> None:
        async with self.Session() as s:
            game = await s.get_one(EncounterGame, self.game_id)
            game.state = enums.EncounterGameState.CANCELLED
            await s.commit()
        self.assertEqual("result_locked", await self.deliver(self.event()))

    async def _record(self, source: enums.EncounterGameResultSource) -> None:
        async with self.Session() as s:
            encounter = await self.encounter(s)
            game = await s.get_one(EncounterGame, self.game_id)
            await encounter_game_service.record_result(
                s,
                encounter,
                game,
                results=[
                    GameResultIn(encounter_team_id=self.teams[0], score=3),
                    GameResultIn(encounter_team_id=self.teams[1], score=1),
                ],
                source=source,
                actor_user_id=None,
            )
            await s.commit()


class OrderingTests(EvidenceCase):
    async def test_rev2_then_rev1_keeps_rev2_and_journals_one_receipt(self) -> None:
        self.assertEqual("accepted", await self.deliver(self.event(2, placements=(2, 1))))
        self.assertEqual("stale_revision", await self.deliver(self.event(1, placements=(1, 2))))

        self.assertEqual(["accepted"], await self.outcomes())
        self.assertEqual(1, (await self.game()).result_version)

    async def test_rev1_then_rev2_leaves_the_first_accepted_result_standing(self) -> None:
        self.assertEqual("accepted", await self.deliver(self.event(1, placements=(1, 2))))
        self.assertEqual("result_locked", await self.deliver(self.event(2, placements=(2, 1), basis=1)))

        game = await self.game()
        self.assertEqual(1, game.result_version)
        async with self.Session() as s:
            seats = {seat.id: seat.placement for seat in await participants.active_teams(s, self.ids["e"])}
        self.assertEqual({self.teams[0]: 1, self.teams[1]: 2}, seats)
        self.assertEqual(["accepted", "result_locked"], await self.outcomes())

    async def test_the_same_event_twice_changes_nothing_the_second_time(self) -> None:
        evidence = self.event()
        self.assertEqual("accepted", await self.deliver(evidence))
        self.assertEqual("duplicate", await self.deliver(evidence))
        self.assertEqual(1, len(await self.receipts()))
        self.assertEqual(1, (await self.game()).result_version)

    async def test_the_same_revision_under_another_event_id_is_a_duplicate(self) -> None:
        self.assertEqual("accepted", await self.deliver(self.event(1)))
        self.assertEqual("duplicate", await self.deliver(self.event(1, event_id="match.ingested:resend")))
        self.assertEqual(1, len(await self.receipts()))

    async def test_another_evidence_id_has_its_own_high_water(self) -> None:
        await self.deliver(self.event(5, evidence_id=EVIDENCE + 1))
        # not "stale_revision": this evidence never delivered anything; the game's accepted result locks it
        self.assertEqual("result_locked", await self.deliver(self.event(1, evidence_id=EVIDENCE)))

    async def test_a_higher_revision_cannot_overwrite_through_a_stale_basis(self) -> None:
        async with self.Session() as s:
            (await s.get_one(EncounterGame, self.game_id)).result_version = 1  # an organizer decision moved the basis
            await s.commit()

        self.assertEqual("stale_basis", await self.deliver(self.event(2, basis=0)))

        game = await self.game()
        self.assertEqual(1, game.result_version)
        self.assertNotEqual(enums.EncounterGameState.CONFIRMED, game.state)
        (receipt,) = await self.receipts()
        self.assertEqual(1, receipt.data["accepted_game_result_version"], "the current version is recorded unchanged")

    async def test_a_rollback_after_the_result_leaves_neither_result_nor_receipt(self) -> None:
        evidence = self.event()
        async with self.Session() as s:
            self.assertEqual("accepted", await apply_match_evidence(s, evidence))
            await s.rollback()  # the commit never happened

        await self.assert_untouched()
        self.assertEqual([], await self.receipts())
        self.assertEqual("accepted", await self.deliver(evidence))
        self.assertEqual(1, (await self.game()).result_version)
        self.assertEqual(1, len(await self.receipts()))

    async def test_an_old_receipt_is_found_below_five_hundred_unrelated_rows(self) -> None:
        await self.deliver(self.event(3))
        async with self.Session() as s:
            s.add_all(
                [
                    EncounterRoomEvent(encounter_id=self.ids["e"], action="ready_marked", source="admin", data={})
                    for _ in range(600)
                ]
            )
            await s.commit()
        async with self.Session() as s:
            window = await room_history_service.list_history(s, self.ids["e"], limit=500)
        self.assertNotIn("match_ingested", [row.action for row in window.entries], "the receipt left the UI window")

        self.assertEqual("stale_revision", await self.deliver(self.event(2)))
        self.assertEqual("duplicate", await self.deliver(self.event(3, event_id="match.ingested:other")))


class RosterTests(EvidenceCase):
    ROLE = RoleRef(dimension="player_role", role="tank")

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:  # the workspace canon rank the existing rank rules resolve from
            await member_rank_service.set_ranks(
                s,
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                workspace_member_id=self.ids["m2"],
                ranks={"tank": 2500},
            )
            await s.commit()

    async def test_a_tournament_extra_is_seated_once_as_a_substitute_with_the_observed_role(self) -> None:
        outcome = await self.deliver(self.event(extras=(self.extra("m2", role=self.ROLE, handle="Ghost#1"),)))

        self.assertEqual("accepted", outcome)
        added = [row for row in await self.roster() if row.workspace_member_id == self.ids["m2"]]
        self.assertEqual(1, len(added))
        (member,) = added
        self.assertTrue(member.is_substitute)
        self.assertEqual(self.teams[0], member.encounter_team_id)
        self.assertEqual("Ghost#1", member.display_name_snapshot)
        self.assertEqual(2500, member.rank, "the rank comes from the workspace canon, not from the observation")
        async with self.Session() as s:
            roles = (
                await s.scalars(
                    sa.select(EncounterTeamMemberRole).where(EncounterTeamMemberRole.team_member_id == member.id)
                )
            ).all()
        self.assertEqual(1, len(roles))
        # a redelivery and a later revision seat nobody twice
        self.assertEqual("duplicate", await self.deliver(self.event(extras=(self.extra("m2"),))))
        self.assertEqual("result_locked", await self.deliver(self.event(2, basis=1, extras=(self.extra("m2"),))))
        self.assertEqual(3, len(await self.roster()))

    async def test_a_confirmed_game_still_seats_a_new_substitute_without_touching_the_result(self) -> None:
        self.assertEqual("accepted", await self.deliver(self.event(placements=(1, 2))))

        outcome = await self.deliver(self.event(2, basis=1, placements=(2, 1), extras=(self.extra("m2"),)))

        self.assertEqual("applied_roster_only", outcome)
        game = await self.game()
        self.assertEqual(1, game.result_version)
        self.assertEqual(enums.EncounterGameResultSource.ADMIN_LOG, game.result_source)
        receipt = (await self.receipts())[-1]
        self.assertEqual("game_confirmed", receipt.reason)
        self.assertEqual(3, len(await self.roster()))

    async def test_a_member_already_on_that_team_is_idempotent(self) -> None:
        async with self.Session() as s:
            participation = (await participants.active_teams(s, self.ids["e"]))[0]
            await participants.add_substitute(
                s,
                participation,
                participants.MemberSnapshot(
                    workspace_member_id=self.ids["m2"], display_name="m2", rank=None, is_substitute=True, roles=()
                ),
            )
            await s.commit()

        self.assertEqual("accepted", await self.deliver(self.event(extras=(self.extra("m2"),))))
        self.assertEqual(3, len(await self.roster()))

    async def test_a_member_seated_on_the_other_team_is_a_contradiction_and_changes_nothing(self) -> None:
        outcome = await self.deliver(self.event(extras=(self.extra("m1", team_index=0),)))

        self.assertEqual("owner_policy_refused", outcome)
        await self.assert_untouched()
        self.assertEqual(2, len(await self.roster()))
        (receipt,) = await self.receipts()
        self.assertEqual("extra_member_contradiction", receipt.reason)

    async def test_a_foreign_workspace_member_is_refused(self) -> None:
        other = await self._seed()
        self.ids["foreign"] = other["m0"]

        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("foreign"),))))
        self.assertEqual(2, len(await self.roster()))
        await self.assert_untouched()

    async def test_a_removed_member_is_refused_and_never_revived(self) -> None:
        async with self.Session() as s:
            member = await s.get_one(WorkspaceMember, self.ids["m2"])
            member.removed_at = sa.func.now()
            await s.commit()

        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2"),))))
        async with self.Session() as s:
            self.assertIsNotNone((await s.get_one(WorkspaceMember, self.ids["m2"], populate_existing=True)).removed_at)

    async def test_an_observation_only_anchor_is_seated_and_stays_observation_only(self) -> None:
        async with self.Session() as s:
            member = await s.get_one(WorkspaceMember, self.ids["m2"])
            member.observed_only = True
            await s.commit()

        self.assertEqual("accepted", await self.deliver(self.event(extras=(self.extra("m2"),))))
        self.assertEqual(3, len(await self.roster()))
        async with self.Session() as s:
            anchor = await s.get_one(WorkspaceMember, self.ids["m2"], populate_existing=True)
        self.assertTrue(anchor.observed_only and anchor.removed_at is None, "seating a substitute admits nobody")

    async def test_a_removed_observation_only_anchor_is_still_refused(self) -> None:
        async with self.Session() as s:
            member = await s.get_one(WorkspaceMember, self.ids["m2"])
            member.observed_only = True
            member.removed_at = sa.func.now()
            await s.commit()

        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2"),))))
        self.assertEqual(2, len(await self.roster()))

    async def test_an_observed_role_the_workspace_does_not_own_refuses_everything(self) -> None:
        bad = RoleRef(dimension="player_role", role="no_such_role")
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2", role=bad),))))
        self.assertEqual(2, len(await self.roster()))
        await self.assert_untouched()

    async def test_a_foreign_dimension_is_refused(self) -> None:
        bad = RoleRef(dimension="hero_pool", role="tank")
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2", role=bad),))))

    async def test_a_team_outside_the_game_is_refused(self) -> None:
        stray = MatchIngestExtraParticipant(
            encounter_team_id=self.teams[1] + 999_999, workspace_member_id=self.ids["m2"], handle_snapshot="x"
        )
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(stray,))))

    async def test_a_roster_survives_a_refused_result_and_tells_the_readers(self) -> None:
        """Valid extras are judged on their own rules: seated, journaled as roster-only, signalled."""
        with (
            patch.object(log_evidence, "emit", AsyncMock()) as emit,
            patch.object(log_evidence, "emit_pick_ban_update", AsyncMock()) as room,
            patch.object(log_evidence, "enqueue_tournament_recalculation", AsyncMock()) as recalculation,
        ):
            outcome = await self.deliver(self.event(placements=(1, None), extras=(self.extra("m2"),)))

        self.assertEqual("applied_roster_only", outcome)
        await self.assert_untouched()
        self.assertEqual(3, len(await self.roster()))
        (receipt,) = await self.receipts()
        self.assertEqual("placements_missing", receipt.reason)
        emit.assert_awaited_once()
        room.assert_awaited_once()
        recalculation.assert_not_awaited()  # nothing in the standings moved

    async def test_a_refusal_that_seats_nobody_signals_nothing(self) -> None:
        with (
            patch.object(log_evidence, "emit", AsyncMock()) as emit,
            patch.object(log_evidence, "emit_pick_ban_update", AsyncMock()) as room,
        ):
            self.assertEqual("result_incomplete", await self.deliver(self.event(placements=(1, None))))
        emit.assert_not_awaited()
        room.assert_not_awaited()

    async def test_an_extra_without_any_role_is_refused(self) -> None:
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2", role=None),))))
        (receipt,) = await self.receipts()
        self.assertEqual("extra_role_unknown", receipt.reason)
        self.assertEqual(2, len(await self.roster()))

    async def test_an_extra_no_rank_rule_can_rank_is_refused(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(MemberRank).where(MemberRank.workspace_member_id == self.ids["m2"]))
            await s.commit()
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2"),))))
        (receipt,) = await self.receipts()
        self.assertEqual("extra_rank_unknown", receipt.reason)
        self.assertEqual(2, len(await self.roster()))

    async def test_the_tournament_roster_row_is_the_rank_authority(self) -> None:
        async with self.Session() as s:
            s.add(
                Player(
                    tournament_id=self.ids["t"],
                    team_id=self.ids["team0"],
                    workspace_member_id=self.ids["m2"],
                    name="m2",
                    rank=1234,
                )
            )
            await s.commit()
        self.assertEqual("accepted", await self.deliver(self.event(extras=(self.extra("m2"),))))
        (member,) = [row for row in await self.roster() if row.workspace_member_id == self.ids["m2"]]
        self.assertEqual(1234, member.rank)

    async def test_an_unranked_roster_row_stays_unranked(self) -> None:
        """A NULL roster rank is "not specified", not missing: no member-rank fallback, no refusal."""
        async with self.Session() as s:
            await s.execute(sa.delete(MemberRank).where(MemberRank.workspace_member_id == self.ids["m2"]))
            s.add(
                Player(
                    tournament_id=self.ids["t"],
                    team_id=self.ids["team0"],
                    workspace_member_id=self.ids["m2"],
                    name="m2",
                    rank=None,
                )
            )
            await s.commit()
        self.assertEqual("accepted", await self.deliver(self.event(extras=(self.extra("m2"),))))
        (member,) = [row for row in await self.roster() if row.workspace_member_id == self.ids["m2"]]
        self.assertIsNone(member.rank)

    async def test_a_member_rostered_on_another_team_is_refused(self) -> None:
        async with self.Session() as s:
            s.add(
                Player(
                    tournament_id=self.ids["t"],
                    team_id=self.ids["team2"],
                    workspace_member_id=self.ids["m2"],
                    name="m2",
                    rank=1234,
                )
            )
            await s.commit()
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2"),))))
        (receipt,) = await self.receipts()
        self.assertEqual("extra_member_other_team", receipt.reason)


class MixOwnerTests(EvidenceCase):
    async def test_a_mix_adds_nobody_and_decides_nothing(self) -> None:
        async with self.Session() as s:
            mix = await self.mix_encounter(s)
            game = await encounter_game_service.open_game(s, mix, position=1)
            seats = [seat.id for seat in await participants.active_teams(s, mix.id)]
            await s.commit()
            mix_id, mix_game = mix.id, game.id
        evidence = MatchIngestedEvent(
            workspace_id=self.ids["ws"],
            discipline="overwatch",
            encounter_id=mix_id,
            encounter_game_id=mix_game,
            evidence_id=EVIDENCE,
            revision=1,
            ingest_job_id=1,
            basis_game_result_version=0,
            placements=[
                MatchIngestPlacement(encounter_team_id=seats[0], placement=1),
                MatchIngestPlacement(encounter_team_id=seats[1], placement=2),
            ],
            extra_participants=[
                MatchIngestExtraParticipant(
                    encounter_team_id=seats[0], workspace_member_id=self.ids["m2"], handle_snapshot="m2"
                )
            ],
        )

        self.assertEqual("owner_policy_refused", await self.deliver(evidence))

        async with self.Session() as s:
            game = await s.get_one(EncounterGame, mix_game)
        self.assertNotEqual(enums.EncounterGameState.CONFIRMED, game.state)
        self.assertEqual([], await self.roster(mix_id))
        (receipt,) = await self.receipts(mix_id)
        self.assertEqual("owner_not_tournament", receipt.reason)


class ResultInputTests(EvidenceCase):
    async def test_an_objectiveless_games_null_placements_decide_nothing(self) -> None:
        """Push/Clash: the decoder claims no placements for the 0:0 artifact, so no draw is ever recorded."""
        self.assertEqual("result_incomplete", await self.deliver(self.event(placements=(None, None))))
        (receipt,) = await self.receipts()
        self.assertEqual("placements_missing", receipt.reason)
        await self.assert_untouched()

    async def test_missing_placements_are_refused_and_nothing_is_invented(self) -> None:
        self.assertEqual("result_incomplete", await self.deliver(self.event(placements=(1, None))))
        self.assertEqual("result_incomplete", await self.deliver(self.event(2, placements=None)))
        await self.assert_untouched()

    async def test_a_team_set_that_changed_makes_the_binding_stale(self) -> None:
        evidence = self.event().model_copy(
            update={
                "placements": [
                    MatchIngestPlacement(encounter_team_id=self.teams[0], placement=1),
                    MatchIngestPlacement(encounter_team_id=self.teams[1] + 999_999, placement=2),
                ]
            }
        )
        self.assertEqual("stale_basis", await self.deliver(evidence))
        await self.assert_untouched()

    async def test_a_foreign_workspace_event_is_malformed_and_leaves_no_receipt(self) -> None:
        other = await self._seed()
        with self.assertRaises(ForeignEvidenceError):
            await self.deliver(self.event(workspace_id=other["ws"]))
        with self.assertRaises(ForeignEvidenceError):
            await self.deliver(self.event(discipline="lol"))
        await self.assert_untouched()
        self.assertEqual([], await self.receipts(), "no receipt, so no watermark for a corrected delivery to hit")
        self.assertEqual("accepted", await self.deliver(self.event()))

    async def test_a_deleted_game_or_encounter_is_ignored_without_a_receipt(self) -> None:
        self.assertEqual("ignored", await self.deliver(self.event(game_id=self.game_id + 10_000_000)))
        self.assertEqual("ignored", await self.deliver(self.event(encounter_id=self.ids["e"] + 10_000_000)))
        self.assertEqual([], await self.receipts())


class OrganizerColumnTests(EvidenceCase):
    """A points rule with a mandatory organizer column: logs never fill it in."""

    preset = "points"
    game_formula = "place_pts + kills"
    end_formula = "games >= best_of"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            from shared.models.encounter import ScoringRule

            rule = await s.get_one(ScoringRule, self.ids["rule"])
            rule.placement_points = [10.0, 6.0]
            rule.columns = [{"key": "kills", "label": "Kills", "public": True, "better": "high"}]
            await s.commit()

    async def test_missing_organizer_inputs_are_refused_while_nothing_changes(self) -> None:
        self.assertEqual("result_incomplete", await self.deliver(self.event()))
        await self.assert_untouched()
        (receipt,) = await self.receipts()
        self.assertEqual("ffa_result_missing_stat", receipt.reason)


class ConsumerTests(EvidenceCase):
    async def test_the_consumer_commits_once_and_returns_the_outcome(self) -> None:
        with patch.object(log_evidence_events.db, "async_session_maker", self.Session):
            outcome = await log_evidence_events.process_match_ingested(self.event().model_dump())
        self.assertEqual("accepted", outcome)
        self.assertEqual(1, (await self.game()).result_version)
        self.assertEqual(1, len(await self.receipts()))

    async def test_a_malformed_foreign_event_raises_for_the_dead_letter_queue(self) -> None:
        with patch.object(log_evidence_events.db, "async_session_maker", self.Session):
            with self.assertRaises(ValidationError):
                await log_evidence_events.process_match_ingested({"event_type": "match_ingested", "revision": 0})
        self.assertEqual([], await self.receipts())

    async def test_a_transient_database_failure_requeues_and_the_redelivery_applies_once(self) -> None:
        failure = DBAPIError("SELECT 1", {}, _DriverError("40P01"))
        data = self.event().model_dump()
        with patch.object(log_evidence_events.db, "async_session_maker", self.Session):
            with patch.object(log_evidence_events, "apply_match_evidence", AsyncMock(side_effect=failure)):
                self.assertIsNone(await log_evidence_events.process_match_ingested(data))
            await self.assert_untouched()
            self.assertEqual([], await self.receipts())

            self.assertEqual("accepted", await log_evidence_events.process_match_ingested(data))
        self.assertEqual(1, (await self.game()).result_version)
        self.assertEqual(1, len(await self.receipts()))

    async def test_a_permanent_database_defect_is_rejected_not_requeued(self) -> None:
        failure = DBAPIError("SELECT 1", {}, _DriverError("42703"))
        with patch.object(log_evidence_events.db, "async_session_maker", self.Session):
            with patch.object(log_evidence_events, "apply_match_evidence", AsyncMock(side_effect=failure)):
                with self.assertRaises(DBAPIError):
                    await log_evidence_events.process_match_ingested(self.event().model_dump())

    def test_the_asyncpg_error_shapes_are_classified(self) -> None:
        # the adapter wraps the asyncpg exception: the SQLSTATE sits on ``orig`` or on its ``__cause__``
        wrapped = Exception("adapter")
        wrapped.__cause__ = _DriverError("40001")
        for orig in (_DriverError("40001"), _DriverError("40P01"), _DriverError("08003"), wrapped):
            self.assertTrue(log_evidence_events.is_transient(DBAPIError("s", {}, orig)), orig)
        self.assertTrue(log_evidence_events.is_transient(DBAPIError("s", {}, Exception(), connection_invalidated=True)))
        for orig in (_DriverError("23505"), _DriverError("42P01"), Exception("no state")):
            self.assertFalse(log_evidence_events.is_transient(DBAPIError("s", {}, orig)), orig)

    async def _challonge_pushes(self) -> list[dict]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(EventOutbox.payload_json).where(
                        EventOutbox.event_id.startswith(f"challonge_push:{self.ids['e']}:")
                    )
                )
            )

    async def test_an_accepted_completing_result_stages_its_challonge_push_in_the_same_commit(self) -> None:
        with (
            patch.object(log_evidence_events.db, "async_session_maker", self.Session),
            patch(
                "src.services.encounter.settle.resolve_encounter_challonge",
                AsyncMock(side_effect=lambda _s, ids: dict.fromkeys(ids, 1)),
            ),
        ):
            self.assertEqual("accepted", await log_evidence_events.process_match_ingested(self.event().model_dump()))
            self.assertEqual("duplicate", await log_evidence_events.process_match_ingested(self.event().model_dump()))
        async with self.Session() as s:
            version = (await s.get_one(Encounter, self.ids["e"])).result_version
        self.assertEqual([version], [push["result_version"] for push in await self._challonge_pushes()])

    async def test_no_push_when_nothing_became_official(self) -> None:
        with (
            patch.object(log_evidence_events.db, "async_session_maker", self.Session),
            patch(
                "src.services.encounter.settle.resolve_encounter_challonge",
                AsyncMock(side_effect=lambda _s, ids: dict.fromkeys(ids, 1)),
            ),
        ):
            await log_evidence_events.process_match_ingested(self.event(placements=(1, None)).model_dump())
        self.assertEqual([], await self._challonge_pushes())

    async def test_the_consumer_modules_import_no_stats_package(self) -> None:
        for module in ("log_evidence.py", "log_evidence_events.py"):
            tree = ast.parse((_SERVICE_DIR / module).read_text(encoding="utf-8"))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
                    imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
                elif isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
            self.assertEqual([], [name for name in imported if re.search(r"(^|\.)stats(\.|_|$)", name)], module)


class TournamentFlagTests(EvidenceCase):
    """``logs_official`` is off by default and flips only through the owner update path."""

    logs_official = False

    async def test_a_new_tournament_row_defaults_to_off(self) -> None:
        async with self.Session() as s:
            tag = f"flag-{os.getpid()}-{next(_TAG)}"
            row = Tournament(workspace_id=self.ids["ws"], name=tag, slug=tag)
            s.add(row)
            await s.flush()
            self.assertIs(False, row.logs_official)
            create = schemas.TournamentCreate(
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                name="n",
                start_date="2026-01-01",
                end_date="2026-01-02",
            )
            self.assertIs(False, create.logs_official)
            await s.rollback()

    async def test_the_update_path_persists_and_reads_the_flag(self) -> None:
        async with self.Session() as s:
            tournament = await tournament_service.update_tournament(
                s, self.ids["t"], schemas.TournamentUpdate(logs_official=True)
            )
            self.assertTrue(tournament.logs_official)
        async with self.Session() as s:
            self.assertTrue((await s.get_one(Tournament, self.ids["t"], populate_existing=True)).logs_official)

    async def test_an_untouched_update_leaves_the_flag_alone(self) -> None:
        async with self.Session() as s:
            await tournament_service.update_tournament(
                s, self.ids["t"], schemas.TournamentUpdate(name=f"renamed-{next(_TAG)}")
            )
        async with self.Session() as s:
            self.assertFalse((await s.get_one(Tournament, self.ids["t"], populate_existing=True)).logs_official)


class BracketStateTests(EvidenceCase):
    """The live-encounter gate and settlement refusals, with the encounter inside a real stage."""

    async def _in_stage(self, *, published: bool) -> None:
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="Playoff",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=1,
                is_published=published,
            )
            s.add(stage)
            await s.flush()
            s.add(BracketEncounter(encounter_id=self.ids["e"], tournament_id=self.ids["t"], stage_id=stage.id, round=1))
            await s.commit()

    async def test_a_preview_bracket_takes_no_result_and_no_roster_change(self) -> None:
        await self._in_stage(published=False)

        outcome = await self.deliver(self.event(extras=(self.extra("m2"),)))

        self.assertEqual("owner_policy_refused", outcome)
        await self.assert_untouched()
        self.assertEqual(2, len(await self.roster()))
        (receipt,) = await self.receipts()
        self.assertEqual("encounter_preview", receipt.reason)

    async def test_a_published_bracket_accepts_the_same_evidence(self) -> None:
        await self._in_stage(published=True)
        self.assertEqual("accepted", await self.deliver(self.event()))

    async def test_a_level_finish_in_an_elimination_bracket_is_journaled_not_dead_lettered(self) -> None:
        await self._in_stage(published=True)
        before = await self._outbox_count()

        outcome = await self.deliver(self.event(placements=(1, 1)))

        self.assertEqual("result_incomplete", outcome)
        await self.assert_untouched()
        async with self.Session() as s:
            encounter = await s.get_one(Encounter, self.ids["e"], populate_existing=True)
        self.assertNotEqual(enums.EncounterResultStatus.CONFIRMED, encounter.result_status)
        self.assertEqual(before, await self._outbox_count(), "the tentative cascade left no outbox row")
        (receipt,) = await self.receipts()
        self.assertEqual("bracket_tie", receipt.reason)
        self.assertEqual(0, receipt.data["accepted_game_result_version"])

    async def test_a_level_finish_keeps_valid_roster_additions(self) -> None:
        await self._in_stage(published=True)
        async with self.Session() as s:
            await member_rank_service.set_ranks(
                s,
                workspace_id=self.ids["ws"],
                discipline="overwatch",
                workspace_member_id=self.ids["m2"],
                ranks={"tank": 2500},
            )
            await s.commit()

        outcome = await self.deliver(self.event(placements=(1, 1), extras=(self.extra("m2"),)))

        self.assertEqual("applied_roster_only", outcome)
        await self.assert_untouched()
        self.assertEqual(3, len(await self.roster()))

    async def _outbox_count(self) -> int:
        async with self.Session() as s:
            return await s.scalar(sa.select(sa.func.count()).select_from(EventOutbox).where(_outbox_about(self.ids)))


class RosterRoleAuthorityTests(EvidenceCase):
    """A tournament roster row's rated assignment (root or sub-role) outranks and never yields to the observation."""

    async def _rostered_as(self, code: str, *, rank: int = 1234) -> None:
        async with self.Session() as s:
            role = await CatalogRoleRepository().resolve(
                s, discipline="overwatch", workspace_id=self.ids["ws"], dimension="player_role", code=code
            )
            player = Player(
                tournament_id=self.ids["t"],
                team_id=self.ids["team0"],
                workspace_member_id=self.ids["m2"],
                name="m2",
                rank=rank,
            )
            s.add(player)
            await s.flush()
            s.add(PlayerRole(player_id=player.id, dimension_id=role.dimension_id, role_id=role.id))
            await s.commit()

    async def _seated_roles(self) -> list[str]:
        async with self.Session() as s:
            (member,) = [row for row in await self.roster() if row.workspace_member_id == self.ids["m2"]]
            rows = (
                await s.scalars(
                    sa.select(EncounterTeamMemberRole).where(EncounterTeamMemberRole.team_member_id == member.id)
                )
            ).all()
            return [row.role for row in rows]

    async def test_a_root_assignment_wins_over_a_different_observed_role(self) -> None:
        await self._rostered_as("support")

        outcome = await self.deliver(
            self.event(extras=(self.extra("m2", role=RoleRef(dimension="player_role", role="tank")),))
        )

        self.assertEqual("accepted", outcome)
        self.assertEqual(["support"], await self._seated_roles())
        (member,) = [row for row in await self.roster() if row.workspace_member_id == self.ids["m2"]]
        self.assertEqual(1234, member.rank)

    async def test_a_root_assignment_is_used_when_nothing_was_observed(self) -> None:
        await self._rostered_as("support")
        self.assertEqual("accepted", await self.deliver(self.event(extras=(self.extra("m2", role=None),))))
        self.assertEqual(["support"], await self._seated_roles())

    async def test_an_invalid_observed_leaf_is_refused_even_beside_a_valid_roster_role(self) -> None:
        await self._rostered_as("support")

        outcome = await self.deliver(
            self.event(extras=(self.extra("m2", role=RoleRef(dimension="player_role", role="no_such_role")),))
        )

        self.assertEqual("owner_policy_refused", outcome)
        (receipt,) = await self.receipts()
        self.assertEqual("extra_role_invalid", receipt.reason)
        self.assertEqual(2, len(await self.roster()))
        await self.assert_untouched()

    async def test_an_observed_foreign_dimension_is_refused_beside_a_valid_roster_role(self) -> None:
        await self._rostered_as("support")
        bad = RoleRef(dimension="hero_pool", role="tank")
        self.assertEqual("owner_policy_refused", await self.deliver(self.event(extras=(self.extra("m2", role=bad),))))


class SavepointSignalTests(EvidenceCase):
    """Releasing or rolling back a SAVEPOINT is not a commit: nothing publishes before the root commit."""

    @staticmethod
    async def _settle() -> None:
        for _ in range(3):
            await asyncio.sleep(0)

    async def _events(self) -> int:
        async with self.Session() as s:
            return await s.scalar(
                sa.select(sa.func.count())
                .select_from(WorkspaceEvent)
                .where(WorkspaceEvent.tournament_id == self.ids["t"])
            )

    async def test_a_released_savepoint_then_an_outer_rollback_publishes_and_persists_nothing(self) -> None:
        emit_module = sys.modules["shared.services.realtime.emit"]
        with (
            patch.object(emit_module, "_flush", AsyncMock()) as flush,
            patch.object(room_reconcile, "_reconcile_in_new_session", AsyncMock()) as reconcile,
        ):
            async with self.Session() as s:
                async with s.begin_nested():
                    await emit(s, scope=Scope.tournament(self.ids["t"]), invalidates=[Resource.TOURNAMENT_ENCOUNTERS])
                    room_reconcile.request_room_reconcile(s, self.ids["e"])
                await s.rollback()
            await self._settle()
        flush.assert_not_awaited()
        reconcile.assert_not_awaited()
        self.assertEqual(0, await self._events())

    async def test_a_released_savepoint_publishes_only_after_the_root_commit(self) -> None:
        emit_module = sys.modules["shared.services.realtime.emit"]
        with (
            patch.object(emit_module, "_flush", AsyncMock()) as flush,
            patch.object(room_reconcile, "_reconcile_in_new_session", AsyncMock()) as reconcile,
        ):
            async with self.Session() as s:
                async with s.begin_nested():
                    await emit(s, scope=Scope.tournament(self.ids["t"]), invalidates=[Resource.TOURNAMENT_ENCOUNTERS])
                    room_reconcile.request_room_reconcile(s, self.ids["e"])
                await self._settle()
                flush.assert_not_awaited()
                reconcile.assert_not_awaited()
                await s.commit()
            await self._settle()
        flush.assert_awaited_once()
        reconcile.assert_awaited_once()

    async def test_a_rolled_back_savepoint_drops_only_what_it_staged(self) -> None:
        emit_module = sys.modules["shared.services.realtime.emit"]
        with (
            patch.object(emit_module, "_flush", AsyncMock()) as flush,
            patch.object(room_reconcile, "_reconcile_in_new_session", AsyncMock()) as reconcile,
        ):
            async with self.Session() as s:
                await emit(s, scope=Scope.tournament(self.ids["t"]), invalidates=[Resource.TOURNAMENT_ENCOUNTERS])
                room_reconcile.request_room_reconcile(s, self.ids["e"])
                try:
                    async with s.begin_nested():
                        await emit(
                            s, scope=Scope.tournament(self.ids["t"]), invalidates=[Resource.TOURNAMENT_STANDINGS]
                        )
                        room_reconcile.request_stage_reconcile(s, 999)
                        raise RuntimeError("savepoint refused")
                except RuntimeError:
                    pass
                await s.commit()
            await self._settle()
        flush.assert_awaited_once()
        pending, _generations = flush.await_args.args
        resources = {resource for _scope, _row, resources, _ids in pending for resource in resources}
        self.assertEqual({Resource.TOURNAMENT_ENCOUNTERS}, resources)
        reconcile.assert_awaited_once()
        self.assertEqual(("encounter", self.ids["e"]), reconcile.await_args.args[0])
