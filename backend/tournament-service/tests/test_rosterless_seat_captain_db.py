"""A tournament seat with no ``tournament.team`` behind it (an individual-Swiss round team) against the real Postgres.

Its roster, captain and roles live only in the ``encounter.team_member`` snapshot, so every place that asked
``Team.captain_id`` / ``Player.team_id`` must read the snapshot for such a seat -- and keep reading the team for a
team-backed one.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import sqlalchemy as sa

from shared.core.errors import BaseAPIException
from shared.models import AuthUser, User, WorkspaceMember
from shared.models.catalog.role import RoleDimension
from shared.models.encounter import Encounter
from shared.models.platform.notification import Notification
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.services.encounter.participants import MemberSnapshot, active_teams, place_team
from src.services.encounter import dispute_review
from src.services.encounter.captain import captain_service
from src.services.encounter.ffa import ffa_encounter_service
from src.services.encounter.pick_ban_action import PickBanActionService, RosterlessTarget
from tests._encounter_layer import EncounterLayerCase, add_encounter


class RosterlessSeatTests(EncounterLayerCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        tag = f"rls-{os.getpid()}"
        self.accounts: dict[str, AuthUser] = {}
        async with self.Session() as s:
            dimension = await s.scalar(
                sa.select(RoleDimension.code).where(RoleDimension.discipline == "overwatch", RoleDimension.rated)
            )
            self.assertIsNotNone(dimension, "the overwatch rated role dimension is not seeded")
            members: dict[str, MemberSnapshot] = {}
            for who, role, is_captain in (
                ("cap_a", "tank", True),
                ("mem_a", "damage", False),
                ("cap_b", "support", True),
                ("cap_c", "tank", True),
            ):
                account = AuthUser(
                    email=f"{who}-{tag}-{self.workspace_id}@example.test",
                    username=f"{who}-{self.workspace_id}",
                    is_active=True,
                )
                s.add(account)
                await s.flush()
                user = User(name=f"{who}-{self.workspace_id}", auth_user_id=account.id)
                s.add(user)
                await s.flush()
                member = WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
                s.add(member)
                await s.flush()
                self.accounts[who] = account
                members[who] = MemberSnapshot(
                    workspace_member_id=member.id,
                    display_name=user.name,
                    rank=3000,
                    is_substitute=False,
                    roles=((dimension, role),),
                    is_captain=is_captain,
                )
                setattr(self, f"{who}_user_id", user.id)
            tournament = await s.get_one(Tournament, self.tournament_id)
            # Two round teams, no tournament team behind either.
            rosterless = await add_encounter(s, tournament, self.rule_id, teams=[None, None], stage_id=self.stage_id)
            await place_team(
                s,
                rosterless,
                slot=1,
                team_id=None,
                name="Команда A",
                seed=None,
                members=[members["cap_a"], members["mem_a"]],
            )
            await place_team(
                s, rosterless, slot=2, team_id=None, name="Команда B", seed=None, members=[members["cap_b"]]
            )
            self.rosterless_id = rosterless.id
            # A team-backed encounter whose captain is only the team's live ``captain_id``.
            await s.execute(sa.update(Team).where(Team.id == self.teams[0]).values(captain_id=self.cap_c_user_id))
            self.backed_id = (
                await add_encounter(
                    s, tournament, self.rule_id, teams=[self.teams[0], self.teams[1]], stage_id=self.stage_id
                )
            ).id
            await s.commit()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.execute(
                sa.delete(User).where(User.id.in_([getattr(self, f"{who}_user_id") for who in self.accounts]))
            )
            await s.execute(sa.delete(AuthUser).where(AuthUser.id.in_([a.id for a in self.accounts.values()])))
            await s.commit()
        await self.engine.dispose()

    async def _encounter(self, s, encounter_id: int) -> Encounter:
        return await s.get_one(Encounter, encounter_id)

    async def test_the_snapshot_captain_gets_their_seat(self) -> None:
        async with self.Session() as s:
            encounter = await self._encounter(s, self.rosterless_id)
            seat, player_id = await captain_service.captain_seat(s, self.accounts["cap_a"], encounter)
            self.assertEqual(("Команда A", self.cap_a_user_id), (seat.name, player_id))
            self.assertIsNone(seat.team_id)
            other, _ = await captain_service.captain_seat(s, self.accounts["cap_b"], encounter)
            self.assertEqual("Команда B", other.name)

    async def test_a_non_captain_member_is_refused(self) -> None:
        async with self.Session() as s:
            encounter = await self._encounter(s, self.rosterless_id)
            with self.assertRaises(BaseAPIException) as caught:
                await captain_service.captain_seat(s, self.accounts["mem_a"], encounter)
            self.assertEqual(403, caught.exception.status_code)
            with self.assertRaises(BaseAPIException) as outsider:
                await captain_service.captain_seat(s, self.accounts["cap_c"], encounter)
            self.assertEqual(403, outsider.exception.status_code)

    async def test_a_team_backed_seat_still_resolves_through_team_captain_id(self) -> None:
        async with self.Session() as s:
            encounter = await self._encounter(s, self.backed_id)
            seat, player_id = await captain_service.captain_seat(s, self.accounts["cap_c"], encounter)
            self.assertEqual((self.teams[0], self.cap_c_user_id), (seat.team_id, player_id))
            with self.assertRaises(BaseAPIException):
                await captain_service.captain_seat(s, self.accounts["cap_a"], encounter)

    async def test_a_tournament_encounter_has_no_own_member(self) -> None:
        async with self.Session() as s:
            encounter = await self._encounter(s, self.rosterless_id)
            seat, _player, is_captain, own = await captain_service.resolve_participant(
                s, self.accounts["cap_a"], encounter
            )
            self.assertEqual((True, None), (is_captain, own))
            self.assertEqual("Команда A", seat.name)

    async def test_chat_treats_the_snapshot_captain_as_a_participant_captain(self) -> None:
        async with self.Session() as s:
            encounter = await self._encounter(s, self.rosterless_id)
            self.assertTrue(await ffa_encounter_service.is_participant_captain(s, self.accounts["cap_a"], encounter))
            self.assertFalse(await ffa_encounter_service.is_participant_captain(s, self.accounts["mem_a"], encounter))
            backed = await self._encounter(s, self.backed_id)
            self.assertTrue(await ffa_encounter_service.is_participant_captain(s, self.accounts["cap_c"], backed))

    async def test_a_game_dispute_pages_the_snapshot_captains(self) -> None:
        async with self.Session() as s:
            encounter = await self._encounter(s, self.rosterless_id)
            seats = await active_teams(s, encounter.id)
            game = SimpleNamespace(id=1, position=1, map_id=None)
            await dispute_review.notify_dispute(s, encounter, seats=seats, actor_auth_user_id=None, game=game)  # type: ignore[arg-type]
            await s.commit()
            paged = set(
                await s.scalars(
                    sa.select(Notification.recipient_auth_user_id).where(
                        Notification.kind == "encounter.report_disputed",
                        Notification.recipient_auth_user_id.in_([account.id for account in self.accounts.values()]),
                    )
                )
            )
        self.assertEqual({self.accounts["cap_a"].id, self.accounts["cap_b"].id}, paged)

    async def test_hero_ban_targets_list_the_snapshot_members(self) -> None:
        async with self.Session() as s:
            seats = await active_teams(s, self.rosterless_id)
            rosters = await PickBanActionService()._load_rosters(s, seats, "overwatch")
        by_name = {seat.name: [(p.name.split("-")[0], p.role) for p in rosters[seat.id]] for seat in seats}
        self.assertEqual(
            {"Команда A": [("cap_a", "tank"), ("mem_a", "damage")], "Команда B": [("cap_b", "support")]}, by_name
        )
        self.assertTrue(all(isinstance(p, RosterlessTarget) for players in rosters.values() for p in players))

    async def test_a_team_backed_seat_beside_a_rosterless_one_follows_the_live_team_captain(self) -> None:
        # The team's captain was transferred after the seat was snapshotted: the old captain is still the snapshot's
        # ``is_captain``, the new one is a plain snapshot member. Only ``Team.captain_id`` decides a team-backed seat.
        async with self.Session() as s:
            dimension = await s.scalar(
                sa.select(RoleDimension.code).where(RoleDimension.discipline == "overwatch", RoleDimension.rated)
            )
            snapshots: dict[str, MemberSnapshot] = {}
            for who, is_captain in (("old_cap", True), ("new_cap", False)):
                account = AuthUser(
                    email=f"{who}-{self.workspace_id}@example.test",
                    username=f"{who}-{self.workspace_id}",
                    is_active=True,
                )
                s.add(account)
                await s.flush()
                user = User(name=f"{who}-{self.workspace_id}", auth_user_id=account.id)
                s.add(user)
                await s.flush()
                member = WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
                s.add(member)
                await s.flush()
                self.accounts[who] = account
                setattr(self, f"{who}_user_id", user.id)
                snapshots[who] = MemberSnapshot(
                    workspace_member_id=member.id,
                    display_name=user.name,
                    rank=3000,
                    is_substitute=False,
                    roles=((dimension, "tank"),),
                    is_captain=is_captain,
                )
            rosterless_captain = MemberSnapshot(
                workspace_member_id=await s.scalar(
                    sa.select(WorkspaceMember.id).where(WorkspaceMember.player_id == self.cap_c_user_id)
                ),
                display_name="cap_c",
                rank=3000,
                is_substitute=False,
                roles=((dimension, "damage"),),
                is_captain=True,
            )
            await s.execute(sa.update(Team).where(Team.id == self.teams[1]).values(captain_id=self.new_cap_user_id))
            tournament = await s.get_one(Tournament, self.tournament_id)
            mixed = await add_encounter(s, tournament, self.rule_id, teams=[None, None], stage_id=self.stage_id)
            await place_team(s, mixed, slot=1, team_id=None, name="Команда C", seed=None, members=[rosterless_captain])
            await place_team(
                s,
                mixed,
                slot=2,
                team_id=self.teams[1],
                name="t1",
                seed=None,
                members=[snapshots["old_cap"], snapshots["new_cap"]],
            )
            await s.commit()
            encounter = await s.get_one(Encounter, mixed.id)
            seat, player_id = await captain_service.captain_seat(s, self.accounts["new_cap"], encounter)
            self.assertEqual((self.teams[1], self.new_cap_user_id), (seat.team_id, player_id))
            with self.assertRaises(BaseAPIException) as refused:
                await captain_service.captain_seat(s, self.accounts["old_cap"], encounter)
            self.assertEqual(403, refused.exception.status_code)
            rosterless_seat, _ = await captain_service.captain_seat(s, self.accounts["cap_c"], encounter)
            self.assertIsNone(rosterless_seat.team_id)
