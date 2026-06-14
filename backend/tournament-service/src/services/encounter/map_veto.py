"""Map veto/pick sequence engine for encounters."""

from typing import Any

from fastapi import HTTPException, status
from shared.core.enums import MapPickSide, MapPoolEntryStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models


async def get_veto_config(session: AsyncSession, encounter: models.Encounter) -> models.MapVetoConfig | None:
    """Find applicable veto config: stage-specific first, then tournament-level."""
    if encounter.stage_id:
        result = await session.execute(
            select(models.MapVetoConfig).where(
                models.MapVetoConfig.tournament_id == encounter.tournament_id,
                models.MapVetoConfig.stage_id == encounter.stage_id,
            )
        )
        config = result.scalar_one_or_none()
        if config:
            return config

    result = await session.execute(
        select(models.MapVetoConfig).where(
            models.MapVetoConfig.tournament_id == encounter.tournament_id,
            models.MapVetoConfig.stage_id.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_map_pool(session: AsyncSession, encounter_id: int) -> list[models.EncounterMapPool]:
    result = await session.execute(
        select(models.EncounterMapPool)
        .where(models.EncounterMapPool.encounter_id == encounter_id)
        .order_by(models.EncounterMapPool.order)
    )
    pool = list(result.scalars().all())
    await auto_complete_decider(session, encounter_id, pool=pool)
    return pool


async def initialize_map_pool(
    session: AsyncSession, encounter_id: int, map_ids: list[int]
) -> list[models.EncounterMapPool]:
    """Initialize the map pool for an encounter from the veto config or explicit list."""
    entries = []
    for idx, map_id in enumerate(map_ids):
        entry = models.EncounterMapPool(
            encounter_id=encounter_id,
            map_id=map_id,
            order=idx,
            status=MapPoolEntryStatus.AVAILABLE,
        )
        session.add(entry)
        entries.append(entry)
    await session.commit()
    return entries


def get_current_step(
    veto_sequence: list[str],
    pool: list[models.EncounterMapPool],
) -> tuple[int, str] | None:
    """Determine current step index and action from the veto sequence.

    Counts completed actions (picked/banned) and returns the next step.
    Returns None if sequence is complete.
    """
    completed = sum(1 for e in pool if e.status in (MapPoolEntryStatus.PICKED, MapPoolEntryStatus.BANNED))
    if completed >= len(veto_sequence):
        return None
    return completed, veto_sequence[completed]


def serialize_map_pool_entry(entry: models.EncounterMapPool) -> dict[str, Any]:
    return {
        "id": entry.id,
        "map_id": entry.map_id,
        "order": entry.order,
        "picked_by": entry.picked_by,
        "status": entry.status,
    }


def auto_complete_decider_entry(
    veto_sequence: list[str],
    pool: list[models.EncounterMapPool],
) -> models.EncounterMapPool | None:
    step = get_current_step(veto_sequence, pool)
    if step is None:
        return None

    _, step_action = step
    if step_action != "decider":
        return None

    available = [entry for entry in pool if entry.status == MapPoolEntryStatus.AVAILABLE]
    if len(available) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decider step requires exactly one available map",
        )

    entry = available[0]
    entry.status = MapPoolEntryStatus.PICKED
    entry.picked_by = MapPickSide.DECIDER
    entry.order = sum(1 for pool_entry in pool if pool_entry.status == MapPoolEntryStatus.PICKED)
    return entry


async def auto_complete_decider(
    session: AsyncSession,
    encounter_id: int,
    *,
    encounter: models.Encounter | None = None,
    config: models.MapVetoConfig | None = None,
    pool: list[models.EncounterMapPool] | None = None,
) -> models.EncounterMapPool | None:
    if encounter is None:
        enc_result = await session.execute(select(models.Encounter).where(models.Encounter.id == encounter_id))
        encounter = enc_result.scalar_one_or_none()
        if encounter is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Encounter not found",
            )

    if config is None:
        config = await get_veto_config(session, encounter)
        if config is None:
            return None

    if pool is None:
        pool = await get_map_pool(session, encounter_id)

    entry = auto_complete_decider_entry(config.veto_sequence_json, pool)
    if entry is None:
        return None

    await session.commit()
    await session.refresh(entry)
    return entry


