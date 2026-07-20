"""Map veto/pick step engine for encounters.

The engine runs on an :class:`~shared.models.tournament.encounter_map.EncounterVetoSession`
snapshot (see ``veto_session.py`` for its lifecycle): the action path locks the
session row FOR UPDATE, requires ``status=active`` and reads the step sequence
from ``session.resolved_sequence_json`` — the config is never consulted after
session init. Every action stamps the entry's global ``action_index`` and the
session's ``current_step_started_at``; the final step (a decider counts)
completes the session.

The state read path (``get_map_pool_state``) lazily ensures the session and
never 400s on a missing config/pool: it returns ``session: null`` plus a
``reason`` (``teams_unknown``/``not_configured``) with empty defaults instead.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import MapPickSide, MapPoolEntryStatus, MapVetoSessionStatus
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.services.encounter import veto_session as veto_session_service
from src.services.encounter.realtime_commit import register_map_veto_realtime_update


async def _load_pool(session: AsyncSession, encounter_id: int) -> list[models.EncounterMapPool]:
    result = await session.execute(
        select(models.EncounterMapPool)
        .where(models.EncounterMapPool.encounter_id == encounter_id)
        .order_by(models.EncounterMapPool.order)
    )
    return list(result.scalars().all())


async def get_map_pool(session: AsyncSession, encounter_id: int) -> list[models.EncounterMapPool]:
    pool = await _load_pool(session, encounter_id)
    await auto_complete_decider(session, encounter_id, pool=pool)
    return pool


async def initialize_map_pool(
    session: AsyncSession, encounter_id: int, map_ids: list[int]
) -> list[models.EncounterMapPool]:
    """Admin escape hatch: initialize the map pool from an explicit map list."""
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

    Counts completed actions (everything no longer available) and returns the
    next step. Returns None if the sequence is complete.
    """
    completed = sum(1 for e in pool if e.status != MapPoolEntryStatus.AVAILABLE)
    if completed >= len(veto_sequence):
        return None
    return completed, veto_sequence[completed]


def serialize_map_pool_entry(entry: models.EncounterMapPool) -> dict[str, Any]:
    return {
        "id": entry.id,
        "map_id": entry.map_id,
        "order": entry.order,
        "action_index": entry.action_index,
        "picked_by": entry.picked_by,
        "team_id": entry.team_id,
        "status": entry.status,
    }


