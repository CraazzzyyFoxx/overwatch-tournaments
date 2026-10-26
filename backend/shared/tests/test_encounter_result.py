"""The only writer of an encounter's result (D57, D68). Needs the test Postgres.

Every path that moves a result -- the games adding up, a captain's series
claim, an admin, a Challonge import -- lands here, under the encounter row's
own lock, and leaves exactly one journal row carrying the version it wrote.
``uq_result_audit_version`` is what makes "one row per version" checkable, so
these run against the real database rather than a session double.
"""

from __future__ import annotations

import math

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.encounter import (
    Encounter,
    EncounterGame,
    EncounterGameTeam,
    EncounterResultAudit,
    EncounterTeam,
)
from shared.models.platform.outbox import EventOutbox
from shared.services.encounter import events, participants, result
from shared.tests.encounter_writer_case import EncounterWriterCase


class ResultWriterCase(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            encounter = await self.encounter(s)
            self.seats = [
                (
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
                                roles=(),
                            )
                        ],
                    )
                ).id
                for slot in (1, 2)
            ]
            await s.commit()

    async def confirm_game(
        self, session, position: int, winner_index: int, *, seats: list[int] | None = None
    ) -> EncounterGame:
        """One confirmed game, won 1:0 by ``seats[winner_index]``.

        ``seats`` defaults to the line-up placed in ``asyncSetUp``; a case that
        replaces an occupant passes the line-up that actually played.
        """
        line_up = self.seats if seats is None else seats
        game = EncounterGame(
            encounter_id=self.ids["e"],
            position=position,
            state=enums.EncounterGameState.CONFIRMED,
            result_source=enums.EncounterGameResultSource.ADMIN,
            confirmed_at=sa.func.now(),
        )
        session.add(game)
        await session.flush()
        for index, seat_id in enumerate(line_up):
            session.add(
                EncounterGameTeam(
                    game_id=game.id,
                    encounter_id=self.ids["e"],
                    encounter_team_id=seat_id,
                    score=1 if index == winner_index else 0,
                )
            )
        await session.flush()
        return game

    async def audits(self) -> list[EncounterResultAudit]:
        async with self.Session() as s:
            return list(
                (
                    await s.execute(
                        sa.select(EncounterResultAudit)
                        .where(EncounterResultAudit.encounter_id == self.ids["e"])
                        .order_by(EncounterResultAudit.result_version)
                    )
                )
                .scalars()
                .all()
            )

    async def reload(self) -> Encounter:
        async with self.Session() as s:
            return await s.get_one(Encounter, self.ids["e"])

    async def standing(self) -> list[tuple[int, float, int | None]]:
        async with self.Session() as s:
            return list(
                (
                    await s.execute(
                        sa.select(EncounterTeam.id, EncounterTeam.score, EncounterTeam.placement)
                        .where(EncounterTeam.encounter_id == self.ids["e"], EncounterTeam.active.is_(True))
                        .order_by(EncounterTeam.slot)
                    )
                ).all()
            )


class LockEncounterTests(ResultWriterCase):
    async def test_the_row_is_held_against_a_second_writer(self) -> None:
        async with self.Session() as holder:
            encounter = await result.lock_encounter(holder, self.ids["e"])
            self.assertEqual(self.ids["e"], encounter.id)
            async with self.Session() as other:
                with self.assertRaises(DBAPIError):
                    await other.execute(
                        sa.text("SELECT 1 FROM encounter.encounter WHERE id = :id FOR UPDATE NOWAIT"),
                        {"id": self.ids["e"]},
                    )
            await holder.rollback()