def build_map_pool_state(
    veto_sequence: list[str],
    pool: list[models.EncounterMapPool],
    *,
    viewer_side: str | None = None,
) -> dict[str, Any]:
    current_step = get_current_step(veto_sequence, pool)
    current_step_value: str | None = None
    expected_action: str | None = None
    turn_side: str | None = None
    allowed_actions: list[str] = []

    if current_step is not None:
        _, current_step_value = current_step
        if current_step_value == "decider":
            expected_action = "decider"
        else:
            parts = current_step_value.split("_", 1)
            expected_action = parts[0]
            turn_side = parts[1] if len(parts) > 1 else None

        if viewer_side is not None and turn_side == viewer_side and expected_action in {"pick", "ban"}:
            allowed_actions = [expected_action]

    return {
        "pool": [serialize_map_pool_entry(entry) for entry in pool],
        "viewer_side": viewer_side,
        "viewer_can_act": bool(allowed_actions),
        "allowed_actions": allowed_actions,
        "current_step_index": current_step[0] if current_step is not None else None,
        "current_step": current_step_value,
        "expected_action": expected_action,
        "turn_side": turn_side,
        "is_complete": current_step is None,
    }


async def get_map_pool_state(
    session: AsyncSession,
    encounter_id: int,
    *,
    viewer_side: str | None = None,
) -> dict[str, Any]:
    enc_result = await session.execute(select(models.Encounter).where(models.Encounter.id == encounter_id))
    encounter = enc_result.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    config = await get_veto_config(session, encounter)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No map veto configuration found for this tournament/stage",
        )

    pool = await get_map_pool(session, encounter_id)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map pool not initialized for this encounter",
        )

    return build_map_pool_state(
        config.veto_sequence_json,
        pool,
        viewer_side=viewer_side,
    )


async def perform_veto_action(
    session: AsyncSession,
    encounter_id: int,
    captain_side: str,
    map_id: int,
    action: str,
) -> models.EncounterMapPool:
    """Perform a ban or pick action in the veto sequence.

    Validates:
    - It's the correct team's turn
    - The map is still available
    - The action matches the sequence step type
    """
    # Load encounter for veto config
    enc_result = await session.execute(select(models.Encounter).where(models.Encounter.id == encounter_id))
    encounter = enc_result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    config = await get_veto_config(session, encounter)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No map veto configuration found for this tournament/stage",
        )

    pool = await get_map_pool(session, encounter_id)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map pool not initialized for this encounter",
        )

    step = get_current_step(config.veto_sequence_json, pool)
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Veto sequence is already complete",
        )

    _, step_action = step
    # step_action format: "ban_home", "ban_away", "pick_home", "pick_away", "decider"
    parts = step_action.split("_", 1)
    expected_action = parts[0]
    expected_side = parts[1] if len(parts) > 1 else None

    if expected_side == "decider":
        resolved = await auto_complete_decider(
            session,
            encounter_id,
            encounter=encounter,
            config=config,
            pool=pool,
        )
        if resolved is not None:
            return resolved
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decider step could not be resolved",
        )

    # Validate action type
    if action != expected_action:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected action '{expected_action}', got '{action}'",
        )

    # Validate side
    if expected_side and captain_side != expected_side:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"It's {expected_side} team's turn, not {captain_side}",
        )

    # Find the map entry
    entry = next((e for e in pool if e.map_id == map_id), None)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map is not in the pool for this encounter",
        )
    if entry.status != MapPoolEntryStatus.AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Map is already {entry.status}",
        )

    if action == "ban":
        entry.status = MapPoolEntryStatus.BANNED
        entry.picked_by = MapPickSide(captain_side)
    elif action == "pick":
        entry.status = MapPoolEntryStatus.PICKED
        entry.picked_by = MapPickSide(captain_side)
        pick_order = sum(1 for e in pool if e.status == MapPoolEntryStatus.PICKED)
        entry.order = pick_order

    await session.commit()
    await session.refresh(entry)
    await auto_complete_decider(
        session,
        encounter_id,
        encounter=encounter,
        config=config,
        pool=pool,
    )
    return entry
