"""Shared pick-ban helpers that outlived the legacy map-veto session.

``VetoSessionService`` and the ``MapVetoConfig`` tables are gone. What remains
is the sequence/seed vocabulary ``pick_ban_session`` still calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import MapPickSide, VetoSeedSource
from src import models

REASON_TEAMS_UNKNOWN = "teams_unknown"
REASON_NOT_CONFIGURED = "not_configured"
REASON_SLOT_COUNT_MISMATCH = "slot_count_mismatch"
REASON_SLOT_UNDERFILLED = "slot_underfilled"
REASON_BRACKET_PREVIEW = "bracket_preview"

SLOT_CANDIDATE_FLOOR = 2


@dataclass(frozen=True)
class SeedResolution:
    home_seed: int | None
    away_seed: int | None
    seed_source: VetoSeedSource
    first_side: MapPickSide


def decide_seeds(
    home_slot: int | None,
    away_slot: int | None,
    home_position: int | None,
    away_position: int | None,
) -> SeedResolution:
    """Pure seed decision: bracket slot -> previous-stage standings -> fallback home."""
    if home_slot is not None and away_slot is not None:
        if home_slot == away_slot:
            return SeedResolution(home_slot, away_slot, VetoSeedSource.FALLBACK_HOME, MapPickSide.HOME)
        first = MapPickSide.HOME if home_slot < away_slot else MapPickSide.AWAY
        return SeedResolution(home_slot, away_slot, VetoSeedSource.BRACKET_SLOT, first)
    if home_position is not None and away_position is not None:
        if home_position == away_position:
            return SeedResolution(home_position, away_position, VetoSeedSource.FALLBACK_HOME, MapPickSide.HOME)
        first = MapPickSide.HOME if home_position < away_position else MapPickSide.AWAY
        return SeedResolution(home_position, away_position, VetoSeedSource.STANDINGS, first)
    return SeedResolution(None, None, VetoSeedSource.FALLBACK_HOME, MapPickSide.HOME)


async def resolve_seeds(session: AsyncSession, encounter: models.Encounter) -> SeedResolution:
    """Resolve both teams' seeds for the encounter (snapshot at session init)."""
    home_team_id = encounter.home_team_id
    away_team_id = encounter.away_team_id
    if home_team_id is None or away_team_id is None:
        return decide_seeds(None, None, None, None)
    team_ids = (home_team_id, away_team_id)

    home_slot: int | None = None
    away_slot: int | None = None
    if encounter.stage_item_id is not None:
        rows = await session.execute(
            select(models.StageItemInput.team_id, models.StageItemInput.slot).where(
                models.StageItemInput.stage_item_id == encounter.stage_item_id,
                models.StageItemInput.team_id.in_(team_ids),
            )
        )
        for team_id, slot in rows.all():
            if team_id == home_team_id:
                home_slot = slot
            elif team_id == away_team_id:
                away_slot = slot
    if home_slot is not None and away_slot is not None:
        return decide_seeds(home_slot, away_slot, None, None)

    home_position: int | None = None
    away_position: int | None = None
    if encounter.stage_id is not None:
        # The stage that actually feeds this bracket: follow the TENTATIVE
        # inputs' ``source_stage_item_id`` back to its stage. Plain stage order
        # cannot answer it once a phase runs parallel divisions — "the earlier
        # stage" is then two stages, only one of which holds these teams.
        previous_stage_id = None
        if encounter.stage_item_id is not None:
            previous_stage_id = await session.scalar(
                select(models.StageItem.stage_id)
                .join(
                    models.StageItemInput,
                    models.StageItemInput.source_stage_item_id == models.StageItem.id,
                )
                .where(models.StageItemInput.stage_item_id == encounter.stage_item_id)
                .limit(1)
            )
        if previous_stage_id is None:
            current_order = await session.scalar(
                select(models.Stage.order).where(models.Stage.id == encounter.stage_id)
            )
            if current_order is not None:
                previous_stage_id = await session.scalar(
                    select(models.Stage.id)
                    .where(
                        models.Stage.tournament_id == encounter.tournament_id,
                        models.Stage.order < current_order,
                    )
                    .order_by(models.Stage.order.desc(), models.Stage.id.desc())
                    .limit(1)
                )
        if previous_stage_id is not None:
            rows = await session.execute(
                select(models.Standing.team_id, sa.func.min(models.Standing.position))
                .where(
                    models.Standing.stage_id == previous_stage_id,
                    models.Standing.team_id.in_(team_ids),
                )
                .group_by(models.Standing.team_id)
            )
            for team_id, position in rows.all():
                if team_id == home_team_id:
                    home_position = position
                elif team_id == away_team_id:
                    away_position = position

    return decide_seeds(home_slot, away_slot, home_position, away_position)
