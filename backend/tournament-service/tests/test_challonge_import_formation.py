"""A Challonge import completes the formation node once the tournament has teams, so its first stage can go ready."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

from shared import models
from shared.core.enums import FlowNodeStatus as S
from shared.core.enums import StageItemType
from src.services.challonge import sync as challonge_sync
from src.services.challonge.sync import locking as sync_locking
from src.services.flow.lifecycle import flow_node_service
from tests._flow_case import FlowCase
from tests.test_challonge_sync_hardening import _Redis


class ImportedFormationTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.registration = await self.node("registration", config={"check_in": False, "intake": "team"})
        self.formation = await self.node("formation", config={"mode": "balancer"})
        await self.edge(self.registration, "participants", self.formation, "players")
        stage_id, self.stage_node = await self.stage()
        async with self.Session() as s:
            s.add(models.StageItem(stage_id=stage_id, name="A", type=StageItemType.GROUP, order=0))
            s.add(models.ChallongeSource(tournament_id=self.tournament_id, challonge_tournament_id=5))
            await s.commit()
        self.redis = _Redis()

    async def add_teams(self) -> None:
        async with self.Session() as s:
            s.add_all(
                models.Team(tournament_id=self.tournament_id, name=f"T{i}", balancer_name=f"T{i}") for i in range(2)
            )
            await s.commit()

    async def sync(self) -> None:
        with (
            patch.object(sync_locking, "_get_redis", AsyncMock(return_value=self.redis)),
            patch.object(challonge_sync.challonge_client, "fetch_matches", AsyncMock(return_value=[])),
            patch.object(challonge_sync.challonge_client, "fetch_participants", AsyncMock(return_value=[])),
        ):
            async with self.Session() as s:
                await challonge_sync.sync_service.import_tournament(s, self.tournament_id)

    async def test_import_completes_the_formation_and_the_first_stage_can_go_ready(self) -> None:
        await self.add_teams()
        await self.sync()
        self.assertEqual("completed", await self.node_status(self.formation))
        async with self.Session() as s:
            formation = await s.get_one(models.FlowNode, self.formation)
            registrations = await s.scalar(
                sa.select(sa.func.count()).where(
                    models.FlowNode.tournament_id == self.tournament_id, models.FlowNode.kind == "registration"
                )
            )
        self.assertEqual("manual", formation.config["mode"])
        self.assertEqual(0, registrations, "an import has no registration to wait for")
        async with self.Session() as s:
            await flow_node_service.transition(s, self.stage_node, S.READY, actor=self.actor)
            await s.commit()
        self.assertEqual("ready", await self.node_status(self.stage_node))

    async def test_a_resync_leaves_a_completed_formation_alone(self) -> None:
        await self.add_teams()
        await self.sync()
        await self.sync()
        self.assertEqual("completed", await self.node_status(self.formation))

    async def test_a_tournament_without_teams_keeps_its_formation(self) -> None:
        await self.sync()
        self.assertEqual("draft", await self.node_status(self.formation))
        self.assertEqual("draft", await self.node_status(self.registration))

    async def test_an_open_registration_keeps_the_formation_waiting(self) -> None:
        await self.add_teams()
        async with self.Session() as s:
            await s.execute(
                sa.update(models.FlowNode).where(models.FlowNode.id == self.registration).values(status="open")
            )
            await s.commit()
        await self.sync()
        self.assertEqual(
            ("open", "draft"), (await self.node_status(self.registration), await self.node_status(self.formation))
        )
