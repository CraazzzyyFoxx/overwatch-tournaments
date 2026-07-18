"""Veto session lifecycle: config cascade, seed resolution, init/reset hooks.

An :class:`~shared.models.tournament.encounter_map.EncounterVetoSession` is the
1:1 snapshot of one encounter's veto room. It is created idempotently
(``ensure_veto_session``) once both teams are known and a config resolves via
the ``(stage, round) -> (stage, NULL) -> (NULL, NULL)`` cascade, freezing the
seed resolution and the side-resolved step sequence so later config edits or
standings recalculations never change a running veto. Resetting = delete the
session + pool rows and re-create.

Commit semantics mirror ``map_veto.initialize_map_pool``: the lifecycle
functions commit internally by default; the team-change hook runs with
``commit=False`` inside the caller's transaction (bracket propagation / admin
encounter updates own the commit boundary there).

The step engine itself (turn validation, action application, decider
auto-resolve) lives in ``map_veto.py``; this module must not import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.enums import MapPickSide, MapPoolEntryStatus, MapVetoSessionStatus, VetoSeedSource
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.services.encounter.realtime_commit import register_map_veto_realtime_update

# Side-agnostic step tokens allowed on MapVetoConfig.veto_sequence_json.
VETO_SEQUENCE_TOKENS = frozenset({"ban_first", "ban_second", "pick_first", "pick_second", "decider"})

# ``session: null`` reasons on the state read path (mirrors the frontend's
# VetoUnavailableReason union).
REASON_TEAMS_UNKNOWN = "teams_unknown"
REASON_NOT_CONFIGURED = "not_configured"


# ── config validation & cascade ─────────────────────────────────────────────


def validate_veto_config(sequence: list[str], map_ids: list[int]) -> None:
    """Validate a config upsert body (sequence tokens + map pool coherence)."""
    if not sequence:
        raise HTTPException(status_code=422, detail="sequence must not be empty")
    invalid = sorted({token for token in sequence if token not in VETO_SEQUENCE_TOKENS})
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid sequence token(s): {', '.join(invalid)}")
    decider_positions = [idx for idx, token in enumerate(sequence) if token == "decider"]
    if len(decider_positions) > 1:
        raise HTTPException(status_code=422, detail="sequence may contain at most one decider step")
    if decider_positions and decider_positions[0] != len(sequence) - 1:
        raise HTTPException(status_code=422, detail="decider must be the last step of the sequence")
    if not map_ids:
        raise HTTPException(status_code=422, detail="map_ids must not be empty")
    if len(set(map_ids)) != len(map_ids):
        raise HTTPException(status_code=422, detail="map_ids must be unique")
    if len(sequence) > len(map_ids):
        raise HTTPException(status_code=422, detail="sequence has more steps than maps in the pool")
    if not any(token.startswith("pick") or token == "decider" for token in sequence):
        raise HTTPException(status_code=422, detail="sequence must contain at least one pick or a decider")


def select_config(
    configs: list[models.MapVetoConfig],
    *,
    stage_id: int | None,
    round: int | None,
) -> models.MapVetoConfig | None:
    """Pick the most specific applicable config: (stage, round) > (stage, NULL) > (NULL, NULL)."""

    def specificity(config: models.MapVetoConfig) -> int:
        if config.stage_id is not None and config.round is not None:
            return 0
        if config.stage_id is not None:
            return 1
        return 2

    best: models.MapVetoConfig | None = None
    for config in configs:
        if config.stage_id is not None and (stage_id is None or config.stage_id != stage_id):
            continue
        if config.round is not None and config.round != round:
            continue
        if best is None or specificity(config) < specificity(best):
            best = config
    return best


async def resolve_config(session: AsyncSession, encounter: models.Encounter) -> models.MapVetoConfig | None:
    """Cascade-resolve the veto config applicable to this encounter."""
    result = await session.execute(
        select(models.MapVetoConfig)
        .where(
            models.MapVetoConfig.tournament_id == encounter.tournament_id,
            sa.or_(
                models.MapVetoConfig.stage_id.is_(None),
                models.MapVetoConfig.stage_id == encounter.stage_id,
            ),
        )
        .options(selectinload(models.MapVetoConfig.map_pool))
    )
    return select_config(
        list(result.scalars().all()),
        stage_id=encounter.stage_id,
        round=encounter.round,
    )


# ── seed resolution ──────────────────────────────────────────────────────────


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
    """Pure seed decision: bracket slot -> previous-stage standings -> fallback home.

    LOWER seed number = higher seed = acts FIRST. A level resolves only when
    BOTH sides have a distinct value there; a tie keeps the (informational)
    seeds but falls back to home acting first.
    """
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
    """Resolve both teams' seeds for the encounter (snapshot at session init).

    1. ``StageItemInput.slot`` of the encounter's stage item (seed = slot).
    2. ``Standing.position`` of the previous stage (by ``Stage.order`` within
       the tournament; min position when a team has rows in several items).
    3. Fallback: home acts first, ``seed_source=fallback_home``.
    """
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
        current_order = await session.scalar(select(models.Stage.order).where(models.Stage.id == encounter.stage_id))
        previous_stage_id = None
        if current_order is not None:
            previous_stage_id = await session.scalar(
                select(models.Stage.id)
                .where(
                    models.Stage.tournament_id == encounter.tournament_id,
                    models.Stage.order < current_order,
                )
                .order_by(models.Stage.order.desc())
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


# ── sequence token mapping ───────────────────────────────────────────────────


def resolve_sequence_tokens(sequence: list[str], first_side: MapPickSide | str) -> list[str]:
    """Map side-agnostic ``*_first``/``*_second`` tokens onto home/away."""
    first = first_side.value if isinstance(first_side, MapPickSide) else first_side
    second = "away" if first == "home" else "home"
    resolved: list[str] = []
    for token in sequence:
        if token == "decider":
            resolved.append("decider")
            continue
        action, slot = token.split("_", 1)
        resolved.append(f"{action}_{first if slot == 'first' else second}")
    return resolved


# ── session lifecycle ────────────────────────────────────────────────────────


async def get_veto_session(
    session: AsyncSession,
    encounter_id: int,
    *,
    for_update: bool = False,
) -> models.EncounterVetoSession | None:
    query = select(models.EncounterVetoSession).where(models.EncounterVetoSession.encounter_id == encounter_id)
    if for_update:
        query = query.with_for_update()
    result = await session.execute(query)
    return result.scalar_one_or_none()


def unavailable_reason(encounter: models.Encounter) -> str:
    """Why ``ensure_veto_session`` returned None for this encounter."""
    if encounter.home_team_id is None or encounter.away_team_id is None:
        return REASON_TEAMS_UNKNOWN
    return REASON_NOT_CONFIGURED


async def ensure_veto_session(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    commit: bool = True,
) -> models.EncounterVetoSession | None:
    """Idempotently create the encounter's veto session (and pool) if possible.

    Returns the existing session untouched when one exists. No-ops (returns
    None) when either team is unknown or no config cascades onto the
    encounter — ``unavailable_reason`` names which. The config pool is copied
    to ``encounter_map_pool`` ONLY when the encounter has no pool rows yet, so
    a pre-existing admin-assigned pool is respected.
    """
    existing = await get_veto_session(session, encounter.id)
    if existing is not None:
        return existing
    if encounter.home_team_id is None or encounter.away_team_id is None:
        return None
    config = await resolve_config(session, encounter)
    if config is None:
        return None

    seeds = await resolve_seeds(session, encounter)
    now = datetime.now(UTC)
    veto = models.EncounterVetoSession(
        encounter_id=encounter.id,
        config_id=config.id,
        first_side=seeds.first_side,
        seed_source=seeds.seed_source,
        home_seed=seeds.home_seed,
        away_seed=seeds.away_seed,
        resolved_sequence_json=resolve_sequence_tokens(config.veto_sequence_json, seeds.first_side),
        turn_timer_seconds=config.turn_timer_seconds,
        status=MapVetoSessionStatus.ACTIVE,
        started_at=now,
        current_step_started_at=now,
    )
    session.add(veto)

    pool_count = await session.scalar(
        select(sa.func.count())
        .select_from(models.EncounterMapPool)
        .where(models.EncounterMapPool.encounter_id == encounter.id)
    )
    if not pool_count:
        for idx, config_map in enumerate(config.map_pool):
            session.add(
                models.EncounterMapPool(
                    encounter_id=encounter.id,
                    map_id=config_map.map_id,
                    order=idx,
                    status=MapPoolEntryStatus.AVAILABLE,
                )
            )

    register_map_veto_realtime_update(session, encounter.id)
    if commit:
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent reader created the session first — use theirs.
            await session.rollback()
            return await get_veto_session(session, encounter.id)
    else:
        await session.flush()
    return veto


async def reset_veto_session(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    commit: bool = True,
) -> models.EncounterVetoSession | None:
    """Drop the encounter's veto session + pool rows and re-create them.

    Re-resolves config and seeds from scratch; returns the new session (or
    None when it can no longer be created — teams unknown / not configured).
    """
    await session.execute(
        sa.delete(models.EncounterVetoSession).where(models.EncounterVetoSession.encounter_id == encounter.id)
    )
    await session.execute(
        sa.delete(models.EncounterMapPool).where(models.EncounterMapPool.encounter_id == encounter.id)
    )
    await session.flush()
    # Signal even when the re-ensure no-ops: the room just lost its session.
    register_map_veto_realtime_update(session, encounter.id)
    veto = await ensure_veto_session(session, encounter, commit=False)
    if commit:
        await session.commit()
    return veto


async def sync_veto_session_after_team_change(
    session: AsyncSession,
    encounter: models.Encounter,
) -> None:
    """Team-assignment hook (bracket propagation / admin encounter edits).

    Called after an encounter's home/away team ids changed. Both teams now
    set with no session -> ensure one. Session already exists -> the snapshot
    is stale, reset it — UNLESS a pool entry is already ``played`` (the match
    is underway; an admin resets manually). Runs inside the caller's
    transaction (no commit).
    """
    veto = await get_veto_session(session, encounter.id)
    if veto is None:
        if encounter.home_team_id is not None and encounter.away_team_id is not None:
            await ensure_veto_session(session, encounter, commit=False)
        return
    played_count = await session.scalar(
        select(sa.func.count())
        .select_from(models.EncounterMapPool)
        .where(
            models.EncounterMapPool.encounter_id == encounter.id,
            models.EncounterMapPool.status == MapPoolEntryStatus.PLAYED,
        )
    )
    if played_count:
        return
    await reset_veto_session(session, encounter, commit=False)