class ApplyResultTests(ResultWriterCase):
    async def test_a_confirmation_writes_one_version_and_one_journal_row(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            audit = await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={self.seats[0]: 2.0, self.seats[1]: 0.0},
                placements={self.seats[0]: 1, self.seats[1]: 2},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason="decided by the referee",
            )
            await s.commit()
            self.assertEqual(1, audit.result_version)

        encounter = await self.reload()
        self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, encounter.result_status)
        self.assertEqual(enums.EncounterResultSource.ADMIN.value, encounter.result_source)
        self.assertIsNotNone(encounter.confirmed_at)
        self.assertEqual(1, encounter.result_version)
        self.assertEqual([(self.seats[0], 2.0, 1), (self.seats[1], 0.0, 2)], await self.standing())

        rows = await self.audits()
        self.assertEqual(1, len(rows))
        self.assertEqual(enums.AuditSnapshotScope.ENCOUNTER.value, rows[0].snapshot_scope)
        self.assertEqual(
            [{"encounter_team_id": self.seats[0], "score": 0.0, "placement": None}],
            [row for row in rows[0].before if row["encounter_team_id"] == self.seats[0]],
        )
        self.assertEqual(
            [
                {"encounter_team_id": self.seats[0], "score": 2.0, "placement": 1},
                {"encounter_team_id": self.seats[1], "score": 0.0, "placement": 2},
            ],
            rows[0].after,
        )
        self.assertEqual("decided by the referee", rows[0].reason)

    async def test_a_non_finite_total_is_refused(self) -> None:
        for bad in (math.nan, math.inf, -math.inf):
            async with self.Session() as s:
                encounter = await result.lock_encounter(s, self.ids["e"])
                with self.assertRaises(ValueError):
                    await result.apply_result(
                        s,
                        encounter,
                        source=enums.EncounterResultSource.ADMIN,
                        totals={self.seats[0]: bad, self.seats[1]: 0.0},
                        placements={self.seats[0]: 1, self.seats[1]: 2},
                        action=enums.EncounterResultAuditAction.CONFIRM,
                        audit_source="admin",
                        actor_user_id=None,
                        reason=None,
                    )
                await s.rollback()

    async def test_a_game_scoped_write_names_the_game_it_decided(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            game = await self.confirm_game(s, 1, 0)
            audit = await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={self.seats[0]: 1.0, self.seats[1]: 0.0},
                placements={self.seats[0]: 1, self.seats[1]: 2},
                action=enums.EncounterResultAuditAction.GAME_CORRECT,
                audit_source="admin",
                actor_user_id=None,
                reason="map 1 re-entered by hand",
                game=game,
                scope=enums.AuditSnapshotScope.GAME,
            )
            await s.commit()
            self.assertEqual(game.id, audit.game_id)
            self.assertEqual(enums.AuditSnapshotScope.GAME.value, audit.snapshot_scope)

        encounter = await self.reload()
        self.assertEqual(1, encounter.result_version)

    async def test_there_is_no_way_to_un_complete_an_encounter_through_it(self) -> None:
        """``source`` has no "none": a Task 6/7 caller that leaves the keyword
        out gets a TypeError, and one that spells ``None`` gets told to use
        ``reopen`` -- never a silent un-completion."""
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            with self.assertRaises(TypeError):
                await result.apply_result(
                    s,
                    encounter,
                    totals={self.seats[0]: 1.0, self.seats[1]: 0.0},
                    placements={self.seats[0]: 1, self.seats[1]: 2},
                    action=enums.EncounterResultAuditAction.CONFIRM,
                    audit_source="admin",
                    actor_user_id=None,
                    reason=None,
                )
            with self.assertRaises(ValueError):
                await result.apply_result(
                    s,
                    encounter,
                    source=None,
                    totals={self.seats[0]: 1.0, self.seats[1]: 0.0},
                    placements={self.seats[0]: 1, self.seats[1]: 2},
                    action=enums.EncounterResultAuditAction.CONFIRM,
                    audit_source="admin",
                    actor_user_id=None,
                    reason=None,
                )
            await s.rollback()
        self.assertEqual(0, (await self.reload()).result_version)

    async def test_an_id_that_is_not_a_live_seat_is_refused(self) -> None:
        """``team_id`` and ``encounter_team_id`` are two ints both called
        "team". Reading the mapping by seat and ignoring the rest would zero
        every seat and confirm that. The ids come from an admin's request body,
        so the refusal is a 422, not a 500."""
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            for totals, placements in (
                ({self.ids["team0"]: 2.0}, {self.ids["team0"]: 1}),
                ({self.seats[0]: 2.0}, {self.seats[0]: 1, self.ids["team1"]: 2}),
            ):
                with self.assertRaises(BaseAPIException) as caught:
                    await result.apply_result(
                        s,
                        encounter,
                        source=enums.EncounterResultSource.ADMIN,
                        totals=totals,
                        placements=placements,
                        action=enums.EncounterResultAuditAction.CONFIRM,
                        audit_source="admin",
                        actor_user_id=None,
                        reason=None,
                    )
                self.assertEqual(422, caught.exception.status_code)
            await s.rollback()
        self.assertEqual(0, (await self.reload()).result_version)
        self.assertEqual([(self.seats[0], 0.0, None), (self.seats[1], 0.0, None)], await self.standing())

    async def test_a_live_seat_left_out_simply_scored_nothing(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={self.seats[0]: 2.0},
                placements={self.seats[0]: 1},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason=None,
            )
            await s.commit()
        self.assertEqual([(self.seats[0], 2.0, 1), (self.seats[1], 0.0, None)], await self.standing())
        self.assertEqual(1, encounter.result_version)


