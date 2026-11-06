"""A published two-tier division grid for a League of Legends workspace.

A ladder-less game rates against a grid of its own, and the roster engine reads it on every
registration read, so a real-DB test of a League tournament has to seed one.
"""

from __future__ import annotations

from typing import Any

from shared.services.ontology import project_disciplines
from src import schemas
from src.services.division_grid.service import division_grid_service


async def seed_lol_grid(session: Any, *, workspace_id: int, suffix: str) -> int:
    """Create, publish and return the id of a LoL grid version (the caller pins it on its tournament).

    The LoL role ontology is not ambient test-DB state (app-service projects it at startup): a LoL tournament's team
    format checks against it, so it is projected here, like the other DB tests do."""
    await project_disciplines(session)
    grid = await division_grid_service.create_grid(
        session,
        workspace_id,
        schemas.DivisionGridCreate(discipline="lol", slug=f"lol-{suffix}", name=f"LoL {suffix}"),
    )
    version = await division_grid_service.create_version(
        session,
        workspace_id,
        grid.id,
        schemas.DivisionGridVersionCreate(
            label="v1",
            tiers=[
                schemas.DivisionGridTierWrite(
                    slug="low", number=1, name="Low", sort_order=1, rank_min=0, rank_max=999, icon_url="/low.png"
                ),
                schemas.DivisionGridTierWrite(
                    slug="high", number=2, name="High", sort_order=2, rank_min=1000, rank_max=None, icon_url="/high.png"
                ),
            ],
        ),
    )
    await division_grid_service.publish_version(session, version.id)
    return version.id
