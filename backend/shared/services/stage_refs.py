"""Unified resolver for Stage/StageItem references from TournamentGroup.

This module centralises the logic that backfills `stage_id`/`stage_item_id` for
encounters and standings created via legacy flows (Challonge sync, admin
encounter creation with only `tournament_group_id`). It exists during the
groups-to-stages migration period and MUST be used whenever a new encounter is
written to the DB.

Once `tournament_group_id` is fully removed from the encounter write path,
this helper collapses to `(stage_id, stage_item_id)` identity.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.models.stage import Stage, StageItem
from shared.models.tournament import TournamentGroup

__all__ = (
    "StageRefs",
    "resolve_stage_refs_from_group",
    "resolve_stage_refs_from_inputs",
)


@dataclass(frozen=True)
class StageRefs:
    """Canonical encounter/standing stage identity."""

    stage_id: int | None
    stage_item_id: int | None
    tournament_group_id: int | None


async def _load_group(
    session: AsyncSession, group_id: int
) -> TournamentGroup | None:
    result = await session.execute(
        sa.select(TournamentGroup)
        .where(TournamentGroup.id == group_id)
        .options(selectinload(TournamentGroup.stage))
    )
    return result.scalar_one_or_none()


async def _pick_default_stage_item(
    session: AsyncSession,
    stage_id: int,
    hint_name: str | None = None,
) -> int | None:
    items = (
        (
            await session.execute(
                sa.select(StageItem)
                .where(StageItem.stage_id == stage_id)
                .order_by(StageItem.order.asc(), StageItem.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return None
    if hint_name:
        normalized = hint_name.strip().lower()
        for item in items:
            if item.name.strip().lower() == normalized:
                return item.id
    return items[0].id


async def resolve_stage_refs_from_group(
    session: AsyncSession,
    *,
    tournament_id: int,
    tournament_group_id: int | None,
    stage_id: int | None = None,
    stage_item_id: int | None = None,
) -> StageRefs:
    """Resolve canonical stage/stage_item ids for a legacy group reference.

    Priority order:
    1. If caller supplied stage_id AND stage_item_id — use them as-is.
    2. If stage_id is given without stage_item_id — pick first item of that stage.
    3. If only tournament_group_id is given — walk group.stage_id and pick
       a stage_item whose name matches the group (or the first item).
    4. Fall back to the tournament's first stage/item (stable ordering).
    """
    # Case 1 & 2
    if stage_id is not None:
        if stage_item_id is None:
            stage_item_id = await _pick_default_stage_item(session, stage_id)
        return StageRefs(
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            tournament_group_id=tournament_group_id,
        )

    # Case 3
    if tournament_group_id is not None:
        group = await _load_group(session, tournament_group_id)
        if group is not None and group.stage_id is not None:
            resolved_stage_id = group.stage_id
            resolved_item_id = await _pick_default_stage_item(
                session,
                resolved_stage_id,
                hint_name=group.name,
            )
            return StageRefs(
                stage_id=resolved_stage_id,
                stage_item_id=resolved_item_id,
                tournament_group_id=tournament_group_id,
            )

    # Case 4 — fall back to the tournament's first stage.
    stage_row = await session.execute(
        sa.select(Stage.id)
        .where(Stage.tournament_id == tournament_id)
        .order_by(Stage.order.asc(), Stage.id.asc())
        .limit(1)
    )
    first_stage_id = stage_row.scalar_one_or_none()
    if first_stage_id is None:
        return StageRefs(
            stage_id=None,
            stage_item_id=None,
            tournament_group_id=tournament_group_id,
        )

    first_item_id = await _pick_default_stage_item(session, first_stage_id)
    return StageRefs(
        stage_id=first_stage_id,
        stage_item_id=first_item_id,
        tournament_group_id=tournament_group_id,
    )


async def resolve_stage_refs_from_inputs(
    session: AsyncSession,
    *,
    tournament_id: int,
    stage_id: int | None,
    stage_item_id: int | None,
    tournament_group_id: int | None,
) -> StageRefs:
    """Admin-flow resolver: prefers stage_item_id if given, falls back to group."""
    if stage_item_id is not None:
        item = await session.get(StageItem, stage_item_id)
        if item is not None and item.stage_id:
            return StageRefs(
                stage_id=item.stage_id,
                stage_item_id=item.id,
                tournament_group_id=tournament_group_id,
            )
    return await resolve_stage_refs_from_group(
        session,
        tournament_id=tournament_id,
        tournament_group_id=tournament_group_id,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
    )
