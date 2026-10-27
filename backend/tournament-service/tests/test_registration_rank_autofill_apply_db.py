"""Autofill apply derives every applied row's balancer verdict from ONE post-write resolve, against PostgreSQL.

Two rows in one run take the two verdict branches: one already in the pool (``incomplete``) is re-derived, one
outside it is added. Both verdicts must see the ranks this same run wrote, so both end ``ready``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.models.platform.outbox import EventOutbox
from shared.services.ontology import project_disciplines
from shared.testing import create_test_async_engine
from src.services.registration.lifecycle import lifecycle_service
from src.services.registration.rank_autofill import rank_autofill_service


class AutofillApplyVerdictTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        tag = f"autofill-apply-{self.tag}"
        async with self.Session() as s:
            await project_disciplines(s)
            workspace = models.Workspace(slug=tag, name=tag, disciplines_enabled=["overwatch", "lol"])
            s.add(workspace)
            await s.flush()
            grid = models.DivisionGrid(workspace_id=workspace.id, discipline="lol", slug=tag, name=tag)
            s.add(grid)
            await s.flush()
            version = models.DivisionGridVersion(grid_id=grid.id, version=1, label="v1", status="published")
            s.add(version)
            await s.flush()
            for order, (slug, low, high) in enumerate((("low", 0, 1599), ("plat", 1600, 1699), ("high", 1700, None))):
                s.add(
                    models.DivisionGridTier(
                        version_id=version.id,
                        slug=slug,
                        number=order + 1,
                        name=slug,
                        sort_order=order,
                        rank_min=low,
                        rank_max=high,
                        icon_url=f"/{slug}.png",
                    )
                )
            tournament = models.Tournament(
                workspace_id=workspace.id,
                name=tag,
                slug=tag,
                discipline="lol",
                division_grid_version_id=version.id,
                start_date=datetime.now(UTC),
                end_date=datetime.now(UTC),
            )
            s.add(tournament)
            await s.commit()
            self.workspace_id, self.tournament_id = workspace.id, tournament.id

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            player_ids = set(
                await s.scalars(
                    sa.select(models.WorkspaceMember.player_id).where(
                        models.WorkspaceMember.workspace_id == self.workspace_id
                    )
                )
            )
            await s.execute(
                sa.delete(EventOutbox).where(
                    EventOutbox.payload_json["tournament_id"].as_string() == str(self.tournament_id)
                )
            )
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.User).where(models.User.id.in_(player_ids)))
            await s.commit()
        await self.engine.dispose()

    async def _registration_with_solo_rank(self, s, name: str) -> int:
        """An approved, unranked ``mid`` registration whose player has a fresh Solo/Duo rank to fill it from."""
        registration = await lifecycle_service.create_manual_registration(
            s,
            tournament_id=self.tournament_id,
            display_name=None,
            admin_notes=None,
            answers={"identity_riot": [f"{name}{self.tag}#EUW"]},
            roles=[
                {
                    "role": {"dimension": "position", "role": "mid"},
                    "priority": 0,
                    "is_primary": True,
                    "rank_value": None,
                    "is_active": True,
                }
            ],
        )
        account = await s.scalar(
            sa.select(models.SocialAccount).where(
                models.SocialAccount.user_id == registration.workspace_member.player_id,
                models.SocialAccount.provider == "riot",
            )
        )
        now = datetime.now(UTC)
        s.add_all(
            [
                models.RankAccountState(
                    discipline="lol", social_account_id=account.id, handle=account.username, last_success_at=now
                ),
                models.UserRankSnapshot(
                    discipline="lol",
                    user_id=account.user_id,
                    social_account_id=account.id,
                    handle=account.username,
                    queue="solo",
                    division="PLATINUM",
                    tier=2,
                    lp=50,
                    wins=10,
                    losses=5,
                    rank_value=1650,
                    is_ranked=True,
                    captured_at=now - timedelta(hours=1),
                    source="scheduled",
                ),
            ]
        )
        await s.commit()
        return registration.id

    async def test_both_verdict_branches_see_the_ranks_the_run_wrote(self) -> None:
        async with self.Session() as s:
            pooled = await self._registration_with_solo_rank(s, "Pool")
            joining = await self._registration_with_solo_rank(s, "Join")
            # A manual approved row lands in the pool on creation (unranked: ``incomplete``). The pooled row stays
            # there, so autofill re-derives its verdict; the joining row is taken out, so autofill adds it back.
            await s.execute(
                sa.update(models.Registration)
                .where(models.Registration.id == pooled)
                .values(balancer_status="incomplete")
            )
            await s.execute(
                sa.update(models.Registration)
                .where(models.Registration.id == joining)
                .values(balancer_status="not_in_balancer")
            )
            await s.commit()

        async with self.Session() as s:
            result = await rank_autofill_service.autofill_registration_ranks_from_parsed(
                s, self.tournament_id, registration_ids=[pooled, joining], add_to_balancer=True, apply=True
            )

        assert (result["applied_registrations"], result["balancer_additions"]) == (2, 1)
        async with self.Session() as s:
            verdicts = dict(
                (
                    await s.execute(
                        sa.select(models.Registration.id, models.Registration.balancer_status).where(
                            models.Registration.id.in_([pooled, joining])
                        )
                    )
                ).all()
            )
        assert verdicts == {pooled: "ready", joining: "ready"}