class RetiredLineupTests(ResultWriterCase):
    """A confirmed game stays with the participation that played it, so after a
    seat changes hands those rows are still on record -- and they are the OLD
    line-up's result. They must not reach the live standing, in either
    direction: not as points, not as wins, and not as a rank."""

    async def _replace_slot_one(self) -> int:
        """Retire slot 1's occupant and seat ``team2`` in its place."""
        async with self.Session() as s:
            encounter = await self.encounter(s)
            await participants.vacate_slot(s, encounter, slot=1)
            replacement = await participants.place_team(
                s,
                encounter,
                slot=1,
                team_id=self.ids["team2"],
                name="T2",
                seed=1,
                members=[
                    participants.MemberSnapshot(
                        workspace_member_id=self.ids["m2"],
                        display_name="m2",
                        rank=2500,
                        is_substitute=False,
                        roles=(),
                    )
                ],
            )
            await s.commit()
            return replacement.id

    async def test_a_retired_occupants_wins_neither_score_nor_end_the_series(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            for position in (1, 2):
                game = await self.confirm_game(s, position, 0)
                outcome = await result.refresh_from_games(
                    s,
                    encounter,
                    action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                    audit_source="admin",
                    actor_user_id=None,
                    game=game,
                )
            await s.commit()
        # Slot 1 took the Bo3 2:0 and the encounter confirmed itself.
        self.assertTrue(outcome.ended)
        self.assertEqual(enums.EncounterResultSource.GAMES.value, (await self.reload()).result_source)

        replacement = await self._replace_slot_one()
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            outcome = await result.refresh_from_games(
                s,
                encounter,
                action=enums.EncounterResultAuditAction.CASCADE_RESET,
                audit_source="system",
                actor_user_id=None,
            )
            await s.commit()

        # Both games belong to a line-up that no longer exists: nothing counts.
        self.assertEqual(0, outcome.games)
        self.assertEqual({replacement: 0.0, self.seats[1]: 0.0}, dict(outcome.totals))
        self.assertEqual({replacement: 0, self.seats[1]: 0}, dict(outcome.wins))
        self.assertFalse(outcome.ended)

        encounter = await self.reload()
        self.assertIsNone(encounter.result_source)
        self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)
        self.assertEqual(enums.EncounterResultStatus.NONE, encounter.result_status)
        # Level on nothing: both live seats share first, and the retired seat
        # is nowhere in the standing.
        self.assertEqual([(replacement, 0.0, 1), (self.seats[1], 0.0, 1)], await self.standing())

    async def test_the_survivor_is_ranked_by_the_games_its_new_opponent_played(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            game = await self.confirm_game(s, 1, 0)
            await result.refresh_from_games(
                s,
                encounter,
                action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                game=game,
            )
            await s.commit()

        replacement = await self._replace_slot_one()
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            # Position 2, played by the new line-up and won by slot 2.
            game = await self.confirm_game(s, 2, 1, seats=[replacement, self.seats[1]])
            outcome = await result.refresh_from_games(
                s,
                encounter,
                action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                game=game,
            )
            await s.commit()

        self.assertEqual(1, outcome.games)
        # Position 1 went to the retired occupant; it pays the survivor nothing
        # and leaves nobody at place 1 above it.
        self.assertEqual([(replacement, 0.0, 2), (self.seats[1], 1.0, 1)], await self.standing())
        self.assertFalse(outcome.ended)


class HoldResultTests(ResultWriterCase):
    async def hold(self, status: enums.EncounterResultStatus, action: enums.EncounterResultAuditAction) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.hold_result(
                s,
                encounter,
                status=status,
                action=action,
                audit_source="series_claim",
                actor_user_id=None,
            )
            await s.commit()

    async def test_each_hold_is_one_version_and_one_journal_row_and_adopts_nothing(self) -> None:
        await self.hold(enums.EncounterResultStatus.PENDING_CONFIRMATION, enums.EncounterResultAuditAction.AUTO_PENDING)
        await self.hold(enums.EncounterResultStatus.DISPUTED, enums.EncounterResultAuditAction.AUTO_DISPUTE)

        encounter = await self.reload()
        self.assertEqual(enums.EncounterResultStatus.DISPUTED, encounter.result_status)
        self.assertIsNone(encounter.result_source)
        self.assertIsNone(encounter.confirmed_at)
        self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)
        self.assertEqual(2, encounter.result_version)
        self.assertEqual([(self.seats[0], 0.0, None), (self.seats[1], 0.0, None)], await self.standing())

        rows = await self.audits()
        self.assertEqual([1, 2], [row.result_version for row in rows])
        self.assertEqual(
            [enums.EncounterResultAuditAction.AUTO_PENDING, enums.EncounterResultAuditAction.AUTO_DISPUTE],
            [row.action for row in rows],
        )
        self.assertEqual(
            [
                (enums.EncounterResultStatus.NONE, enums.EncounterResultStatus.PENDING_CONFIRMATION),
                (enums.EncounterResultStatus.PENDING_CONFIRMATION, enums.EncounterResultStatus.DISPUTED),
            ],
            [(row.from_result_status, row.to_result_status) for row in rows],
        )
        self.assertTrue(all(row.before == row.after for row in rows))

    async def test_a_hold_drops_the_reports_closeness_average(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            encounter.closeness = 0.7
            await s.commit()
        await self.hold(enums.EncounterResultStatus.DISPUTED, enums.EncounterResultAuditAction.AUTO_DISPUTE)
        self.assertIsNone((await self.reload()).closeness)

    async def test_only_a_pending_or_disputed_status_can_be_held(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            with self.assertRaises(ValueError):
                await result.hold_result(
                    s,
                    encounter,
                    status=enums.EncounterResultStatus.CONFIRMED,
                    action=enums.EncounterResultAuditAction.CONFIRM,
                    audit_source="admin",
                    actor_user_id=None,
                )
            await s.rollback()
        self.assertEqual(0, (await self.reload()).result_version)

    async def test_a_confirmed_result_leaves_only_through_reopen(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={self.seats[0]: 2.0, self.seats[1]: 0.0},
                placements={self.seats[0]: 1, self.seats[1]: 2},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason=None,
            )
            with self.assertRaises(ValueError):
                await result.hold_result(
                    s,
                    encounter,
                    status=enums.EncounterResultStatus.DISPUTED,
                    action=enums.EncounterResultAuditAction.AUTO_DISPUTE,
                    audit_source="series_claim",
                    actor_user_id=None,
                )
            await s.rollback()


class RefreshFromGamesTests(ResultWriterCase):
    async def test_an_unfinished_series_materializes_without_confirming(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            game = await self.confirm_game(s, 1, 0)
            outcome = await result.refresh_from_games(
                s,
                encounter,
                action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                game=game,
            )
            await s.commit()
            self.assertFalse(outcome.ended)

        self.assertEqual([(self.seats[0], 1.0, 1), (self.seats[1], 0.0, 2)], await self.standing())
        encounter = await self.reload()
        self.assertIsNone(encounter.result_source)
        self.assertEqual(1, encounter.result_version)
        self.assertEqual(1, len(await self.audits()))

    async def test_the_series_confirms_itself_once_it_has_ended(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            for position in (1, 2):
                game = await self.confirm_game(s, position, 0)
                outcome = await result.refresh_from_games(
                    s,
                    encounter,
                    action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                    audit_source="admin",
                    actor_user_id=None,
                    game=game,
                )
            await s.commit()
            self.assertTrue(outcome.ended)

        encounter = await self.reload()
        self.assertEqual(enums.EncounterResultSource.GAMES.value, encounter.result_source)
        self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, encounter.result_status)
        self.assertEqual([(self.seats[0], 2.0, 1), (self.seats[1], 0.0, 2)], await self.standing())
        # One per write, numbered by the version each left behind.
        self.assertEqual([1, 2], [row.result_version for row in await self.audits()])
        self.assertEqual(2, encounter.result_version)

    async def test_a_series_claim_result_is_never_overwritten_by_the_games(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.SERIES_CLAIM,
                totals={self.seats[0]: 0.0, self.seats[1]: 2.0},
                placements={self.seats[0]: 2, self.seats[1]: 1},
                action=enums.EncounterResultAuditAction.AUTO_CONFIRM,
                audit_source="captain_agreement",
                actor_user_id=None,
                reason=None,
            )
            await s.commit()

        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            game = await self.confirm_game(s, 1, 0)
            await result.refresh_from_games(
                s,
                encounter,
                action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                game=game,
            )
            await s.commit()

        encounter = await self.reload()
        self.assertEqual(enums.EncounterResultSource.SERIES_CLAIM.value, encounter.result_source)
        self.assertEqual(1, encounter.result_version)
        self.assertEqual([(self.seats[0], 0.0, 2), (self.seats[1], 2.0, 1)], await self.standing())
        self.assertEqual(1, len(await self.audits()))


class ReopenTests(ResultWriterCase):
    async def test_reopen_clears_the_result_source_and_takes_the_next_version(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.IMPORT,
                totals={self.seats[0]: 2.0, self.seats[1]: 1.0},
                placements={self.seats[0]: 1, self.seats[1]: 2},
                action=enums.EncounterResultAuditAction.IMPORT,
                audit_source="challonge",
                actor_user_id=None,
                reason=None,
            )
            await s.commit()

        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            audit = await result.reopen(s, encounter, actor_user_id=self.users[0], reason="wrong bracket")
            await s.commit()
            self.assertEqual(enums.EncounterResultAuditAction.REOPEN, audit.action)

        encounter = await self.reload()
        self.assertIsNone(encounter.result_source)
        self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)
        self.assertEqual(enums.EncounterResultStatus.NONE, encounter.result_status)
        self.assertIsNone(encounter.confirmed_at)
        self.assertEqual(2, encounter.result_version)
        self.assertEqual([1, 2], [row.result_version for row in await self.audits()])

    async def test_a_reopened_encounter_is_scored_by_its_games_again(self) -> None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={self.seats[0]: 2.0, self.seats[1]: 0.0},
                placements={self.seats[0]: 1, self.seats[1]: 2},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason=None,
            )
            await result.reopen(s, encounter, actor_user_id=self.users[0], reason="replay ordered")
            game = await self.confirm_game(s, 1, 1)
            await result.refresh_from_games(
                s,
                encounter,
                action=enums.EncounterResultAuditAction.GAME_CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                game=game,
            )
            await s.commit()

        self.assertEqual([(self.seats[0], 0.0, 2), (self.seats[1], 1.0, 1)], await self.standing())
        self.assertEqual([1, 2, 3], [row.result_version for row in await self.audits()])
        self.assertEqual(3, (await self.reload()).result_version)


class CompletedEventTests(ResultWriterCase):
    """The winner the achievement rail is told about is the sole first place.

    Staged, never committed: the outbox row only has to exist long enough to
    be read back, and the test leaves nothing behind in a shared table.
    """

    async def _winner_in_event(self, placements: dict[int, int]) -> int | None:
        async with self.Session() as s:
            encounter = await result.lock_encounter(s, self.ids["e"])
            await result.apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals=dict.fromkeys(self.seats, 1.0),
                placements=placements,
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason=None,
            )
            await events.enqueue_encounter_completed(s, encounter, source_service="shared-tests")
            row = (
                await s.execute(
                    sa.select(EventOutbox)
                    .where(EventOutbox.event_type == "encounter_completed")
                    .order_by(EventOutbox.id.desc())
                    .limit(1)
                )
            ).scalar_one()
            payload = row.payload_json
            await s.rollback()
        self.assertEqual(self.ids["e"], payload["encounter_id"])
        return payload["winner_team_id"]

    async def test_the_sole_first_place_is_the_winner(self) -> None:
        winner = await self._winner_in_event({self.seats[0]: 1, self.seats[1]: 2})
        self.assertEqual(self.ids["team0"], winner)

    async def test_a_shared_first_place_is_nobody(self) -> None:
        self.assertIsNone(await self._winner_in_event({self.seats[0]: 1, self.seats[1]: 1}))
