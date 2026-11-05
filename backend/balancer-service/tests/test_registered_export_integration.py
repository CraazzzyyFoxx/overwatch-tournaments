"""End-to-end materialization of registered teams against real Postgres.

Requires a reachable database via POSTGRES_* env vars (use a disposable DB such
as anak_dev — NEVER production). Skips cleanly if the DB is unreachable.

This is the proof step 5 needs: the unit tests pin the *plan*, but only a real
engine shows that a registered roster becomes correct `tournament.team` /
`tournament.player` rows, that the `exported_team_id` back-link lands, that a
re-export replaces rather than duplicates, and that substitutes are written as
substitutes and excluded from the team's SR.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for path in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from shared import models  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.team_format import FormatDimension, FormatRule, TeamFormat  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    Registration,
    RegistrationEntry,
    RegistrationForm,
    RegistrationIdentity,
    RegistrationRole,
    RegistrationTeam,
)
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament.tournament import Tournament  # noqa: E402
from shared.repository import CatalogRoleRepository  # noqa: E402
from shared.services.team_format import save_tournament_format  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from shared.testing.factories import add_entry  # noqa: E402
from src.services.registered_teams import registered_teams_service  # noqa: E402
from tests.factories import formation_node, wire_input  # noqa: E402

_UNIQUE = 0


def _uniq() -> int:
    global _UNIQUE
    _UNIQUE += 1
    return _UNIQUE


#: tank 1 + damage 2 = a 3-person roster, so "complete" is reachable with few rows.
_SHAPE = {"tank": 1, "damage": 2}


class RegisteredExportIntegrationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.suffix = f"regexp-{os.getpid()}-{_uniq()}"

        async with self.Session() as session:
            workspace = Workspace(slug=f"ws-{self.suffix}", name=f"WS {self.suffix}")
            session.add(workspace)
            await session.flush()

            # ``slug`` is NOT NULL and globally unique (migration tslug0001).
            tournament = Tournament(workspace_id=workspace.id, name=f"T {self.suffix}", slug=f"t-{self.suffix}")
            tournament.status = "registration"
            session.add(tournament)
            await session.flush()
            await save_tournament_format(
                session,
                tournament,
                TeamFormat(
                    discipline="overwatch",
                    name="Export seats",
                    starter_min=sum(_SHAPE.values()),
                    starter_max=sum(_SHAPE.values()),
                    dimensions=(FormatDimension("player_role", "enforced"),),
                    rules=tuple(FormatRule("player_role", role, count, count) for role, count in _SHAPE.items()),
                ),
            )

            session.add(
                RegistrationForm(
                    tournament_id=tournament.id,
                    workspace_id=workspace.id,
                    # One bench place, so the substitute assertions have something
                    # legal to assert on.
                    max_substitutes=1,
                )
            )

            self.workspace_id = workspace.id
            self.tournament_id = tournament.id
            self.node_id = await formation_node(session, tournament.id, mode="registered")
            self.registration_node_id = await wire_input(session, self.node_id)
            self.member_ids: list[int] = []
            self.player_ids: list[int] = []
            for index in range(4):
                player = User(name=f"p-{self.suffix}-{index}")
                session.add(player)
                await session.flush()
                member = WorkspaceMember(workspace_id=workspace.id, player_id=player.id)
                session.add(member)
                await session.flush()
                self.player_ids.append(player.id)
                self.member_ids.append(member.id)
            await session.commit()

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as session:
            await session.execute(sa.delete(models.Player).where(models.Player.tournament_id == self.tournament_id))
            await session.execute(sa.delete(models.Team).where(models.Team.tournament_id == self.tournament_id))
            await session.execute(
                sa.delete(RegistrationTeam).where(RegistrationTeam.tournament_id == self.tournament_id)
            )
            await session.execute(sa.delete(Tournament).where(Tournament.id == self.tournament_id))
            await session.execute(sa.delete(WorkspaceMember).where(WorkspaceMember.workspace_id == self.workspace_id))
            await session.execute(sa.delete(User).where(User.id.in_(self.player_ids)))
            await session.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await session.commit()
        await self.engine.dispose()

    # ── seeding helpers ──────────────────────────────────────────────────────

    async def _seed_team(
        self,
        session: sa.orm.Session,  # type: ignore[name-defined]
        *,
        name: str,
        status: str,
        roster: list[tuple[int, str, int, bool]],
    ) -> RegistrationTeam:
        """``roster`` = (member index, slot code, rank, is_substitute)."""
        team = RegistrationTeam(
            tournament_id=self.tournament_id,
            registration_node_id=self.registration_node_id,
            workspace_id=self.workspace_id,
            name=name,
            name_normalized=name.lower(),
            status=status,
        )
        session.add(team)
        await session.flush()

        first_registration_id: int | None = None
        catalog_roles = await CatalogRoleRepository().rated_rows(
            session, discipline="overwatch", workspace_id=self.workspace_id
        )
        for member_index, slot_code, rank, is_substitute in roster:
            tag = f"m{member_index}-{self.suffix}#1111"
            registration = Registration(
                tournament_id=self.tournament_id,
                workspace_member_id=self.member_ids[member_index],
                display_name=f"m{member_index}-{self.suffix}",
                registration_team_id=team.id,
                team_slot_code=slot_code,
            )
            session.add(registration)
            await session.flush()
            await add_entry(
                session, self.registration_node_id, registration.id, status="approved", is_substitute=is_substitute
            )
            session.add(
                RegistrationIdentity(
                    registration_id=registration.id,
                    provider="battlenet",
                    position=0,
                    handle=tag,
                    handle_normalized=tag.lower(),
                )
            )
            session.add(
                RegistrationRole(
                    registration_id=registration.id,
                    catalog_role=catalog_roles[slot_code],
                    dimension_id=catalog_roles[slot_code].dimension_id,
                    is_primary=True,
                    priority=0,
                    rank_value=rank,
                )
            )
            if first_registration_id is None and not is_substitute:
                first_registration_id = registration.id
        team.captain_registration_id = first_registration_id
        await session.commit()
        return team

    async def _complete_team(self, name: str = "Alpha") -> RegistrationTeam:
        async with self.Session() as session:
            return await self._seed_team(
                session,
                name=name,
                status="complete",
                roster=[
                    (0, "tank", 3000, False),
                    (1, "damage", 2500, False),
                    (2, "damage", 2000, False),
                    (3, "damage", 1000, True),
                ],
            )

    async def _exported(self) -> tuple[models.Team | None, list[models.Player]]:
        async with self.Session() as session:
            team = await session.scalar(sa.select(models.Team).where(models.Team.tournament_id == self.tournament_id))
            players = list(
                await session.scalars(
                    sa.select(models.Player)
                    .where(models.Player.tournament_id == self.tournament_id)
                    .order_by(models.Player.rank.desc())
                )
            )
            return team, players

    # ── tests ────────────────────────────────────────────────────────────────

    async def test_a_complete_team_becomes_a_tournament_team(self) -> None:
        await self._complete_team()
        async with self.Session() as session:
            result = await registered_teams_service.export_registered(
                session, self.tournament_id, self.node_id, actor_user_id=1
            )

        self.assertEqual(1, result.imported_teams)
        self.assertEqual(0, result.removed_teams)
        self.assertEqual([], result.skipped)

        team, players = await self._exported()
        self.assertIsNotNone(team)
        assert team is not None
        # The registered name IS the balancer name on this path: there is no
        # captain battle tag standing in for it.
        self.assertEqual("Alpha", team.name)
        self.assertEqual("Alpha", team.balancer_name)
        self.assertEqual(4, len(players))

    async def test_slot_codes_become_player_roles(self) -> None:
        await self._complete_team()
        async with self.Session() as session:
            await registered_teams_service.export_registered(session, self.tournament_id, self.node_id, actor_user_id=1)

        _team, players = await self._exported()
        roles = sorted(player.role for player in players)
        self.assertEqual(["damage"] * 3 + ["tank"], roles)

    async def test_ranks_come_from_the_registration_roles(self) -> None:
        """`Player.rank` is NOT NULL, so a wrong rank source here is a silent data
        corruption rather than an error."""
        await self._complete_team()
        async with self.Session() as session:
            await registered_teams_service.export_registered(session, self.tournament_id, self.node_id, actor_user_id=1)

        _team, players = await self._exported()
        self.assertEqual([3000, 2500, 2000, 1000], [player.rank for player in players])

    async def test_the_substitute_is_written_as_one_and_excluded_from_team_sr(self) -> None:
        """`Team.avg_sr`/`total_sr` are correlated subqueries filtering on
        `is_substitution`; a substitute wrongly marked active would inflate both."""
        await self._complete_team()
        async with self.Session() as session:
            await registered_teams_service.export_registered(session, self.tournament_id, self.node_id, actor_user_id=1)

        _team, players = await self._exported()
        substitutes = [player for player in players if player.is_substitution]
        self.assertEqual(1, len(substitutes))
        self.assertEqual(1000, substitutes[0].rank)
        # A registration-time substitute has replaced nobody yet.
        self.assertIsNone(substitutes[0].related_player_id)

        async with self.Session() as session:
            total_sr = await session.scalar(
                sa.select(models.Team.total_sr).where(models.Team.tournament_id == self.tournament_id)
            )
        # 3000 + 2500 + 2000, with the 1000 bench player excluded.
        self.assertEqual(7500, total_sr)

    async def test_the_export_back_link_is_stamped_on_the_source_team(self) -> None:
        source = await self._complete_team()
        async with self.Session() as session:
            await registered_teams_service.export_registered(session, self.tournament_id, self.node_id, actor_user_id=1)

        async with self.Session() as session:
            fresh = await session.scalar(sa.select(RegistrationTeam).where(RegistrationTeam.id == source.id))
        assert fresh is not None
        team, _players = await self._exported()
        assert team is not None
        self.assertEqual(team.id, fresh.exported_team_id)
        self.assertEqual("success", fresh.export_status)
        self.assertIsNotNone(fresh.exported_at)
        self.assertIsNone(fresh.export_error)

    async def test_re_export_replaces_rather_than_duplicates(self) -> None:
        """The prior export's rows are deleted and rebuilt, so pressing the button
        twice is idempotent instead of doubling the roster."""
        await self._complete_team()
        async with self.Session() as session:
            await registered_teams_service.export_registered(session, self.tournament_id, self.node_id, actor_user_id=1)
        first_team, first_players = await self._exported()

        async with self.Session() as session:
            second = await registered_teams_service.export_registered(
                session, self.tournament_id, self.node_id, actor_user_id=1
            )

        self.assertEqual(1, second.removed_teams)
        self.assertEqual(1, second.imported_teams)
        second_team, second_players = await self._exported()
        assert first_team is not None and second_team is not None
        self.assertEqual(len(first_players), len(second_players))
        # A genuinely new row: the old one was deleted, not updated in place.
        self.assertNotEqual(first_team.id, second_team.id)

    async def test_an_incomplete_team_is_skipped_not_exported(self) -> None:
        """An incomplete roster would materialize an under-sized team that the
        bracket then treats as real."""
        async with self.Session() as session:
            await self._seed_team(
                session,
                name="Partial",
                status="forming",
                roster=[(0, "tank", 3000, False)],
            )
        async with self.Session() as session:
            result = await registered_teams_service.export_registered(
                session, self.tournament_id, self.node_id, actor_user_id=1
            )

        self.assertEqual(0, result.imported_teams)
        self.assertEqual(["team_incomplete"], [item.code for item in result.skipped])
        team, players = await self._exported()
        self.assertIsNone(team)
        self.assertEqual([], players)

    async def test_a_withdrawn_starter_blocks_an_incomplete_export(self) -> None:
        """A stale complete flag cannot bypass the format gate after a starter withdraws."""
        source = await self._complete_team()
        async with self.Session() as session:
            await session.execute(
                sa.update(RegistrationEntry)
                .where(
                    RegistrationEntry.registration_id.in_(
                        sa.select(Registration.id).where(
                            Registration.registration_team_id == source.id,
                            Registration.team_slot_code == "tank",
                        )
                    )
                )
                .values(status="withdrawn")
            )
            await session.commit()

        async with self.Session() as session:
            with self.assertRaises(ApiHTTPException) as caught:
                await registered_teams_service.export_registered(
                    session, self.tournament_id, self.node_id, actor_user_id=1
                )
        assert caught.exception.status_code == 409
        assert "team_format_violation" in str(caught.exception.detail)
        assert "role_below_hard_min" in str(caught.exception.detail)
        team, players = await self._exported()
        assert team is None and players == []
        async with self.Session() as session:
            failed = await session.get(RegistrationTeam, source.id)
            assert failed.export_status == "failed"
            assert "team_format_violation" in failed.export_error
