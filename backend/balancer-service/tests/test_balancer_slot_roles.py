"""Saved solver slots resolve through the owning tournament's rated dimension."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

for candidate in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from shared import models  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.services.ontology import project_disciplines  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from shared.testing.db import ensure_test_postgres  # noqa: E402
from src.schemas.team import InternalBalancerTeamsPayload  # noqa: E402
from src.services.admin.balancer_variant import BalancerVariantService  # noqa: E402
from tests.factories import formation_node  # noqa: E402


class BalancerSlotRoleTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def test_same_role_code_is_scoped_to_discipline_and_open_slot_has_no_role(self) -> None:
        ensure_test_postgres()
        engine = create_test_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await project_disciplines(session)
                workspace = models.Workspace(slug="saved-slot-test", name="Saved slots")
                session.add(workspace)
                await session.flush()
                for discipline, dimension in (("overwatch", "player_role"), ("lol", "position")):
                    tournament = models.Tournament(
                        workspace_id=workspace.id, discipline=discipline, name=discipline, slug=f"slots-{discipline}"
                    )
                    session.add(tournament)
                    await session.flush()
                    balance = models.BalancerBalance(
                        tournament_id=tournament.id,
                        formation_node_id=await formation_node(session, tournament.id),
                        result_json={},
                    )
                    session.add(balance)
                    await session.flush()
                    team = models.BalancerTeam(
                        balance_id=balance.id, name="A", balancer_name="A", avg_sr=2000, total_sr=4000
                    )
                    session.add(team)
                    await session.flush()
                    payload = InternalBalancerTeamsPayload.model_validate(
                        {
                            "teams": [
                                {
                                    "id": 1,
                                    "name": "A",
                                    "average_mmr": 2000,
                                    "roster": {
                                        role: [{"uuid": str(index), "name": f"Player{index}", "assigned_rating": 2000}]
                                        for index, role in enumerate(("support", "flex"))
                                    },
                                }
                            ]
                        }
                    )
                    await BalancerVariantService().sync(session, balance, payload)
                    slots = (
                        await session.scalars(
                            sa.select(models.BalancerTeamSlot)
                            .where(models.BalancerTeamSlot.team_id == team.id)
                            .order_by(models.BalancerTeamSlot.sort_order)
                        )
                    ).all()
                    assert slots[0].role == "support"
                    assert slots[0].role_row.dimension.code == dimension
                    assert slots[0].role_row.dimension.discipline == discipline
                    assert slots[1].role is None
                    assert slots[1].role_id is None and slots[1].dimension_id is None
                # Retain the team when replacing the prior variant (its FK cascades).
                team.variant_id = None
                await session.flush()
                payload.teams[0].roster["unknown"] = payload.teams[0].roster.pop("support")
                with self.assertRaises(BaseAPIException) as caught:
                    await BalancerVariantService().sync(session, balance, payload)
                assert caught.exception.status_code == 422
                assert "unknown_role" in caught.exception.detail
                await session.rollback()
        finally:
            await engine.dispose()
