"""Individual Swiss on its stage node: the pool is the node's input, the qualification lock completes the node."""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.registration.registration import Registration, RegistrationRole
from shared.repository import CatalogRoleRepository
from shared.services.encounter.participants import active_teams
from shared.services.encounter.result import apply_result
from shared.testing.factories import add_entry
from src.schemas import individual_swiss as swiss_schemas
from src.services.flow.engine import flow_engine
from src.services.flow.lifecycle import flow_node_service
from src.services.individual_swiss.pins import pins_service
from src.services.individual_swiss.qualification import qualification_service
from src.services.standings.service import standings_service
from tests._flow_case import FlowCase

#: Two tanks, four damage, four support are the first ten approvals (the filter's top 10), then one more each of
#: damage and support: all twelve would not split into equal teams, the ten do (2 teams of tank 1 / damage 2 / support 2).
ROLES = ["tank"] * 2 + ["damage"] * 4 + ["support"] * 4 + ["damage", "support"]
INPUT_SIZE = 10


class SwissNodeTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.stage_id, self.stage_node = await self.stage(
            enums.StageType.INDIVIDUAL_SWISS, max_rounds=1, playoff_team_count=1
        )
        self.registration_node = await self.node("registration", "closed")
        self.filter_node = await self.node("filter", "pending", config={"mode": "top", "n": INPUT_SIZE})
        await self.edge(self.registration_node, "participants", self.filter_node, "ranking")
        await self.edge(self.filter_node, "passed", self.stage_node, "participants")
        self.members: list[int] = []
        self.user_ids: list[int] = []
        await self._seed_registrations()
        async with self.Session() as s:
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.id.in_(self.user_ids)))
            await s.commit()

    async def _seed_registrations(self) -> None:
        async with self.Session() as s:
            catalog = await CatalogRoleRepository().rated_rows(s, discipline="overwatch", workspace_id=None)
            for index, role in enumerate(ROLES):
                user = models.User(name=f"{self.tag}-{index}")
                s.add(user)
                await s.flush()
                self.user_ids.append(user.id)
                member = models.WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
                s.add(member)
                await s.flush()
                registration = Registration(
                    tournament_id=self.tournament_id,
                    display_name=f"{role}{index}",
                    workspace_member_id=member.id,
                )
                s.add(registration)
                await s.flush()
                await add_entry(s, self.registration_node, registration.id, status="approved", balancer_status="ready")
                s.add(
                    RegistrationRole(
                        registration_id=registration.id,
                        catalog_role=catalog[role],
                        dimension_id=catalog[role].dimension_id,
                        is_primary=True,
                        priority=0,
                        rank_value=2000 + 100 * index,
                        is_active=True,
                    )
                )
                self.members.append(member.id)
            await s.commit()

    async def _go_live(self) -> None:
        async with self.Session() as s:
            for target in (enums.FlowNodeStatus.READY, enums.FlowNodeStatus.LIVE):
                await flow_node_service.transition(s, self.stage_node, target, actor=None)
            await s.commit()

    async def _play_the_round(self) -> None:
        async with self.Session() as s:
            encounter_id = await s.scalar(
                sa.select(models.BracketEncounter.encounter_id).where(models.BracketEncounter.stage_id == self.stage_id)
            )
            encounter = await s.get_one(models.Encounter, encounter_id)
            first, second = await active_teams(s, encounter_id)
            await apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={first.id: 2, second.id: 0},
                placements={first.id: 1, second.id: 2},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason="test",
            )
            await s.commit()
        async with self.Session() as s:
            await standings_service.recalculate_for_tournament(s, self.tournament_id)

    async def _lock(self) -> swiss_schemas.QualificationLockRead:
        async with self.Session() as s:
            stage = await s.get_one(models.Stage, self.stage_id)
            return await qualification_service.lock(s, stage)

    async def test_start_freezes_only_the_input_members(self) -> None:
        await self._go_live()
        async with self.Session() as s:
            frozen = set(
                await s.scalars(
                    sa.select(models.PlayerStanding.workspace_member_id).where(
                        models.PlayerStanding.stage_id == self.stage_id
                    )
                )
            )
        self.assertEqual(set(self.members[:INPUT_SIZE]), frozen)

    async def test_lock_completes_the_stage_node_and_leaves_tournament_status(self) -> None:
        await self._go_live()
        await self._play_the_round()
        result = await self._lock()

        self.assertTrue(result.qualified)
        self.assertEqual("completed", await self.node_status(self.stage_node))
        async with self.Session() as s:
            self.assertIsNotNone(
                await s.scalar(sa.select(models.Stage.qualification_locked_at).where(models.Stage.id == self.stage_id))
            )
            self.assertEqual(
                {"ready"},
                set(
                    await s.scalars(
                        sa.select(models.RegistrationEntry.balancer_status).where(
                            models.RegistrationEntry.registration_node_id == self.registration_node
                        )
                    )
                ),
            )
            derived = await flow_node_service.sync_tournament_status(s, self.tournament_id)
        self.assertEqual(derived, await self.tournament_status())

    async def test_lock_refused_before_the_rule_holds(self) -> None:
        await self._go_live()
        with self.assertRaises(BaseAPIException) as raised:
            await self._lock()
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("stage_not_completed", raised.exception.detail[0]["code"])
        self.assertEqual("live", await self.node_status(self.stage_node))

    async def test_pins_refused_after_lock(self) -> None:
        await self._go_live()
        await self._play_the_round()
        await self._lock()
        pin = swiss_schemas.PlayerStandingPinWrite(workspace_member_id=self.members[0], position=1)
        async with self.Session() as s:
            stage = await s.get_one(models.Stage, self.stage_id)
            with self.assertRaises(BaseAPIException) as raised:
                await pins_service.set_pins(s, stage, swiss_schemas.PlayerStandingPinsUpdate(pins=[pin]))
        self.assertEqual(409, raised.exception.status_code)
