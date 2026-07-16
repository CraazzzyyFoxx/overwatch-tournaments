"""Registration lifecycle CRUD for the admin surface.

Listing, manual creation, profile edits, review transitions
(approve/reject/withdraw/restore), soft delete, balancer inclusion/status and
check-in. Everything here is re-exported by the ``admin`` facade.

Note for tests: functions here resolve collaborators from *this* module's
globals, so patch ``src.services.registration.lifecycle`` (not the ``admin``
facade) to intercept e.g. ``get_registration_by_id`` or
``enqueue_registration_approved``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.services.registration._common import (
    VALID_BALANCER_STATUSES,
    VALID_REGISTRATION_STATUSES,
    _register_registration_changed,
    active_roles_all_ranked,
    ensure_tournament_exists,
    get_registration_form,
    included_balancer_status,
    replace_registration_roles,
    sync_included_balancer_status,
)
from src.services.registration.service import ensure_player_identity
from src.services.registration.utils import (
    normalize_battle_tag,
    normalize_battle_tag_key,
)
from src.services.tournament.events import (
    enqueue_registration_approved,
    enqueue_registration_rejected,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_check_in_window_active(
    tournament: models.Tournament,
    *,
    now: datetime | None = None,
) -> bool:
    if tournament.status != enums.TournamentStatus.CHECK_IN:
        return False

    current_time = _as_utc(now or datetime.now(UTC))
    opens_at = _as_utc(tournament.check_in_opens_at) if tournament.check_in_opens_at is not None else None
    closes_at = _as_utc(tournament.check_in_closes_at) if tournament.check_in_closes_at is not None else None
    return (opens_at is None or opens_at <= current_time) and (closes_at is None or current_time <= closes_at)


async def list_registrations(
    session: AsyncSession,
    tournament_id: int,
    *,
    status_filter: str | None = None,
    inclusion_filter: str | None = None,
    source_filter: str | None = None,
    include_deleted: bool = False,
) -> list[models.BalancerRegistration]:
    query = (
        sa.select(models.BalancerRegistration)
        .where(models.BalancerRegistration.tournament_id == tournament_id)
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero),
            selectinload(models.BalancerRegistration.reviewer),
            selectinload(models.BalancerRegistration.deleted_by_user),
            selectinload(models.BalancerRegistration.checked_in_by_user),
            selectinload(models.BalancerRegistration.google_sheet_binding).selectinload(
                models.BalancerRegistrationGoogleSheetBinding.feed
            ),
            # serialize_registration derives user_id from workspace_member.player_id.
            selectinload(models.BalancerRegistration.workspace_member),
        )
        .order_by(models.BalancerRegistration.submitted_at.desc(), models.BalancerRegistration.id.desc())
    )
    if not include_deleted:
        query = query.where(models.BalancerRegistration.deleted_at.is_(None))
    if status_filter and status_filter != "all":
        query = query.where(models.BalancerRegistration.status == status_filter)
    if inclusion_filter == "included":
        query = query.where(models.BalancerRegistration.exclude_from_balancer.is_(False))
    elif inclusion_filter == "excluded":
        query = query.where(models.BalancerRegistration.exclude_from_balancer.is_(True))
    if source_filter == "google_sheets":
        query = query.where(models.BalancerRegistration.google_sheet_binding.has())
    elif source_filter == "manual":
        query = query.where(~models.BalancerRegistration.google_sheet_binding.has())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_registration_by_id(session: AsyncSession, registration_id: int) -> models.BalancerRegistration:
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(models.BalancerRegistration.id == registration_id)
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero),
            selectinload(models.BalancerRegistration.reviewer),
            selectinload(models.BalancerRegistration.checked_in_by_user),
            selectinload(models.BalancerRegistration.google_sheet_binding),
            selectinload(models.BalancerRegistration.tournament),
            # serialize_registration derives user_id from workspace_member.player_id.
            selectinload(models.BalancerRegistration.workspace_member),
        )
    )
    registration = result.scalar_one_or_none()
    if registration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    return registration


async def ensure_unique_battle_tag(
    session: AsyncSession,
    *,
    tournament_id: int,
    battle_tag: str | None,
    exclude_registration_id: int | None = None,
) -> None:
    normalized = normalize_battle_tag_key(battle_tag)
    if not normalized:
        return
    query = sa.select(models.BalancerRegistration.id).where(
        models.BalancerRegistration.tournament_id == tournament_id,
        models.BalancerRegistration.deleted_at.is_(None),
        models.BalancerRegistration.battle_tag_normalized == normalized,
    )
    if exclude_registration_id is not None:
        query = query.where(models.BalancerRegistration.id != exclude_registration_id)
    existing_id = (await session.execute(query)).scalar_one_or_none()
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Registration with this BattleTag already exists"
        )


async def validate_registration_status_value(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: str,
    value: str,
) -> None:
    builtin_values = VALID_REGISTRATION_STATUSES if scope == "registration" else VALID_BALANCER_STATUSES
    if value in builtin_values:
        return

    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus.id).where(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == value,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {scope} status: {value}",
        )


async def create_manual_registration(
    session: AsyncSession,
    *,
    tournament_id: int,
    display_name: str | None,
    battle_tag: str | None,
    smurf_tags_json: list[str] | None,
    discord_nick: str | None,
    twitch_nick: str | None,
    stream_pov: bool,
    notes: str | None,
    admin_notes: str | None,
    roles: list[dict[str, Any]],
    auth_user_id: int | None = None,
) -> models.BalancerRegistration:
    battle_tag = normalize_battle_tag(battle_tag)
    await ensure_unique_battle_tag(session, tournament_id=tournament_id, battle_tag=battle_tag)

    form = await get_registration_form(session, tournament_id)
    config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
    hero_catalog = None
    max_heroes = None
    if config and config.get("enabled", True) is not False:
        from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, resolve_hero_catalog

        hero_catalog = await resolve_hero_catalog(session)
        raw_max = config.get("max_heroes")
        max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

    # Manual (admin-created) registrations have no registering auth account, so
    # they are intentionally left with workspace_member_id=None — mirrors the
    # sheet-sync creation path below. BalancerRegistration has no workspace_id
    # column (derived from tournament_id -> Tournament.workspace_id when needed),
    # so this function takes no workspace_id param either.
    registration = models.BalancerRegistration(
        tournament_id=tournament_id,
        display_name=display_name or battle_tag,
        battle_tag=battle_tag,
        battle_tag_normalized=normalize_battle_tag_key(battle_tag),
        smurf_tags_json=smurf_tags_json or None,
        discord_nick=discord_nick,
        twitch_nick=twitch_nick,
        stream_pov=stream_pov,
        notes=notes,
        admin_notes=admin_notes,
        status="approved",
        exclude_from_balancer=False,
        submitted_at=datetime.now(UTC),
        balancer_profile_overridden_at=datetime.now(UTC),
    )
    replace_registration_roles(registration, roles, hero_catalog=hero_catalog, max_heroes=max_heroes)
    session.add(registration)
    await session.flush()
    # Optionally anchor on a chosen site account: find-or-create that account's
    # player and set workspace_member_id (identity + battletag collapse handled
    # by ensure_player_identity). Without it, manual rows stay unlinked as before.
    if auth_user_id is not None:
        await ensure_player_identity(session, registration, auth_user_id=auth_user_id)
    await enqueue_registration_approved(session, registration)
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def update_registration_profile(
    session: AsyncSession,
    registration_id: int,
    *,
    display_name: str | None,
    battle_tag: str | None,
    smurf_tags_json: list[str] | None,
    discord_nick: str | None,
    twitch_nick: str | None,
    stream_pov: bool | None,
    notes: str | None,
    admin_notes: str | None,
    status_value: str | None,
    balancer_status_value: str | None,
    roles: list[dict[str, Any]] | None,
    auth_user_id: int | None = None,
    exclude_from_balancer: bool | None = None,
    exclude_reason: str | None = None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    previous_status = registration.status
    if battle_tag is not None:
        normalized_battle_tag = normalize_battle_tag(battle_tag)
        await ensure_unique_battle_tag(
            session,
            tournament_id=registration.tournament_id,
            battle_tag=normalized_battle_tag,
            exclude_registration_id=registration.id,
        )
        registration.battle_tag = normalized_battle_tag
        registration.battle_tag_normalized = normalize_battle_tag_key(normalized_battle_tag)
    if display_name is not None:
        registration.display_name = display_name or registration.battle_tag
    if smurf_tags_json is not None:
        registration.smurf_tags_json = smurf_tags_json or None
    if discord_nick is not None:
        registration.discord_nick = discord_nick
    if twitch_nick is not None:
        registration.twitch_nick = twitch_nick
    if stream_pov is not None:
        registration.stream_pov = stream_pov
    if notes is not None:
        registration.notes = notes
    if status_value is not None:
        await validate_registration_status_value(
            session,
            workspace_id=registration.tournament.workspace_id,
            scope="registration",
            value=status_value,
        )
        registration.status = status_value
    if balancer_status_value is not None:
        await validate_registration_status_value(
            session,
            workspace_id=registration.tournament.workspace_id,
            scope="balancer",
            value=balancer_status_value,
        )
        registration.balancer_status = balancer_status_value
        if balancer_status_value == "not_in_balancer":
            registration.exclude_from_balancer = True

    override_changed = False
    if status_value is not None or balancer_status_value is not None:
        override_changed = True
    if admin_notes is not None:
        registration.admin_notes = admin_notes
        override_changed = True
    if roles is not None:
        for r_obj in registration.roles:
            r_obj.hero_entries.clear()
        await session.flush()

        form = await get_registration_form(session, registration.tournament_id)
        config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
        hero_catalog = None
        max_heroes = None
        if config and config.get("enabled", True) is not False:
            from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, resolve_hero_catalog

            hero_catalog = await resolve_hero_catalog(session)
            raw_max = config.get("max_heroes")
            max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

        replace_registration_roles(registration, roles, hero_catalog=hero_catalog, max_heroes=max_heroes)
        sync_included_balancer_status(registration)
        override_changed = True
    # Mirror set_registration_exclusion exactly. Applied last so an explicit
    # exclusion flag wins over the balancer_status/role-sync side effects
    # above; like the dedicated endpoint it does not bump
    # balancer_profile_overridden_at. exclude_reason only applies together
    # with exclude_from_balancer.
    if exclude_from_balancer is not None:
        registration.exclude_from_balancer = exclude_from_balancer
        if exclude_from_balancer:
            registration.balancer_status = "not_in_balancer"
            registration.exclude_reason = exclude_reason
        else:
            registration.exclude_reason = None
            registration.balancer_status = (
                included_balancer_status(registration) if registration.status == "approved" else "not_in_balancer"
            )
    if override_changed:
        registration.balancer_profile_overridden_at = datetime.now(UTC)

    # (Re)anchor on a chosen site account when provided. Uses the possibly-just-
    # updated battle_tag; ensure_player_identity flushes only (commit below).
    if auth_user_id is not None:
        await ensure_player_identity(session, registration, auth_user_id=auth_user_id)

    if status_value == "approved" and previous_status != "approved":
        await enqueue_registration_approved(session, registration)
    elif status_value == "rejected" and previous_status != "rejected":
        await enqueue_registration_rejected(session, registration)
    else:
        _register_registration_changed(session, registration)

    await session.commit()
    # Refetch only when relationships changed: new hero_entries need their
    # .hero loaded for serialization and auth_user_id may swap the
    # workspace_member. Scalar-only updates keep the eagerly-loaded object
    # valid after commit (expire_on_commit=False).
    if roles is not None or auth_user_id is not None:
        return await get_registration_by_id(session, registration.id)
    return registration


async def approve_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    reviewed_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "approved"
    registration.reviewed_at = datetime.now(UTC)
    registration.reviewed_by = reviewed_by
    # Keep exclude_from_balancer for backward compat but do NOT
    # auto-add to balancer.  Admin must explicitly set balancer_status.
    registration.exclude_from_balancer = False
    registration.exclude_reason = None
    await enqueue_registration_approved(session, registration)
    await session.commit()
    # Refetch: reviewed_by changed, the serializer needs a loaded .reviewer.
    return await get_registration_by_id(session, registration.id)


async def reject_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    reviewed_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "rejected"
    registration.reviewed_at = datetime.now(UTC)
    registration.reviewed_by = reviewed_by
    await enqueue_registration_rejected(session, registration)
    await session.commit()
    # Refetch: reviewed_by changed, the serializer needs a loaded .reviewer.
    return await get_registration_by_id(session, registration.id)


async def bulk_approve_registrations(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int],
    *,
    reviewed_by: int | None,
) -> tuple[int, int]:
    result = await session.execute(
        sa.select(models.BalancerRegistration).where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.id.in_(registration_ids),
            models.BalancerRegistration.status == "pending",
        )
    )
    registrations = list(result.scalars().all())
    now = datetime.now(UTC)
    for registration in registrations:
        registration.status = "approved"
        registration.reviewed_at = now
        registration.reviewed_by = reviewed_by
        registration.exclude_from_balancer = False
        registration.exclude_reason = None
        await enqueue_registration_approved(session, registration)
    await session.commit()
    return len(registrations), len(registration_ids) - len(registrations)


async def set_registration_exclusion(
    session: AsyncSession,
    registration_id: int,
    *,
    exclude_from_balancer: bool,
    exclude_reason: str | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.exclude_from_balancer = exclude_from_balancer
    if exclude_from_balancer:
        registration.balancer_status = "not_in_balancer"
        registration.exclude_reason = exclude_reason
    else:
        registration.exclude_reason = None
        registration.balancer_status = (
            included_balancer_status(registration) if registration.status == "approved" else "not_in_balancer"
        )
    _register_registration_changed(session, registration)
    await session.commit()
    # Scalar-only mutation; the eagerly-loaded object stays valid after
    # commit (expire_on_commit=False), so no refetch is needed.
    return registration


async def withdraw_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "withdrawn"
    _register_registration_changed(session, registration)
    await session.commit()
    # Scalar-only mutation; no refetch needed (expire_on_commit=False).
    return registration


async def restore_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "approved"
    _register_registration_changed(session, registration)
    await session.commit()
    # Scalar-only mutation; no refetch needed (expire_on_commit=False).
    return registration


async def soft_delete_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    deleted_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.deleted_at = datetime.now(UTC)
    registration.deleted_by = deleted_by
    _register_registration_changed(session, registration)
    await session.commit()
    return registration


async def set_balancer_status(
    session: AsyncSession,
    registration_id: int,
    *,
    balancer_status: str,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    await validate_registration_status_value(
        session,
        workspace_id=registration.tournament.workspace_id,
        scope="balancer",
        value=balancer_status,
    )
    if balancer_status != "not_in_balancer" and registration.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration must be approved before adding to balancer",
        )
    if balancer_status == "ready" and not active_roles_all_ranked(registration):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration must have at least one active role with rank before it can be ready",
        )
    registration.balancer_status = balancer_status
    if balancer_status == "not_in_balancer":
        registration.exclude_from_balancer = True
    _register_registration_changed(session, registration)
    await session.commit()
    # Scalar-only mutation; no refetch needed (expire_on_commit=False).
    return registration


async def check_in_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    checked_in_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    if not is_check_in_window_active(registration.tournament):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Check-in is not active for this tournament",
        )
    registration.checked_in = True
    registration.checked_in_at = datetime.now(UTC)
    registration.checked_in_by = checked_in_by
    _register_registration_changed(session, registration)
    await session.commit()
    # Refetch: checked_in_by changed, the serializer needs a loaded
    # .checked_in_by_user.
    return await get_registration_by_id(session, registration.id)


async def uncheck_in_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.checked_in = False
    registration.checked_in_at = None
    registration.checked_in_by = None
    # Also clear the loaded relationship so the serializer does not report a
    # stale username: assigning the FK column alone leaves .checked_in_by_user
    # populated (and we skip the refetch — expire_on_commit=False keeps the
    # object valid after commit).
    registration.checked_in_by_user = None
    _register_registration_changed(session, registration)
    await session.commit()
    return registration


async def bulk_add_to_balancer(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int],
    *,
    balancer_status: str = "ready",
) -> tuple[int, int]:
    if balancer_status not in VALID_BALANCER_STATUSES:
        tournament = await ensure_tournament_exists(session, tournament_id)
        await validate_registration_status_value(
            session,
            workspace_id=tournament.workspace_id,
            scope="balancer",
            value=balancer_status,
        )
    result = await session.execute(
        sa.select(models.BalancerRegistration).where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.id.in_(registration_ids),
            models.BalancerRegistration.status == "approved",
        )
    )
    registrations = list(result.scalars().all())
    for registration in registrations:
        registration.balancer_status = (
            included_balancer_status(registration) if balancer_status == "ready" else balancer_status
        )
        registration.exclude_from_balancer = balancer_status == "not_in_balancer"
        registration.exclude_reason = None
        _register_registration_changed(session, registration)
    await session.commit()
    return len(registrations), len(registration_ids) - len(registrations)


async def bulk_set_exclusion(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int],
    *,
    exclude_from_balancer: bool,
    exclude_reason: str | None,
) -> tuple[int, int]:
    """Apply set_registration_exclusion semantics to many registrations at once.

    Returns ``(updated, skipped)`` where skipped counts ids that are missing,
    soft-deleted or belong to another tournament.
    """
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.id.in_(registration_ids),
        )
        # included_balancer_status inspects .roles — eager-load them since a
        # lazy load is not available on an async session.
        .options(selectinload(models.BalancerRegistration.roles))
    )
    registrations = list(result.scalars().all())
    for registration in registrations:
        # Same semantics as set_registration_exclusion.
        registration.exclude_from_balancer = exclude_from_balancer
        if exclude_from_balancer:
            registration.balancer_status = "not_in_balancer"
            registration.exclude_reason = exclude_reason
        else:
            registration.exclude_reason = None
            registration.balancer_status = (
                included_balancer_status(registration) if registration.status == "approved" else "not_in_balancer"
            )
        _register_registration_changed(session, registration)
    await session.commit()
    return len(registrations), len(registration_ids) - len(registrations)
