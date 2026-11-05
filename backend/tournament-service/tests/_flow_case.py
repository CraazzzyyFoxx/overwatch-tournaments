"""Shared base of the flow lifecycle tests: a workspace, an announced tournament and graph-building helpers."""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from datetime import UTC, datetime
from typing import Any
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core import enums
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres
from src import schemas
from src.services.admin.stage import stage_service

_TAG = itertools.count()


class FlowCase(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = f"flw-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            workspace = models.Workspace(slug=self.tag, name=self.tag, disciplines_enabled=["overwatch", "lol"])
            s.add(workspace)
            await s.flush()
            self.workspace_id = workspace.id
            tournament = models.Tournament(
                workspace_id=workspace.id,
                discipline="overwatch",
                name=self.tag,
                slug=self.tag,
                status=enums.TournamentStatus.ANNOUNCEMENT,
                start_date=datetime(2026, 11, 5, tzinfo=UTC),
                end_date=datetime(2026, 11, 6, tzinfo=UTC),
            )
            s.add(tournament)
            await s.flush()
            self.tournament_id = tournament.id
            s.add(models.RegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id))
            self.actor = models.AuthUser(
                email=f"{self.tag}@example.test", username=self.tag, is_active=True, is_superuser=True
            )
            s.add(self.actor)
            await s.commit()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(
                sa.delete(models.EventOutbox).where(
                    models.EventOutbox.payload_json["tournament_id"].as_integer() == self.tournament_id
                )
            )
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.actor.id))
            await s.commit()
        await self.engine.dispose()

    async def node(
        self,
        kind: str,
        status: str = "draft",
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        stage_id: int | None = None,
    ) -> int:
        async with self.Session() as s:
            row = models.FlowNode(
                tournament_id=self.tournament_id,
                kind=kind,
                name=name or kind,
                status=status,
                config=config or {},
                stage_id=stage_id,
            )
            s.add(row)
            await s.commit()
            return row.id

    async def edge(self, source: int, source_port: str, target: int, target_port: str) -> int:
        async with self.Session() as s:
            row = models.FlowEdge(
                tournament_id=self.tournament_id,
                source_node_id=source,
                source_port=source_port,
                target_node_id=target,
                target_port=target_port,
            )
            s.add(row)
            await s.commit()
            return row.id

    async def node_status(self, node_id: int) -> str:
        async with self.Session() as s:
            return await s.scalar(sa.select(models.FlowNode.status).where(models.FlowNode.id == node_id))

    async def tournament_status(self) -> enums.TournamentStatus:
        async with self.Session() as s:
            return await s.scalar(sa.select(models.Tournament.status).where(models.Tournament.id == self.tournament_id))

    async def outbox(self, routing_key: str) -> list[dict]:
        async with self.Session() as s:
            rows = await s.scalars(
                sa.select(models.EventOutbox.payload_json)
                .where(
                    models.EventOutbox.routing_key == routing_key,
                    models.EventOutbox.payload_json["tournament_id"].as_integer() == self.tournament_id,
                )
                .order_by(models.EventOutbox.id)
            )
            return list(rows)

    async def stage(
        self, stage_type: enums.StageType = enums.StageType.ROUND_ROBIN, *, order: int = 1, name: str = "S"
    ) -> tuple[int, int]:
        """A stage through the admin service and the node ``create_stage`` made for it."""
        async with self.Session() as s:
            created = await stage_service.create_stage(
                s, self.tournament_id, schemas.StageCreate(name=name, stage_type=stage_type, order=order)
            )
            node_id = await s.scalar(sa.select(models.FlowNode.id).where(models.FlowNode.stage_id == created.id))
        return created.id, node_id
