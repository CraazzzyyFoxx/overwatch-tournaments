"""Public registration endpoints for tournament sign-up."""

from __future__ import annotations

import sqlalchemy as sa
from cashews import Command, cache
from fastapi import APIRouter, Depends, HTTPException
from shared.balancer_registration_statuses import build_unknown_status_meta, get_status_metas_map
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.hero_catalog import HeroCatalog, resolve_hero_catalog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.core.workspace import get_division_grid_version
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.registration import (
    RegistrationCreate,
    RegistrationFormRead,
    RegistrationListRead,
    RegistrationRead,
    RegistrationRoleRead,
    RegistrationStatusResponse,
    RegistrationUpdate,
    TournamentHistoryEntry,
)
from src.services.registration import service as reg_service
from src.services.registration.validation import validate_registration_input

router = APIRouter(
    prefix="/tournaments/{tournament_id}/registration",
    tags=["registration"],
)


async def _resolve_tournament_workspace(session: AsyncSession, tournament_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return workspace_id


async def _resolve_top_heroes_config(
    session: AsyncSession,
    form: models.BalancerRegistrationForm,
) -> tuple[HeroCatalog | None, int | None]:
    """Resolve ``(hero_catalog, max_heroes)`` when the top-heroes field is enabled.

    Returns ``(None, None)`` when the field is absent or disabled, so heroes are
    neither validated nor persisted for that tournament.
    """
    config = (form.built_in_fields_json or {}).get("top_heroes")
    if not config or config.get("enabled", True) is False:
        return None, None
    raw_max = config.get("max_heroes")
    max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else None
    hero_catalog = await resolve_hero_catalog(session)
    return hero_catalog, max_heroes


def _form_to_read(
    form: models.BalancerRegistrationForm,
    *,
    subrole_catalog: dict[str, list[dict[str, str]]] | None = None,
) -> RegistrationFormRead:
    return RegistrationFormRead(
        id=form.id,
        tournament_id=form.tournament_id,
        workspace_id=form.workspace_id,
        is_open=form.is_open,
        auto_approve=form.auto_approve,
        opens_at=form.opens_at,
        closes_at=form.closes_at,
        built_in_fields=form.built_in_fields_json or {},
        custom_fields=form.custom_fields_json or [],
        subrole_catalog=subrole_catalog or {},
    )


def _reg_to_read(
    reg: models.BalancerRegistration,
    *,
    status_meta_map: dict[str, dict[str, dict[str, object]]] | None = None,
) -> RegistrationRead:
    roles = (
        [
            RegistrationRoleRead(
                role=r.role,
                subrole=r.subrole,
                is_primary=r.is_primary,
                priority=r.priority,
                top_heroes=[he.hero.slug for he in sorted(r.hero_entries, key=lambda he: he.priority)],
            )
            for r in sorted(reg.roles, key=lambda r: (not r.is_primary, r.priority))
        ]
        if reg.roles
        else []
    )

    return RegistrationRead(
        id=reg.id,
        tournament_id=reg.tournament_id,
        workspace_id=reg.workspace_id,
        auth_user_id=reg.auth_user_id,
        user_id=reg.user_id,
        battle_tag=reg.battle_tag,
        smurf_tags_json=reg.smurf_tags_json,
        discord_nick=reg.discord_nick,
        twitch_nick=reg.twitch_nick,
        stream_pov=reg.stream_pov,
        roles=roles,
        notes=reg.notes,
        custom_fields_json=reg.custom_fields_json,
        status=reg.status,
        status_meta=(status_meta_map["registration"].get(reg.status) if status_meta_map is not None else None)
        or build_unknown_status_meta("registration", reg.status),
        checked_in=reg.checked_in,
        submitted_at=reg.submitted_at,
        reviewed_at=reg.reviewed_at,
    )


@router.get("/form", response_model=RegistrationFormRead | None)
async def get_registration_form(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    """Get the registration form config for a tournament (public)."""
    form = await reg_service.get_registration_form(session, tournament_id)
    if form is None:
        return None
    subrole_catalog = await resolve_subrole_catalog(session, form.workspace_id)
    return _form_to_read(form, subrole_catalog=subrole_catalog)


@router.post("", response_model=RegistrationRead, status_code=201)
async def register(
    tournament_id: int,
    data: RegistrationCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Register the current user for a tournament."""
    form = await reg_service.get_registration_form(session, tournament_id)
    if form is None or not form.is_open:
        raise HTTPException(status_code=400, detail="Registration is not open for this tournament")

    workspace_id = form.workspace_id

    subrole_catalog = await resolve_subrole_catalog(session, workspace_id)
    hero_catalog, max_heroes = await _resolve_top_heroes_config(session, form)
    validate_registration_input(
        form,
        data,
        subrole_catalog=subrole_catalog,
        hero_catalog=hero_catalog,
    )

    existing = await reg_service.get_registration(session, tournament_id, user.id)
    if existing is not None:
        if existing.status == "withdrawn":
            raise HTTPException(status_code=409, detail="Withdrawn registrations cannot be submitted again")
        raise HTTPException(status_code=409, detail="Already registered for this tournament")

    # Resolve player profile from auth_user (explicit query to avoid lazy load)
    user_player_id: int | None = None
    link_result = await session.execute(
        sa.select(models.AuthUserPlayer).where(
            models.AuthUserPlayer.auth_user_id == user.id,
            models.AuthUserPlayer.is_primary.is_(True),
        )
    )
    primary_link = link_result.scalar_one_or_none()
    if primary_link is not None:
        user_player_id = primary_link.player_id

    # Build role entries for normalized table (normalized + filtered to match
    # the admin / Google-Sheets write path). Attaches top-hero rows when enabled.
    role_entries = reg_service.build_registration_roles(
        data.roles,
        hero_catalog=hero_catalog,
        max_heroes=max_heroes,
    )

    try:
        registration = await reg_service.create_registration(
            session,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            auth_user_id=user.id,
            user_id=user_player_id,
            battle_tag=data.battle_tag,
            smurf_tags=data.smurf_tags,
            discord_nick=data.discord_nick,
            twitch_nick=data.twitch_nick,
            stream_pov=data.stream_pov,
            notes=data.notes,
            custom_fields=data.custom_fields,
            auto_approve=form.auto_approve,
        )

        # Write normalized roles
        for entry in role_entries:
            entry.registration_id = registration.id
            session.add(entry)
        await session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Already registered for this tournament")

    # Re-fetch with roles eagerly loaded
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(models.BalancerRegistration.id == registration.id)
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero)
        )
    )
    registration = result.scalar_one()
    status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
    return _reg_to_read(registration, status_meta_map=status_meta_map)


@router.get("/me", response_model=RegistrationRead | None)
async def get_my_registration(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Get the current user's registration for a tournament."""
    reg = await reg_service.get_registration(session, tournament_id, user.id)
    if reg is None:
        return None
    status_meta_map = await get_status_metas_map(session, workspace_id=reg.workspace_id)
    return _reg_to_read(reg, status_meta_map=status_meta_map)


@router.patch("/me", response_model=RegistrationRead)
async def update_my_registration(
    tournament_id: int,
    data: RegistrationUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Update the current user's registration (only while status is pending)."""
    form = await reg_service.get_registration_form(session, tournament_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Registration form not found")

    reg = await reg_service.get_registration(session, tournament_id, user.id)
    if reg is None:
        raise HTTPException(status_code=404, detail="No registration found")
    if reg.status != "pending":
        raise HTTPException(status_code=400, detail="Cannot update a registration that is not pending")

    validate_registration_input(form, data, partial=True)

    updated = await reg_service.update_registration(
        session,
        reg,
        **data.model_dump(exclude_unset=True),
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=form.workspace_id)
    return _reg_to_read(updated, status_meta_map=status_meta_map)


@router.delete("/me", response_model=RegistrationStatusResponse)
async def withdraw_my_registration(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Withdraw the current user's registration."""
    reg = await reg_service.get_registration(session, tournament_id, user.id)
    if reg is None:
        raise HTTPException(status_code=404, detail="No registration found")

    await reg_service.withdraw_registration(session, reg)
    return RegistrationStatusResponse(status="withdrawn", message="Registration withdrawn")


@router.post("/me/check-in", response_model=RegistrationRead)
async def check_in_my_registration(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Check in the current user's approved registration during the check-in window."""
    reg = await reg_service.get_registration(session, tournament_id, user.id)
    if reg is None:
        raise HTTPException(status_code=404, detail="No registration found")

    checked_in = await reg_service.check_in_registration(
        session,
        reg,
        checked_in_by=user.id,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=reg.workspace_id)
    return _reg_to_read(checked_in, status_meta_map=status_meta_map)


@router.get("/list", response_model=list[RegistrationListRead])
async def list_registrations(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    """Public list of registrations for a tournament (all statuses, non-deleted)."""
    from sqlalchemy.orm import selectinload

    workspace_id = await _resolve_tournament_workspace(session, tournament_id)

    with cache.disabling(Command.GET, Command.SET):
        result = await session.execute(
            sa.select(models.BalancerRegistration)
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.workspace_id == workspace_id,
                models.BalancerRegistration.deleted_at.is_(None),
            )
            .options(
                selectinload(models.BalancerRegistration.roles)
                .selectinload(models.BalancerRegistrationRole.hero_entries)
                .selectinload(models.BalancerRegistrationRoleHero.hero)
            )
            .order_by(models.BalancerRegistration.submitted_at.asc())
        )
        registrations = result.scalars().all()
        status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)

        # Build tournament history for each participant
        history_map = await _build_tournament_history(
            session,
            registrations,
            tournament_id,
            workspace_id,
        )

        return [
            RegistrationListRead(
                **_reg_to_read(r, status_meta_map=status_meta_map).model_dump(),
                balancer_status=r.balancer_status,
                balancer_status_meta=status_meta_map["balancer"].get(r.balancer_status)
                or build_unknown_status_meta("balancer", r.balancer_status),
                tournament_history=history_map.get(r.id, []),
            )
            for r in registrations
        ]


async def _build_tournament_history(
    session: AsyncSession,
    registrations: list[models.BalancerRegistration],
    current_tournament_id: int,
    workspace_id: int,
) -> dict[int, list[TournamentHistoryEntry]]:
    """Batch-query past tournament participation from the analytics system.

    Uses tournament.player (the analytics table) — if a player record exists,
    they definitely participated. No extra checks needed.

    Resolution order to find player user_id (players.user.id):
    1. user_id on the registration itself
    2. auth_user_id → AuthUserPlayer → player_id

    Returns a mapping of registration_id -> list of history entries.
    """
    # --- Step 1: resolve analytics user_id for every registration ---
    auth_ids_to_resolve: list[int] = []
    for r in registrations:
        if r.user_id is None and r.auth_user_id is not None:
            auth_ids_to_resolve.append(r.auth_user_id)

    auth_to_player: dict[int, int] = {}
    if auth_ids_to_resolve:
        link_result = await session.execute(
            sa.select(
                models.AuthUserPlayer.auth_user_id,
                models.AuthUserPlayer.player_id,
            ).where(
                models.AuthUserPlayer.auth_user_id.in_(auth_ids_to_resolve),
                models.AuthUserPlayer.is_primary.is_(True),
            )
        )
        for auth_id, player_id in link_result:
            auth_to_player[auth_id] = player_id

    # Build reverse map: analytics_user_id -> list of registration ids
    player_to_reg_ids: dict[int, list[int]] = {}
    for r in registrations:
        uid = r.user_id
        if uid is None and r.auth_user_id is not None:
            uid = auth_to_player.get(r.auth_user_id)
        if uid is not None:
            player_to_reg_ids.setdefault(uid, []).append(r.id)

    player_ids = list(player_to_reg_ids.keys())
    if not player_ids:
        return {}

    # --- Step 2: query tournament.player for participation history ---
    result = await session.execute(
        sa.select(models.Player)
        .join(
            models.Tournament,
            models.Player.tournament_id == models.Tournament.id,
        )
        .where(
            models.Player.user_id.in_(player_ids),
            models.Player.tournament_id != current_tournament_id,
            models.Tournament.workspace_id == workspace_id,
        )
        .add_columns(
            models.Tournament.name.label("tournament_name"),
        )
    )

    history_map: dict[int, list[TournamentHistoryEntry]] = {}
    grid_cache: dict[int, tuple[DivisionGrid, DivisionGridVersionRead | None]] = {}

    for row in result:
        player: models.Player = row[0]
        tournament_name: str = row[1]
        role_str = player.role.value if player.role else None
        division = None
        division_grid_version = None
        if player.rank is not None:
            if player.tournament_id not in grid_cache:
                version = await get_division_grid_version(
                    session,
                    workspace_id,
                    tournament_id=player.tournament_id,
                )
                grid_cache[player.tournament_id] = (
                    load_runtime_grid(version),
                    DivisionGridVersionRead.model_validate(version, from_attributes=True)
                    if version is not None
                    else None,
                )
            grid, division_grid_version = grid_cache[player.tournament_id]
            division = grid.resolve_division_number(player.rank)

        entry = TournamentHistoryEntry(
            tournament_id=player.tournament_id,
            tournament_name=tournament_name,
            role=role_str,
            division=division,
            division_grid_version=division_grid_version,
        )
        for reg_id in player_to_reg_ids.get(player.user_id, []):
            history_map.setdefault(reg_id, []).append(entry)

    # Deduplicate: a player can have multiple Player records per tournament
    # (e.g. substitution). Keep unique by tournament_id.
    for reg_id, entries in history_map.items():
        seen: dict[int, TournamentHistoryEntry] = {}
        for e in entries:
            if e.tournament_id not in seen:
                seen[e.tournament_id] = e
        history_map[reg_id] = list(seen.values())

    return history_map
