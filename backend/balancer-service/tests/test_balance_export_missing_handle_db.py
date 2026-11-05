"""A saved balance seating a registration without a game handle is refused before export writes anything.

Materialization finds players by handle, so such a player used to be skipped ("not found") while the team named
after them was still created -- captainless when it was the captain. Needs the test Postgres; skips otherwise.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.core import enums
from shared.core.errors import ApiHTTPException
from shared.models.balancer.balance import BalancerBalance
from shared.models.registration.registration import Registration, RegistrationIdentity
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres
from shared.testing.factories import add_entry
from src.services.admin.balancer import balancer_admin_service
from tests.factories import formation_node, wire_input

_TAG = itertools.count()


def _seat(registration: Registration, name: str, *, captain: bool) -> dict:
    return {
        "uuid": str(registration.id),
        "name": name,
        "assigned_rating": 3000,
        "role_discomfort": 0,
        "is_captain": captain,
        "role_preferences": [],
        "all_ratings": {},
    }


class BalanceExportMissingHandleTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = f"balexp-{os.getpid()}-{next(_TAG)}"

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(Workspace).where(Workspace.slug == self.tag))
            await s.commit()
        await self.engine.dispose()

    async def test_a_handleless_captain_refuses_the_export_and_writes_no_team(self) -> None:
        async with self.Session() as s:
            workspace = Workspace(slug=self.tag, name=self.tag)
            s.add(workspace)
            await s.flush()
            tournament = Tournament(
                workspace_id=workspace.id,
                discipline="overwatch",
                name=self.tag,
                slug=self.tag,
                status=enums.TournamentStatus.LIVE,
            )
            s.add(tournament)
            await s.flush()
            captain, member = (
                Registration(tournament_id=tournament.id, display_name=name) for name in ("No Tag Captain", "Tagged#1")
            )
            s.add_all([captain, member])
            await s.flush()
            formation_id = await formation_node(s, tournament.id)
            registration_node_id = await wire_input(s, formation_id)
            for registration in (captain, member):
                await add_entry(s, registration_node_id, registration.id, status="approved", balancer_status="ready")
            s.add(
                RegistrationIdentity(
                    registration_id=member.id,
                    provider="battlenet",
                    position=0,
                    handle="Tagged#1",
                    handle_normalized="tagged#1",
                )
            )
            team = {
                "id": 1,
                "name": "No Tag Captain",
                "average_mmr": 3000,
                "rating_variance": 0,
                "total_discomfort": 0,
                "max_discomfort": 0,
                "roster": {
                    "tank": [_seat(captain, "No Tag Captain", captain=True)],
                    "damage": [_seat(member, "Tagged#1", captain=False)],
                },
            }
            balance = BalancerBalance(
                tournament_id=tournament.id,
                formation_node_id=formation_id,
                result_json={
                    "teams": [team],
                    "statistics": {"average_mmr": 3000, "mmr_std_dev": 0, "total_teams": 1, "players_per_team": 2},
                },
            )
            s.add(balance)
            await s.commit()
            tournament_id = tournament.id

            with self.assertRaises(ApiHTTPException) as caught:
                await balancer_admin_service.export_balance(s, balance.id, actor_user_id=0)

            self.assertEqual(caught.exception.status_code, 422)
            [detail] = caught.exception.detail
            self.assertEqual(detail["code"], "missing_handle")
            self.assertIn("No Tag Captain", detail["msg"])
            self.assertNotIn("Tagged#1", detail["msg"])
            await s.rollback()
            teams = await s.scalars(sa.select(Team).where(Team.tournament_id == tournament_id))
            self.assertEqual(teams.all(), [])
