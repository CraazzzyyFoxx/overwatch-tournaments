"""A formation node owns its teams, balance, config and draft: exports, uniques and gates are per node (spec §4.6, §5.2).

Needs the test Postgres; skips otherwise.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core.enums import DraftStatus
from shared.core.errors import ApiHTTPException
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import RosterShape
from shared.domain.team_format import FormatDimension, FormatRule, TeamFormat
from shared.schemas.identity import PlayerIdentityRead
from shared.services.team_format import save_tournament_format
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres
from src import schemas
from src.services.admin.balancer import balancer_admin_service
from src.services.draft.lifecycle import lifecycle_service
from src.services.registered_teams import registered_teams_service
from src.services.team_export import (
    ExportPlan,
    MaterializationMember,
    MaterializationTeam,
    registered,
    sync_player_ranks,
    team_materialization,
)
from src.services.team_export.materialization import materialize_teams
from src.services.team_export.registered import build_registered_export
from tests.factories import formation_node, wire_input

_TAG = itertools.count()


def _code(caught) -> str:
    [detail] = caught.exception.detail
    return detail["code"]


def _team(name: str, *member_ids: int) -> MaterializationTeam:
    return MaterializationTeam(
        balancer_name=name,
        members=tuple(
            MaterializationMember(name=f"{name}-{i}", rank=2000, slot_code="tank", workspace_member_id=member_id)
            for i, member_id in enumerate(member_ids)
        ),
    )


class FormationScopeTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = f"fscope-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            workspace = models.Workspace(slug=self.tag, name=self.tag)
            s.add(workspace)
            await s.flush()
            self.workspace_id = workspace.id
            tournament = models.Tournament(
                workspace_id=workspace.id, discipline="overwatch", name=self.tag, slug=self.tag
            )
            s.add(tournament)
            await s.flush()
            self.tournament_id = tournament.id
            await save_tournament_format(
                s,
                tournament,
                TeamFormat(
                    discipline="overwatch",
                    name="Two seats",
                    starter_min=2,
                    starter_max=2,
                    dimensions=(FormatDimension("player_role", "enforced"),),
                    rules=(FormatRule("player_role", "tank", 2, 2),),
                ),
            )
            self.members: list[int] = []
            for i in range(2):
                user = models.User(name=f"{self.tag}-{i}")
                s.add(user)
                await s.flush()
                member = models.WorkspaceMember(workspace_id=workspace.id, player_id=user.id)
                s.add(member)
                await s.flush()
                self.members.append(member.id)
            self.a = await formation_node(s, tournament.id, mode="draft")
            self.b = await formation_node(s, tournament.id, mode="draft")
            await s.commit()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.slug == self.tag))
            await s.commit()
        await self.engine.dispose()

    async def _team(self, s, node_id: int, name: str, *, standing: bool = False) -> int:
        team = models.Team(name=name, balancer_name=name, tournament_id=self.tournament_id, formation_node_id=node_id)
        s.add(team)
        await s.flush()
        s.add(
            models.Player(
                name=f"{name}-p",
                rank=2000,
                tournament_id=self.tournament_id,
                formation_node_id=node_id,
                team_id=team.id,
                workspace_member_id=self.members[0],
            )
        )
        if standing:
            s.add(models.Standing(tournament_id=self.tournament_id, team_id=team.id, position=1, matches=0, points=0))
        await s.flush()
        return team.id

    async def _teams(self, s) -> dict[str, int | None]:
        rows = await s.execute(sa.select(models.Team.name, models.Team.formation_node_id))
        return dict(rows.all())

    async def test_export_deletes_only_its_own_nodes_teams(self) -> None:
        async with self.Session() as s:
            ta = await self._team(s, self.a, "TA", standing=True)
            tb = await self._team(s, self.b, "TB")
            await s.commit()
            await team_materialization.run(
                s,
                ExportPlan(
                    tournament_id=self.tournament_id,
                    formation_node_id=self.b,
                    teams=[_team("New", self.members[1])],
                    prior_team_ids=[tb, ta],
                ),
            )
            teams = await s.execute(
                sa.select(models.Team.id, models.Team.name, models.Team.formation_node_id).where(
                    models.Team.tournament_id == self.tournament_id
                )
            )
            by_id = {row.id: row for row in teams}
            self.assertIn(ta, by_id)
            self.assertNotIn(tb, by_id)
            [new] = [row for row in by_id.values() if row.name == "New"]
            self.assertEqual(new.formation_node_id, self.b)
            self.assertEqual(
                (
                    await s.scalars(
                        sa.select(models.Standing.team_id).where(models.Standing.tournament_id == self.tournament_id)
                    )
                ).all(),
                [ta],
            )
            players = (
                await s.scalars(sa.select(models.Player.team_id).where(models.Player.team_id.in_([ta, tb])))
            ).all()
            self.assertEqual(players, [ta])

    async def test_export_ignores_standings_of_other_formations(self) -> None:
        async with self.Session() as s:
            await self._team(s, self.a, "TA", standing=True)
            await s.commit()
            outcome = await team_materialization.run(
                s,
                ExportPlan(
                    tournament_id=self.tournament_id,
                    formation_node_id=self.b,
                    teams=[_team("New", self.members[1])],
                    guard_standings=True,
                ),
            )
            self.assertEqual(outcome.imported_teams, 1)

    async def test_re_export_adopts_the_legacy_teams_its_source_rows_link_to(self) -> None:
        async with self.Session() as s:
            legacy = await self._team(s, None, "Alpha", standing=True)
            await s.commit()
            outcome = await team_materialization.run(
                s,
                ExportPlan(
                    tournament_id=self.tournament_id,
                    formation_node_id=self.b,
                    teams=[_team("Alpha", self.members[0])],
                    prior_team_ids=[legacy],
                    guard_standings=True,
                ),
            )
            self.assertEqual(outcome.removed_teams, 1)
            teams = (
                await s.execute(
                    sa.select(models.Team.id, models.Team.formation_node_id).where(
                        models.Team.tournament_id == self.tournament_id
                    )
                )
            ).all()
            self.assertEqual([row.formation_node_id for row in teams], [self.b])
            self.assertNotIn(legacy, [row.id for row in teams])
            players = (
                await s.scalars(sa.select(models.Player.formation_node_id).where(models.Player.name.like("Alpha%")))
            ).all()
            self.assertEqual(players, [self.b])

    async def test_a_new_formation_leaves_unrelated_legacy_teams_alone(self) -> None:
        async with self.Session() as s:
            legacy = await self._team(s, None, "Legacy", standing=True)
            await s.commit()
            outcome = await team_materialization.run(
                s,
                ExportPlan(
                    tournament_id=self.tournament_id,
                    formation_node_id=self.b,
                    teams=[_team("New", self.members[1])],
                    guard_standings=True,
                ),
            )
            self.assertEqual(outcome.imported_teams, 1)
            self.assertEqual(await s.scalar(sa.select(models.Team.id).where(models.Team.id == legacy)), legacy)
            self.assertEqual(
                await s.scalar(sa.select(models.Player.id).where(models.Player.team_id == legacy)) is not None, True
            )
            self.assertEqual(
                await s.scalar(sa.select(models.Standing.team_id).where(models.Standing.team_id == legacy)), legacy
            )

    async def test_guard_fires_on_standings_of_the_nodes_teams_the_export_does_not_replace(self) -> None:
        async with self.Session() as s:
            await self._team(s, self.b, "Mine", standing=True)
            await s.commit()
            with self.assertRaises(ApiHTTPException) as caught:
                await team_materialization.run(
                    s,
                    ExportPlan(
                        tournament_id=self.tournament_id,
                        formation_node_id=self.b,
                        teams=[_team("New", self.members[1])],
                        guard_standings=True,
                    ),
                )
            self.assertEqual(_code(caught), "standings_exist")

    async def test_rank_sync_reaches_the_legacy_players_of_linked_teams(self) -> None:
        async with self.Session() as s:
            legacy = await self._team(s, None, "Alpha")
            await sync_player_ranks(
                s,
                self.b,
                [MaterializationTeam("Alpha", (MaterializationMember(name="Alpha-p", rank=3100, slot_code="tank"),))],
                linked_team_ids=[legacy],
            )
            rank = await s.scalar(sa.select(models.Player.rank).where(models.Player.team_id == legacy))
            self.assertEqual(rank, 3100)

    async def test_same_member_placed_in_two_formations(self) -> None:
        async with self.Session() as s:
            for node_id in (self.a, self.b):
                await materialize_teams(s, self.tournament_id, node_id, [_team("Alpha", self.members[0])])
            await s.commit()
            rows = await s.execute(
                sa.select(models.Player.formation_node_id, models.Team.id)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .where(models.Player.tournament_id == self.tournament_id)
            )
            placed = rows.all()
            self.assertEqual(sorted(row.formation_node_id for row in placed), sorted([self.a, self.b]))
            self.assertEqual(len({row.id for row in placed}), 2)

    async def test_balance_is_unique_per_formation_node(self) -> None:
        async with self.Session() as s:
            for node_id in (self.a, self.b):
                s.add(
                    models.BalancerBalance(tournament_id=self.tournament_id, formation_node_id=node_id, result_json={})
                )
            await s.commit()
            s.add(models.BalancerBalance(tournament_id=self.tournament_id, formation_node_id=self.a, result_json={}))
            with self.assertRaises(IntegrityError):
                await s.commit()

    async def _create_draft(self, s, node_id: int):
        return await lifecycle_service.create_for_tournament(
            s,
            schemas.DraftSessionCreateRequest(formation_node_id=node_id),
            tournament_id=self.tournament_id,
            workspace_id=self.workspace_id,
            actor_user_id=0,
        )

    async def test_one_active_draft_per_formation_node(self) -> None:
        async with self.Session() as s:
            await self._create_draft(s, self.a)
            await self._create_draft(s, self.b)
            with self.assertRaises(ApiHTTPException) as caught:
                await self._create_draft(s, self.a)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(_code(caught), "draft_already_active")

    async def test_a_draft_takes_the_format_of_its_own_node(self) -> None:
        custom = {"format": "custom", "round_rules": ["reverse"], "avg_tie_seed_reverse": True}
        async with self.Session() as s:
            other = await formation_node(s, self.tournament_id, mode="draft")
            for node_id, rule in ((self.a, custom), (other, {"format": "linear"})):
                await s.execute(
                    sa.update(models.FlowNode)
                    .where(models.FlowNode.id == node_id)
                    .values(config={"mode": "draft", "draft_format": rule})
                )
            first, second = await self._create_draft(s, self.a), await self._create_draft(s, other)
            self.assertEqual((first.format, second.format), ("custom", "linear"))
            self.assertEqual(first.settings_json["round_rules"][0], "reverse")
            self.assertEqual(len(first.settings_json["round_rules"]), first.rounds)
            self.assertTrue(first.settings_json["avg_tie_seed_reverse"])
            self.assertNotIn("round_rules", second.settings_json)

    async def test_draft_start_needs_forming_node(self) -> None:
        async with self.Session() as s:
            draft = await self._create_draft(s, self.a)
            draft.status = DraftStatus.READY.value
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == self.a).values(status="draft"))
            with self.assertRaises(ApiHTTPException) as caught:
                await lifecycle_service.start(s, draft)
            self.assertEqual(_code(caught), "formation_not_forming")
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == self.a).values(status="forming"))
            with self.assertRaises(ApiHTTPException) as caught:
                await lifecycle_service.start(s, draft)
            self.assertEqual(_code(caught), "draft_no_picks")

    async def test_a_tournament_draft_must_name_its_node(self) -> None:
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await lifecycle_service.create_session(
                    s,
                    workspace_id=self.workspace_id,
                    tournament_id=self.tournament_id,
                    shape=RosterShape(entries=(("tank", 2),)),
                )
            self.assertEqual(_code(caught), "formation_node_required")

    async def test_draft_needs_draft_mode_node(self) -> None:
        async with self.Session() as s:
            balancer_node = await formation_node(s, self.tournament_id, mode="balancer")
            with self.assertRaises(ApiHTTPException) as caught:
                await self._create_draft(s, balancer_node)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(_code(caught), "tournament_not_draft_formation")

    async def test_export_refused_unless_forming(self) -> None:
        async with self.Session() as s:
            node = await formation_node(s, self.tournament_id, status="completed")
            balance = models.BalancerBalance(tournament_id=self.tournament_id, formation_node_id=node, result_json={})
            s.add(balance)
            await s.commit()
            with self.assertRaises(ApiHTTPException) as caught:
                await balancer_admin_service.export_balance(s, balance.id, actor_user_id=0)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(_code(caught), "formation_not_forming")

    async def test_export_refused_unless_the_node_forms_that_way(self) -> None:
        async with self.Session() as s:
            node = await formation_node(s, self.tournament_id, mode="registered")
            balance = models.BalancerBalance(tournament_id=self.tournament_id, formation_node_id=node, result_json={})
            s.add(balance)
            await s.commit()
            with self.assertRaises(ApiHTTPException) as caught:
                await balancer_admin_service.export_balance(s, balance.id, actor_user_id=0)
            self.assertEqual(_code(caught), "formation_wrong_mode")
            with self.assertRaises(ApiHTTPException) as caught:  # self.a forms by draft
                await registered_teams_service.export_registered(s, self.tournament_id, self.a, actor_user_id=0)
            self.assertEqual(_code(caught), "formation_wrong_mode")

    async def test_materialization_skips_a_member_already_on_a_tournament_wide_team(self) -> None:
        async with self.Session() as s:
            await self._team(s, None, "Manual")  # a tournament-wide team seating members[0]
            result = await materialize_teams(
                s, self.tournament_id, self.b, [_team("Alpha", self.members[0], self.members[1])]
            )
            self.assertEqual(result.skipped_members, 1)
            placed = await s.scalars(
                sa.select(models.Player.workspace_member_id).where(
                    models.Player.tournament_id == self.tournament_id, models.Player.name.like("Alpha%")
                )
            )
            self.assertEqual(list(placed), [self.members[1]])

    async def test_registered_export_takes_only_the_formations_input(self) -> None:
        async with self.Session() as s:
            nodes = {}
            for formation, name, member in ((self.a, "TeamA", self.members[0]), (self.b, "TeamB", self.members[1])):
                registration_node = await wire_input(s, formation)
                nodes[formation] = registration_node
                team = models.RegistrationTeam(
                    tournament_id=self.tournament_id,
                    registration_node_id=registration_node,
                    workspace_id=self.workspace_id,
                    name=name,
                    name_normalized=name.lower(),
                    status="complete",
                )
                s.add(team)
                await s.flush()
                registration = models.Registration(
                    tournament_id=self.tournament_id,
                    workspace_member_id=member,
                    registration_team_id=team.id,
                    team_slot_code="tank",
                )
                s.add(registration)
                await s.flush()
                s.add(
                    models.RegistrationEntry(
                        registration_node_id=registration_node, registration_id=registration.id, status="approved"
                    )
                )
                if formation == self.a:
                    # Formation A's export left a legacy (tournament-wide) team linked to its source team.
                    legacy = await self._team(s, None, "TeamA")
                    team.exported_team_id = legacy
            await s.flush()

            async def resolve(_session, registrations, **_kwargs):
                return {
                    r.id: PlayerRoster(
                        registration_id=r.id,
                        identity=PlayerIdentityRead.of("battlenet", f"P#{r.id}"),
                        display_name=None,
                        player_id=None,
                        auth_user_id=None,
                        workspace_member_id=r.workspace_member_id,
                        roles=(),
                        is_full_flex=False,
                    )
                    for r in registrations
                }

            shape = RosterShape(entries=(("tank", 1),))
            with patch.object(registered.roster_engine, "resolve", resolve):
                for_b = await build_registered_export(s, self.tournament_id, shape, [nodes[self.b]])
                for_a = await build_registered_export(s, self.tournament_id, shape, [nodes[self.a]])
            self.assertEqual([team.balancer_name for team in for_b.teams], ["TeamB"])
            self.assertEqual(for_b.prior_team_ids, [])  # A's linked legacy team is not B's to adopt
            self.assertEqual([team.balancer_name for team in for_a.teams], ["TeamA"])
            self.assertEqual(len(for_a.prior_team_ids), 1)
