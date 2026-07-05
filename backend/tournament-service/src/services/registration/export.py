"""Registration exports: balancer payload and domain-user provisioning.

Two export surfaces live here: the legacy "xv-1" balancer payload of active
registrations, and ``export_registrations_to_users`` which provisions domain
players + social identities from approved registrations. Everything here is
re-exported by the ``admin`` facade.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from shared.core.social import SocialProvider, normalize_social_handle
from shared.services import social_identity
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.services.registration._common import BATTLE_TAG_RE
from src.services.registration.lifecycle import list_registrations
from src.services.registration.utils import UNKNOWN_PRIORITY_SENTINEL

logger = logging.getLogger(__name__)


def registration_source(registration: models.BalancerRegistration) -> str:
    return "google_sheets" if registration.google_sheet_binding is not None else "manual"


def serialize_registration_for_export(registration: models.BalancerRegistration, export_uuid: str) -> dict[str, Any]:
    role_entries = sorted(registration.roles, key=lambda role: role.priority)
    role_map = {role.role: role for role in role_entries}
    is_full_flex = registration.is_flex_computed

    def build_class(role_code: str) -> dict[str, Any]:
        role = role_map.get(role_code)
        return {
            "isActive": bool(role and role.is_active and role.rank_value is not None),
            "rank": int(role.rank_value) if role and role.rank_value is not None else 0,
            "priority": 0 if is_full_flex else int(role.priority) if role else UNKNOWN_PRIORITY_SENTINEL,
            "subtype": role.subrole if role else None,
        }

    return {
        "uuid": export_uuid,
        "identity": {
            "name": registration.battle_tag or registration.display_name or f"registration-{registration.id}",
            "isFullFlex": is_full_flex,
        },
        "stats": {
            "classes": {
                "tank": build_class("tank"),
                "dps": build_class("dps"),
                "support": build_class("support"),
            }
        },
    }


async def list_active_registrations_for_balancer(
    session: AsyncSession,
    tournament_id: int,
) -> list[models.BalancerRegistration]:
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.status == "approved",
            models.BalancerRegistration.exclude_from_balancer.is_(False),
            # Mirror the panel's "in balancer" rule (load_pool): a registration is
            # part of the pool only once it has been added (balancer_status set).
            models.BalancerRegistration.balancer_status != "not_in_balancer",
        )
        .options(selectinload(models.BalancerRegistration.roles))
        .order_by(models.BalancerRegistration.battle_tag_normalized.asc().nullslast())
    )
    return list(result.scalars().all())


async def export_active_registrations(
    session: AsyncSession,
    tournament_id: int,
) -> dict[str, Any]:
    registrations = await list_active_registrations_for_balancer(session, tournament_id)
    payload_players: dict[str, Any] = {}
    for registration in registrations:
        export_uuid = str(uuid4())
        payload_players[export_uuid] = serialize_registration_for_export(registration, export_uuid)
    return {"format": "xv-1", "players": payload_players}


async def _find_user_by_battle_tag(session: AsyncSession, battle_tag: str) -> models.User | None:
    user_id = await social_identity.find_player_id_by_handle(
        session, provider=SocialProvider.BATTLENET, username=battle_tag
    )
    if user_id is None:
        return None
    return await session.get(models.User, user_id)


async def _ensure_user_battle_tag(session: AsyncSession, user: models.User, battle_tag: str) -> None:
    if "#" not in battle_tag:
        return
    await social_identity.upsert_social_account(
        session, user_id=user.id, provider=SocialProvider.BATTLENET, username=battle_tag
    )


def _registration_identity_handles(registration: models.BalancerRegistration) -> list[tuple[str, str]]:
    """(provider, raw_handle) pairs this registration would upsert on export."""
    handles: list[tuple[str, str]] = []
    if registration.battle_tag:
        handles.append((SocialProvider.BATTLENET, registration.battle_tag))
        for smurf in registration.smurf_tags_json or []:
            if BATTLE_TAG_RE.match(smurf):
                handles.append((SocialProvider.BATTLENET, smurf))
    if registration.discord_nick:
        handles.append((SocialProvider.DISCORD, registration.discord_nick))
    if registration.twitch_nick:
        handles.append((SocialProvider.TWITCH, registration.twitch_nick))
    return handles


async def _upsert_user_from_registration(
    session: AsyncSession,
    registration: models.BalancerRegistration,
    *,
    battle_tag: str,
    owner_by_handle: dict[tuple[str, str], int] | None = None,
    known_handles: set[tuple[int, str, str]] | None = None,
) -> None:
    """Provision the domain player + social identities for one registration.

    ``owner_by_handle`` ((provider, normalized) → user_id) and ``known_handles``
    ((user_id, provider, normalized)) are optional bulk prefetches from
    ``export_registrations_to_users`` — with them, an already-exported
    registration costs zero queries instead of 3-6. Both caches are mutated as
    users/handles are created so later registrations in the same export see
    them.
    """
    main_key = (SocialProvider.BATTLENET, normalize_social_handle(SocialProvider.BATTLENET, battle_tag))

    user: models.User | None = None
    if owner_by_handle is not None:
        owner_id = owner_by_handle.get(main_key)
        if owner_id is not None:
            user = await session.get(models.User, owner_id)
    else:
        user = await _find_user_by_battle_tag(session, battle_tag)
    if user is None:
        user = models.User(name=battle_tag)
        session.add(user)
        await session.flush()
        if owner_by_handle is not None:
            owner_by_handle[main_key] = user.id

    for provider, handle in _registration_identity_handles(registration):
        if known_handles is not None:
            key = (user.id, provider, normalize_social_handle(provider, handle))
            if key in known_handles:
                continue
            known_handles.add(key)
        await social_identity.upsert_social_account(
            session, user_id=user.id, provider=provider, username=handle
        )


async def export_registrations_to_users(
    session: AsyncSession,
    tournament_id: int,
) -> dict[str, int]:
    registrations = await list_registrations(session, tournament_id, include_deleted=False, status_filter="approved")

    # Bulk prefetch of every social identity this export could touch — one
    # query instead of 3-6 sequential lookups per registration (a 200-player
    # export used to issue 600-1200 round trips inside a single RPC call).
    wanted: set[str] = set()
    for registration in registrations:
        for provider, handle in _registration_identity_handles(registration):
            wanted.add(normalize_social_handle(provider, handle))

    owner_by_handle: dict[tuple[str, str], int] = {}
    known_handles: set[tuple[int, str, str]] = set()
    if wanted:
        rows = await session.execute(
            sa.select(
                models.SocialAccount.user_id,
                models.SocialAccount.provider,
                models.SocialAccount.username_normalized,
            )
            .where(models.SocialAccount.username_normalized.in_(wanted))
            .order_by(models.SocialAccount.id.asc())
        )
        for user_id, provider, normalized in rows.all():
            known_handles.add((user_id, provider, normalized))
            owner_by_handle.setdefault((provider, normalized), user_id)

    processed = 0
    skipped = 0
    for registration in registrations:
        battle_tag = registration.battle_tag
        if not battle_tag:
            skipped += 1
            continue
        try:
            await _upsert_user_from_registration(
                session,
                registration,
                battle_tag=battle_tag,
                owner_by_handle=owner_by_handle,
                known_handles=known_handles,
            )
        except Exception:
            logger.exception("Failed to build user payload for registration %s", battle_tag)
            skipped += 1
            continue

        processed += 1

    await session.commit()
    return {"processed": processed, "skipped": skipped, "total": len(registrations)}
