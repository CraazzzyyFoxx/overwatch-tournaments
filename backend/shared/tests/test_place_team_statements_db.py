"""``place_team`` writes a seat in a fixed number of statements, whatever the roster size. Needs the test Postgres."""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.services.encounter import participants
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

_TAG = itertools.count()


class PlaceTeamStatementTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"pts-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            workspace = models.Workspace(slug=tag, name=tag)
            s.add(workspace)
            await s.flush()
            self.workspace_id = workspace.id
            tournament = models.Tournament(workspace_id=workspace.id, name=tag, slug=tag)
            rule = models.ScoringRule(workspace_id=workspace.id, preset="wins", game_formula="win", end_formula="1")
            s.add_all([tournament, rule])
            await s.flush()
            self.encounter = models.Encounter(
                workspace_id=workspace.id,
                discipline="overwatch",
                tournament_id=tournament.id,
                scoring_rule_id=rule.id,
                name=tag,
                slot_count=2,
                status="PENDING",
            )
            users = [models.User(name=f"{tag}-{index}") for index in range(6)]
            s.add_all([self.encounter, *users])
            await s.flush()
            self.user_ids = [user.id for user in users]
            members = [models.WorkspaceMember(workspace_id=workspace.id, player_id=user.id) for user in users]
            s.add_all(members)
            await s.commit()
            self.member_ids = [member.id for member in members]

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.User).where(models.User.id.in_(self.user_ids)))
            await s.commit()
        await self.engine.dispose()

    def _roster(self, member_ids: list[int]) -> list[participants.MemberSnapshot]:
        codes = ("damage", "damage", "tank")
        return [
            participants.MemberSnapshot(
                workspace_member_id=member_id,
                display_name=f"m{member_id}",
                rank=None,
                is_substitute=False,
                roles=(("player_role", code),),
            )
            for member_id, code in zip(member_ids, codes, strict=True)
        ]

    async def test_second_seat_costs_four_statements_and_keeps_every_role(self) -> None:
        statements: list[str] = []

        def record(_conn, _cursor, statement, *_args) -> None:
            statements.append(statement)

        async with self.Session() as s:
            await participants.place_team(
                s, self.encounter, slot=1, team_id=None, name="A", seed=None, members=self._roster(self.member_ids[:3])
            )
            sa.event.listen(self.engine.sync_engine, "before_cursor_execute", record)
            try:
                second = await participants.place_team(
                    s,
                    self.encounter,
                    slot=2,
                    team_id=None,
                    name="B",
                    seed=None,
                    members=self._roster(self.member_ids[3:]),
                )
            finally:
                sa.event.remove(self.engine.sync_engine, "before_cursor_execute", record)
            await s.commit()
            # Slot check, seat, members, roles: the role lookups were memoized by the first seat.
            self.assertEqual(len(statements), 4, statements)
            rows = (
                await s.execute(
                    sa.select(models.EncounterTeamMember.workspace_member_id, models.EncounterTeamMemberRole.role)
                    .join(models.EncounterTeamMemberRole)
                    .where(models.EncounterTeamMember.encounter_team_id == second.id)
                    .order_by(models.EncounterTeamMember.workspace_member_id)
                )
            ).all()
        self.assertEqual(
            [tuple(row) for row in rows],
            list(zip(self.member_ids[3:], ("damage", "damage", "tank"), strict=True)),
        )
