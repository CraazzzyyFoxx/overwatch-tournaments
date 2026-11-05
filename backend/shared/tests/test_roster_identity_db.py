"""A persisted roster uses only its discipline's provider for handles and ordering (D90)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core.social import normalize_social_handle
from shared.services.roster import roster_engine
from shared.testing import create_test_async_engine
from shared.testing.cache import configure_test_cache


class RosterIdentityTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        configure_test_cache()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"ri-{uuid.uuid4().hex[:12]}"
        self.tournaments = {}
        async with self.Session() as s:
            workspace = models.Workspace(slug=tag, name=tag, disciplines_enabled=["overwatch", "lol"])
            s.add(workspace)
            await s.flush()
            self.workspace_id = workspace.id
            grid = models.DivisionGrid(workspace_id=workspace.id, slug=tag, name=tag, discipline="lol")
            s.add(grid)
            await s.flush()
            version = models.DivisionGridVersion(grid_id=grid.id, version=1, label="v1", status="published")
            s.add(version)
            await s.flush()
            s.add(
                models.DivisionGridTier(
                    version_id=version.id,
                    slug="t-1",
                    number=1,
                    name="T 1",
                    sort_order=0,
                    rank_min=0,
                    rank_max=None,
                    icon_url="/t.png",
                )
            )
            for code in ("overwatch", "lol"):
                tournament = models.Tournament(
                    workspace_id=workspace.id,
                    name=tag,
                    slug=f"{tag}-{code}",
                    discipline=code,
                    division_grid_version_id=version.id if code == "lol" else None,
                )
                s.add(tournament)
                await s.flush()
                node = models.FlowNode(
                    tournament_id=tournament.id, kind="registration", name="R", status="open", config={}
                )
                s.add(node)
                await s.flush()
                registrations = []
                for handles in (
                    {"battlenet": ["Alpha#1234", "Alt#1111"], "riot": ["Zulu Riot#KR1", "Alt Riot#KR2"]},
                    {"battlenet": ["Zulu#1234"], "riot": ["Alpha Riot#KR1"]},
                    {"battlenet" if code == "lol" else "riot": ["Other#1234"]},
                ):
                    registration = models.Registration(
                        tournament_id=tournament.id,
                        identities=[
                            models.RegistrationIdentity(
                                provider=provider,
                                position=position,
                                handle=handle,
                                handle_normalized=normalize_social_handle(provider, handle),
                            )
                            for provider, values in handles.items()
                            for position, handle in enumerate(values)
                        ],
                    )
                    s.add(registration)
                    await s.flush()
                    s.add(models.RegistrationEntry(registration_node_id=node.id, registration_id=registration.id))
                    registrations.append(registration.id)
                self.tournaments[code] = (node.id, registrations)
            await s.commit()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.commit()
        await self.engine.dispose()

    async def test_provider_scopes_primary_extras_order_and_absence(self) -> None:
        for code, (node_id, (first, second, missing)) in self.tournaments.items():
            async with self.Session() as s:
                rosters = await roster_engine.for_registration_node(s, node_id)
            expected = [second, first, missing] if code == "lol" else [first, second, missing]
            assert list(rosters) == expected
            assert (rosters[first].handle, rosters[first].additional_handles) == (
                ("Zulu Riot#KR1", ("Alt Riot#KR2",)) if code == "lol" else ("Alpha#1234", ("Alt#1111",))
            )
            assert rosters[missing].identity is None
            assert rosters[missing].additional_handles == ()