def serialize_veto_session(veto: models.EncounterVetoSession) -> dict[str, Any]:
    return {
        "id": veto.id,
        "status": veto.status,
        "first_side": veto.first_side,
        "seed_source": veto.seed_source,
        "home_seed": veto.home_seed,
        "away_seed": veto.away_seed,
        "turn_timer_seconds": veto.turn_timer_seconds,
        "started_at": veto.started_at.isoformat() if veto.started_at else None,
        "current_step_started_at": (
            veto.current_step_started_at.isoformat() if veto.current_step_started_at else None
        ),
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
    entry.action_index = sum(1 for pool_entry in pool if pool_entry.status != MapPoolEntryStatus.AVAILABLE)
    entry.status = MapPoolEntryStatus.PICKED
    entry.picked_by = MapPickSide.DECIDER
    entry.order = sum(1 for pool_entry in pool if pool_entry.status == MapPoolEntryStatus.PICKED)
    return entry


async def auto_complete_decider(
    session: AsyncSession,
    encounter_id: int,
    *,
    veto: models.EncounterVetoSession | None = None,
    pool: list[models.EncounterMapPool] | None = None,
) -> models.EncounterMapPool | None:
    """Resolve a pending decider step from the session snapshot, if any."""
    if veto is None:
        veto = await veto_session_service.get_veto_session(session, encounter_id)
    if veto is None or veto.status != MapVetoSessionStatus.ACTIVE:
        return None

    if pool is None:
        pool = await _load_pool(session, encounter_id)

    entry = auto_complete_decider_entry(veto.resolved_sequence_json, pool)
    if entry is None:
        return None

    veto.current_step_started_at = datetime.now(UTC)
    if get_current_step(veto.resolved_sequence_json, pool) is None:
        veto.status = MapVetoSessionStatus.COMPLETED

    register_map_veto_realtime_update(session, encounter_id)
    await session.commit()
    await session.refresh(entry)
    return entry


def build_unavailable_state(reason: str) -> dict[str, Any]:
    """State response when the room has no session yet (HTTP 200, never 400)."""
    return {
        "session": None,
        "reason": reason,
        "sequence": [],
        "pool": [],
        "viewer_side": None,
        "viewer_can_act": False,
        "allowed_actions": [],
        "current_step_index": None,
        "current_step": None,
        "expected_action": None,
        "turn_side": None,
        "is_complete": False,
    }


def build_map_pool_state(
    veto_sequence: list[str],
    pool: list[models.EncounterMapPool],
    *,
    viewer_side: str | None = None,
    veto: models.EncounterVetoSession | None = None,
) -> dict[str, Any]:
    """Pure state builder over a side-resolved (home/away) token sequence."""
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
        "session": serialize_veto_session(veto) if veto is not None else None,
        "sequence": list(veto_sequence),
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

    # Lazily create the session (idempotent) — the room never 400s on a
    # missing config/pool, it reports why there is no session instead.
    veto = await veto_session_service.ensure_veto_session(session, encounter)
    if veto is None:
        return build_unavailable_state(veto_session_service.unavailable_reason(encounter))

    pool = await get_map_pool(session, encounter_id)
    return build_map_pool_state(
        veto.resolved_sequence_json,
        pool,
        viewer_side=viewer_side,
        veto=veto,
    )


def apply_veto_action(
    veto: models.EncounterVetoSession,
    pool: list[models.EncounterMapPool],
    captain_side: str,
    map_id: int,
    action: str,
    *,
    now: datetime,
) -> models.EncounterMapPool:
    """Pure engine step: validate and apply one ban/pick to the pool + session.

    Mutates the matched pool entry (status, picked_by, action_index, pick
    order) and the session (current_step_started_at; status=completed after
    the final step). Decider steps are resolved by ``auto_complete_decider``,
    not here.
    """
    step = get_current_step(veto.resolved_sequence_json, pool)
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

    # Global veto-action order (bans AND picks), 0-based.
    entry.action_index = sum(1 for e in pool if e.status != MapPoolEntryStatus.AVAILABLE)
    if action == "ban":
        entry.status = MapPoolEntryStatus.BANNED
        entry.picked_by = MapPickSide(captain_side)
    elif action == "pick":
        entry.status = MapPoolEntryStatus.PICKED
        entry.picked_by = MapPickSide(captain_side)
        pick_order = sum(1 for e in pool if e.status == MapPoolEntryStatus.PICKED)
        entry.order = pick_order

    veto.current_step_started_at = now
    if get_current_step(veto.resolved_sequence_json, pool) is None:
        veto.status = MapVetoSessionStatus.COMPLETED
    return entry


async def perform_veto_action(
    session: AsyncSession,
    encounter_id: int,
    captain_side: str,
    map_id: int,
    action: str,
) -> models.EncounterMapPool:
    """Perform a ban or pick action in the veto sequence.

    Locks the veto session row FOR UPDATE (concurrent actions serialize on
    it), requires an active session and validates:
    - It's the correct team's turn
    - The map is still available
    - The action matches the sequence step type
    """
    enc_result = await session.execute(select(models.Encounter).where(models.Encounter.id == encounter_id))
    encounter = enc_result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    veto = await veto_session_service.get_veto_session(session, encounter_id, for_update=True)
    if veto is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map veto session is not initialized for this encounter",
        )
    if veto.status != MapVetoSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Map veto session is {veto.status}",
        )

    pool = await _load_pool(session, encounter_id)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map pool not initialized for this encounter",
        )

    step = get_current_step(veto.resolved_sequence_json, pool)
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Veto sequence is already complete",
        )

    _, step_action = step
    if step_action == "decider":
        resolved = await auto_complete_decider(session, encounter_id, veto=veto, pool=pool)
        if resolved is not None:
            return resolved
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decider step could not be resolved",
        )

    entry = apply_veto_action(veto, pool, captain_side, map_id, action, now=datetime.now(UTC))
    # Denormalize the picking team (mirrors picked_by) for report/UI consumers.
    if entry.picked_by == MapPickSide.HOME:
        entry.team_id = encounter.home_team_id
    elif entry.picked_by == MapPickSide.AWAY:
        entry.team_id = encounter.away_team_id

    register_map_veto_realtime_update(session, encounter_id)
    await session.commit()
    await session.refresh(entry)
    await auto_complete_decider(session, encounter_id, veto=veto, pool=pool)
    return entry
