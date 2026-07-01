"""Registration service — database operations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from loguru import logger
from shared.core.errors import BaseAPIException as HTTPException
from shared.core import enums
from shared.core.social import SocialProvider
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES, normalize_sub_role
from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, HeroCatalog, build_hero_entries
from shared.services import social_identity
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.services.tournament.events import enqueue_registration_approved
from src.services.tournament.realtime_commit import register_tournament_realtime_update


def _clean_battle_tag(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    text = re.sub(r"\s*#\s*", "#", text)
    return text.replace(" ", "").strip()


def _normalize_battle_tag(value: str | None) -> str | None:
    cleaned = _clean_battle_tag(value)
    if not cleaned:
        return None
    return cleaned.lower()


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


async def get_registration_form(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationForm | None:
    result = await session.execute(
        sa.select(models.BalancerRegistrationForm).where(models.BalancerRegistrationForm.tournament_id == tournament_id)
    )
    return result.scalar_one_or_none()


async def get_registration(
    session: AsyncSession,
    tournament_id: int,
    auth_user_id: int,
) -> models.BalancerRegistration | None:
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.auth_user_id == auth_user_id,
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero)
        )
        .options(selectinload(models.BalancerRegistration.tournament))
    )
    return result.scalar_one_or_none()


def _build_hero_entries(
    slugs: list[str] | None,
    *,
    hero_catalog: HeroCatalog,
    max_heroes: int,
) -> list[models.BalancerRegistrationRoleHero]:
    return build_hero_entries(slugs, hero_catalog=hero_catalog, max_heroes=max_heroes)



def build_registration_roles(
    roles: list[Any] | None,
    *,
    hero_catalog: HeroCatalog | None = None,
    max_heroes: int | None = None,
) -> list[models.BalancerRegistrationRole]:
    """Build normalized role entries, mirroring the admin write path.

    Filters to valid registration role codes (tank/dps/support), de-duplicates,
    normalizes the sub-role slug, and assigns sequential priority. Keeps the
    public and admin/Google-Sheets paths consistent so a sub-role like
    ``main_dps`` is stored identically regardless of entry point.

    When ``hero_catalog`` is provided (the top-heroes field is enabled), the
    ordered ``top_heroes`` slugs on each role are attached as
    ``registration_role_hero`` rows.
    """
    resolved_max = max_heroes if max_heroes and max_heroes > 0 else DEFAULT_MAX_TOP_HEROES
    entries: list[models.BalancerRegistrationRole] = []
    seen: set[str] = set()
    for role in roles or []:
        role_code = getattr(role, "role", None)
        if role_code not in REGISTRATION_ROLE_CODES or role_code in seen:
            continue
        seen.add(role_code)
        entry = models.BalancerRegistrationRole(
            role=role_code,
            subrole=normalize_sub_role(getattr(role, "subrole", None)),
            is_primary=bool(getattr(role, "is_primary", False)),
            priority=len(entries),
        )
        if hero_catalog is not None:
            entry.hero_entries = _build_hero_entries(
                getattr(role, "top_heroes", None),
                hero_catalog=hero_catalog,
                max_heroes=resolved_max,
            )
        entries.append(entry)
    return entries


async def _find_user_by_battle_tag(session: AsyncSession, battle_tag: str) -> models.User | None:
    user_id = await social_identity.find_player_id_by_handle(
        session, provider=SocialProvider.BATTLENET, username=battle_tag
    )
    if user_id is None:
        return None
    return await session.get(models.User, user_id)


async def _find_owned_user(session: AsyncSession, auth_user_id: int | None) -> models.User | None:
    """The player already linked to this auth account via ``players.user.auth_user_id``."""
    if auth_user_id is None:
        return None
    return await session.scalar(sa.select(models.User).where(models.User.auth_user_id == auth_user_id))


async def _move_battle_tag_identity(
    session: AsyncSession,
    *,
    shadow: models.User,
    target: models.User,
) -> None:
    """Move ``shadow``'s battlenet social accounts onto ``target``.

    This is NOT a full user merge (achievements/match stats/registration history
    stay attributed to ``shadow``'s id — see ``ensure_player_identity`` docstring
    for why a full audited merge is out of scope here). It only resolves the
    narrow collision ``ensure_player_identity`` cares about: two distinct
    ``players.user`` rows both claiming the same battletag handle. Moving the
    handle(s) means future lookups (registration, log import, CSV import) all
    converge on ``target`` instead of re-splitting the identity. Idempotent;
    flushes only, caller commits.
    """
    accounts = await social_identity.list_social_accounts(session, shadow.id, providers=[SocialProvider.BATTLENET])
    for account in accounts:
        existing = await social_identity.find_by_handle(
            session, provider=SocialProvider.BATTLENET, username=account.username, user_id=target.id
        )
        if existing is not None:
            # Target already owns this exact handle — drop the shadow's duplicate.
            await session.delete(account)
        else:
            account.user_id = target.id
            account.is_primary = False
    await session.flush()
    for provider in (SocialProvider.BATTLENET,):
        rows = (
            await session.execute(
                sa.select(models.SocialAccount)
                .where(models.SocialAccount.user_id == target.id, models.SocialAccount.provider == provider)
                .order_by(models.SocialAccount.created_at, models.SocialAccount.id)
            )
        ).scalars().all()
        if rows and not any(row.is_primary for row in rows):
            rows[0].is_primary = True
    await session.flush()
    logger.warning(
        "Collapsed colliding shadow player's battletag identity onto account-owned player; "
        "historical stats/achievements remain attributed to the shadow player id and are "
        "NOT reassigned — run the admin user-merge tool to fully consolidate if needed",
        shadow_player_id=shadow.id,
        target_player_id=target.id,
    )


async def _ensure_user_battle_tag(session: AsyncSession, user: models.User, battle_tag: str) -> None:
    if "#" not in battle_tag:
        return
    # Idempotent on (user, battlenet, normalized handle); seeds global visibility.
    await social_identity.upsert_social_account(
        session, user_id=user.id, provider=SocialProvider.BATTLENET, username=battle_tag
    )


async def ensure_player_identity(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> int | None:
    """Find-or-create the domain player (players.user) for a registration's tags.

    Links ``registration.user_id`` and ensures a battlenet ``social_account`` for
    the main tag and each smurf. This is what lets first-time registrants — who
    aren't yet in the analytics system — be picked up by rank collection / the
    open-profile gate. Dedup is by the normalized handle (case-insensitive), so a
    later log/CSV import reconciles to the same player. Flushes only; caller commits.

    Identity precedence (registrant may already have an authenticated account):
    1. An already-linked registration (``registration.user_id`` set, e.g. by a
       prior save) is respected as-is.
    2. Else, if the registering auth account already owns a player
       (``players.user.auth_user_id``), that player is reused — the battletag is
       attached to it rather than find-or-create-by-battletag. If a *different*
       shadow player (no auth link) already owns that exact battletag, its
       battlenet identity is collapsed onto the account-owned player (see
       ``_move_battle_tag_identity``) rather than silently leaving the handle
       split across two player rows. This is an identity-only collapse, not a
       full user merge: non-identity data (stats, achievements, past
       registrations) stays on the shadow player id.
    3. Else, fall back to the historical battletag dedup.
    4. Else, create a new bare player for this battletag (linked to the auth
       account when present).
    """
    battle_tag = registration.battle_tag
    if not battle_tag:
        return registration.user_id

    # Respect an already-linked registration; only reconcile when unset.
    user: models.User | None = None
    if registration.user_id is not None:
        user = await session.get(models.User, registration.user_id)

    registration_auth_user_id = getattr(registration, "auth_user_id", None)

    if user is None:
        owned = await _find_owned_user(session, registration_auth_user_id)
        if owned is not None:
            user = owned
            shadow = await _find_user_by_battle_tag(session, battle_tag)
            if shadow is not None and shadow.id != owned.id:
                await _move_battle_tag_identity(session, shadow=shadow, target=owned)

    if user is None:
        user = await _find_user_by_battle_tag(session, battle_tag)

    if user is None:
        user = models.User(name=battle_tag, auth_user_id=registration_auth_user_id)
        session.add(user)
        await session.flush()

    await _ensure_user_battle_tag(session, user, battle_tag)
    for smurf in registration.smurf_tags_json or []:
        if smurf:
            await _ensure_user_battle_tag(session, user, smurf)

    if registration.user_id != user.id:
        registration.user_id = user.id
    return user.id


async def create_registration(
    session: AsyncSession,
    *,
    tournament_id: int,
    workspace_id: int,
    auth_user_id: int,
    user_id: int | None,
    battle_tag: str | None,
    smurf_tags: list[str] | None,
    discord_nick: str | None,
    twitch_nick: str | None,
    stream_pov: bool,
    notes: str | None,
    custom_fields: dict[str, Any] | None,
    auto_approve: bool = False,
) -> models.BalancerRegistration:
    cleaned_battle_tag = _clean_battle_tag(battle_tag)
    cleaned_smurf_tags = [_clean_battle_tag(tag) for tag in (smurf_tags or [])]
    cleaned_smurf_tags = [tag for tag in cleaned_smurf_tags if tag]

    registration = models.BalancerRegistration(
        tournament_id=tournament_id,
        workspace_id=workspace_id,
        auth_user_id=auth_user_id,
        user_id=user_id,
        display_name=cleaned_battle_tag,
        battle_tag=cleaned_battle_tag,
        battle_tag_normalized=_normalize_battle_tag(cleaned_battle_tag),
        smurf_tags_json=cleaned_smurf_tags or None,
        discord_nick=discord_nick,
        twitch_nick=twitch_nick,
        stream_pov=stream_pov,
        notes=notes,
        custom_fields_json=custom_fields,
        status="approved" if auto_approve else "pending",
        exclude_from_balancer=False,
        submitted_at=datetime.now(UTC),
        reviewed_at=datetime.now(UTC) if auto_approve else None,
    )
    session.add(registration)
    await session.flush()
    # Provision the domain player identity so first-time registrants are picked
    # up by rank collection / the open-profile gate. Done before the approval
    # event so it carries the resolved user_id.
    await ensure_player_identity(session, registration)
    if auto_approve:
        await enqueue_registration_approved(session, registration)
    else:
        register_tournament_realtime_update(session, tournament_id, "structure_changed")
    await session.commit()
    await session.refresh(registration)
    return registration


async def update_registration(
    session: AsyncSession,
    registration: models.BalancerRegistration,
    **kwargs: Any,
) -> models.BalancerRegistration:
    for key, value in kwargs.items():
        if value is not None:
            if key == "battle_tag":
                value = _clean_battle_tag(value)
            elif key == "smurf_tags":
                cleaned_smurf_tags = [_clean_battle_tag(tag) for tag in value]
                value = [tag for tag in cleaned_smurf_tags if tag] or None
            setattr(registration, key, value)
    if "battle_tag" in kwargs and kwargs["battle_tag"] is not None:
        registration.battle_tag_normalized = _normalize_battle_tag(registration.battle_tag)
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")
    await session.commit()
    await session.refresh(registration)
    return registration


async def get_registration_count_by_tournament(
    session: AsyncSession,
    tournament_id: int,
) -> int:
    result = await session.execute(
        sa.select(sa.func.count()).where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.status != "withdrawn",
        )
    )
    return result.scalar_one()


async def get_registration_count_by_tournament_bulk(
    session: AsyncSession,
    tournament_ids: list[int],
) -> dict[int, int]:
    if not tournament_ids:
        return {}
    result = await session.execute(
        sa.select(models.BalancerRegistration.tournament_id, sa.func.count())
        .where(
            models.BalancerRegistration.tournament_id.in_(tournament_ids),
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.status != "withdrawn",
        )
        .group_by(models.BalancerRegistration.tournament_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def withdraw_registration(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> None:
    registration.status = "withdrawn"
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")
    await session.commit()


async def check_in_registration(
    session: AsyncSession,
    registration: models.BalancerRegistration,
    *,
    checked_in_by: int | None,
) -> models.BalancerRegistration:
    if registration.status != "approved":
        raise HTTPException(status_code=409, detail="Registration must be approved before check-in")

    if not is_check_in_window_active(registration.tournament):
        raise HTTPException(status_code=409, detail="Check-in is not active for this tournament")

    registration.checked_in = True
    registration.checked_in_at = datetime.now(UTC)
    registration.checked_in_by = checked_in_by
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")
    await session.commit()
    await session.refresh(registration)
    return registration
