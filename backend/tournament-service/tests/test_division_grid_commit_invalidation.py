"""A read between a grid write and its commit must not leave the pre-commit row cached.

The writer and the reader are separate connections, so the reader sees the committed row while the write is in
flight; the write's cache invalidation has to land after its commit for a later read to see the new row.
"""

from __future__ import annotations

import asyncio
import uuid

import sqlalchemy as sa

from shared import models
from shared.repository.workspace import WorkspaceRepository
from shared.services.division_grid.access import get_workspace_division_grid_version_id, load_division_grid_snapshot
from shared.testing.db import real_db_sessionmaker
from src import schemas
from src.services.division_grid.service import division_grid_service as grid_service


def _tier(name: str, tier_id: int | None = None) -> schemas.DivisionGridTierWrite:
    return schemas.DivisionGridTierWrite(
        id=tier_id, slug="top", number=1, name=name, sort_order=0, rank_min=0, rank_max=None, icon_url="/top.png"
    )


def test_a_read_between_write_and_commit_cannot_cache_the_old_row() -> None:
    async def run() -> None:
        async with real_db_sessionmaker() as maker:
            tag = uuid.uuid4().hex
            async with maker() as setup:
                workspace = models.Workspace(
                    slug=tag, name=tag, disciplines_enabled=["overwatch"], division_grid_defaults=[]
                )
                setup.add(workspace)
                await setup.flush()
                workspace_id = workspace.id
                grid = models.DivisionGrid(workspace_id=workspace_id, slug=tag, name=tag, versions=[])
                setup.add(grid)
                await setup.flush()
                draft, old, new = [
                    await grid_service.create_version(
                        setup,
                        workspace_id,
                        grid.id,
                        schemas.DivisionGridVersionCreate(label=label, tiers=[_tier("Old")]),
                    )
                    for label in ("draft", "old", "new")
                ]
                draft_id, draft_tier_id, old_id, new_id = draft.id, draft.tiers[0].id, old.id, new.id
                for version_id in (old_id, new_id):
                    await grid_service.publish_version(setup, version_id)
                await WorkspaceRepository().set_default_grid_version(
                    setup, workspace, discipline="overwatch", version_id=old_id
                )
                await setup.commit()
            try:
                # A tier edit: the version snapshot's own key.
                async with maker() as writer, maker() as reader:
                    await grid_service.update_version(
                        writer, draft_id, schemas.DivisionGridVersionUpdate(tiers=[_tier("New", draft_tier_id)])
                    )
                    in_flight = await load_division_grid_snapshot(reader, draft_id)
                    assert [tier.name for tier in in_flight.tiers] == ["Old"]
                    await writer.commit()
                async with maker() as later:
                    snapshot = await load_division_grid_snapshot(later, draft_id)
                    assert [tier.name for tier in snapshot.tiers] == ["New"]

                # An activation: the workspace default, keyed by the workspace's generation.
                async with maker() as writer, maker() as reader:
                    owner = await WorkspaceRepository().get_with_default_grid(writer, workspace_id)
                    await grid_service.activate_version(writer, workspace=owner, version_id=new_id)
                    assert await get_workspace_division_grid_version_id(reader, workspace_id, "overwatch") == old_id
                    await writer.commit()
                async with maker() as later:
                    assert await get_workspace_division_grid_version_id(later, workspace_id, "overwatch") == new_id
            finally:
                async with maker() as cleanup:
                    await cleanup.execute(sa.delete(models.Workspace).where(models.Workspace.id == workspace_id))
                    await cleanup.commit()

    asyncio.run(run())
