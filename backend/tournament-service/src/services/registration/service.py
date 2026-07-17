"""Registration service — database operations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import get_status_metas_map
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider, normalize_social_handle
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES, normalize_sub_role
from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, HeroCatalog, build_hero_entries
from shared.rbac import assign_workspace_system_role
from shared.repository import get_or_create_workspace_member
from shared.services import social_identity
from shared.services.profile_visibility import resolve_profiles_open
from src import models
from src.schemas.registration import (
    RegistrationCreate,
    RegistrationFormUpsert,
    RegistrationListRead,
    RegistrationListResponse,
    RegistrationRead,
)
from src.schemas.registration_build import (
    _build_tournament_history,
    _reg_to_read,
    _resolve_top_heroes_config,
    _resolve_tournament_workspace,
)
from src.services.registration.validation import validate_registration_input, validate_verified_identity
from src.services.registration.windows import is_check_in_window_active, is_registration_open
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
            models.BalancerRegistration.workspace_member.has(
                models.WorkspaceMember.player.has(models.User.auth_user_id == auth_user_id)
            ),
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero)
        )
        .options(selectinload(models.BalancerRegistration.tournament))
        # _reg_to_read serializes user_id from workspace_member.player_id and
        # must never lazy-load it in async code.
        .options(selectinload(models.BalancerRegistration.workspace_member))
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
            (
                await session.execute(
                    sa.select(models.SocialAccount)
                    .where(models.SocialAccount.user_id == target.id, models.SocialAccount.provider == provider)
                    .order_by(models.SocialAccount.created_at, models.SocialAccount.id)
                )
            )
            .scalars()
            .all()
        )
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


async def _anchor_registration_member(
    session: AsyncSession,
    registration: models.BalancerRegistration,
    *,
    player_id: int,
    workspace_id: int | None,
    defer_collision_to_db: bool = False,
) -> None:
    """Point ``registration.workspace_member_id`` at ``player_id``'s member row.

    Resolves the workspace from the registration's tournament when the caller
    didn't pass it (``Tournament.workspace_id`` is NOT NULL, so this is total
    for any persisted registration). The partial unique index
    ``uq_balancer_registration_user (tournament_id, workspace_member_id) WHERE
    deleted_at IS NULL`` allows only one live registration per member per
    tournament, so if another live row already holds that member the anchor is
    skipped with a warning (the player identity — social accounts — is still
    ensured; this mirrors how the admin user-merge skips colliding rows).

    ``defer_collision_to_db=True`` disables that pre-check and lets the unique
    index raise ``IntegrityError`` at flush/commit instead — used by the
    self-service path, where a collision means a concurrent duplicate
    registration and must surface as the historical 409, not a silently
    unanchored row.
    """
    if workspace_id is None:
        workspace_id = await session.scalar(
            sa.select(models.Tournament.workspace_id).where(models.Tournament.id == registration.tournament_id)
        )
    if workspace_id is None:
        logger.warning(
            "ensure_player_identity: could not resolve a workspace for the registration's "
            "tournament; leaving workspace_member_id unset",
            registration_id=getattr(registration, "id", None),
            tournament_id=registration.tournament_id,
            player_id=player_id,
        )
        return

    member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)
    if registration.workspace_member_id == member.id:
        return

    if not defer_collision_to_db and registration.deleted_at is None:
        collides = await session.scalar(
            sa.select(
                sa.exists().where(
                    models.BalancerRegistration.tournament_id == registration.tournament_id,
                    models.BalancerRegistration.workspace_member_id == member.id,
                    models.BalancerRegistration.deleted_at.is_(None),
                    models.BalancerRegistration.id != registration.id,
                )
            )
        )
        if collides:
            logger.warning(
                "ensure_player_identity: another live registration in this tournament is "
                "already anchored on the resolved workspace_member (same player twice, e.g. "
                "a main + smurf row); leaving this registration unanchored",
                registration_id=getattr(registration, "id", None),
                tournament_id=registration.tournament_id,
                workspace_member_id=member.id,
                player_id=player_id,
            )
            return

    registration.workspace_member_id = member.id


async def ensure_player_identity(
    session: AsyncSession,
    registration: models.BalancerRegistration,
    *,
    auth_user_id: int | None = None,
    workspace_id: int | None = None,
    known_handles: set[tuple[int, str]] | None = None,
    defer_member_collision_to_db: bool = False,
) -> int | None:
    """Find-or-create the domain player (players.user) for a registration's tags.

    Anchors the registration on that player's ``workspace_member`` row
    (``registration.workspace_member_id`` — the row's ONLY identity column
    since dbarch02 dropped ``user_id``) and ensures a battlenet
    ``social_account`` for the main tag and each smurf. This is what lets
    first-time registrants — who aren't yet in the analytics system — be
    picked up by rank collection / the open-profile gate. Dedup is by the
    normalized handle (case-insensitive), so a later log/CSV import reconciles
    to the same player. Returns the resolved player id (``players.user.id`` ==
    the member's ``player_id``). Flushes only; caller commits.

    ``auth_user_id`` is the *registering* account's auth identity, passed explicitly
    by self-service callers (``create_registration``); manual/sheet-sync callers have
    no auth identity to offer and leave it ``None``. It is no longer read off the
    registration row — ``BalancerRegistration`` has no ``auth_user_id`` column
    (identity is anchored via ``workspace_member`` instead).

    ``workspace_id`` is the registration's tournament's workspace when the
    caller already has it (``create_registration`` / sheet sync); when ``None``
    it is resolved from ``registration.tournament_id`` with one query.

    ``defer_member_collision_to_db`` controls what happens when another live
    registration in the same tournament already holds the resolved member:
    ``False`` (sheet sync / backfill) skips the anchor with a warning so one
    bad row can't break a whole sync; ``True`` (self-service) sets it anyway
    and lets the unique index raise at commit — see
    ``_anchor_registration_member``.

    Identity precedence (registrant may already have an authenticated account):
    1. An already-anchored registration (``registration.workspace_member_id``
       set, e.g. by a prior save) is respected as-is — the member's
       ``player_id`` is the player.
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

    ``known_handles`` is an optional bulk-prefetched cache of
    ``(player_id, normalized_battlenet_handle)`` pairs used by the sheet-sync
    loop (which calls this once per row every 5 minutes): when the registration
    is already anchored and every tag is already a known handle of that player,
    the call is a no-op with ZERO queries — provided the caller eager-loaded
    ``registration.workspace_member`` so the ``session.get`` below hits the
    identity map. The set is mutated (newly ensured handles are added) so
    repeated tags within one sync are also deduplicated. Semantics for
    ``known_handles=None`` callers are unchanged.
    """
    # Resolve the currently-anchored player, if any. session.get() is served
    # from the identity map when the member was eager-loaded by the caller.
    linked_member: models.WorkspaceMember | None = None
    if registration.workspace_member_id is not None:
        linked_member = await session.get(models.WorkspaceMember, registration.workspace_member_id)
    linked_player_id = linked_member.player_id if linked_member is not None else None

    battle_tag = registration.battle_tag
    if not battle_tag:
        if linked_player_id is not None:
            return linked_player_id
        # No battletag on the form: the only identity we can still anchor is
        # the registering account's own player (preserves the pre-dbarch02
        # behavior where the pre-resolved player id was linked directly).
        owned = await _find_owned_user(session, auth_user_id)
        if owned is None:
            return None
        await _anchor_registration_member(
            session,
            registration,
            player_id=owned.id,
            workspace_id=workspace_id,
            defer_collision_to_db=defer_member_collision_to_db,
        )
        return owned.id

    tags = [battle_tag, *[smurf for smurf in (registration.smurf_tags_json or []) if smurf]]

    def _handle_key(player_id: int, tag: str) -> tuple[int, str]:
        return (player_id, normalize_social_handle(SocialProvider.BATTLENET, tag))

    if linked_player_id is not None and known_handles is not None:
        keys = [_handle_key(linked_player_id, tag) for tag in tags if "#" in tag]
        if all(key in known_handles for key in keys):
            return linked_player_id

    # Respect an already-anchored registration; only reconcile when unset.
    user: models.User | None = None
    if linked_player_id is not None:
        user = await session.get(models.User, linked_player_id)

    if user is None:
        owned = await _find_owned_user(session, auth_user_id)
        if owned is not None:
            user = owned
            shadow = await _find_user_by_battle_tag(session, battle_tag)
            if shadow is not None and shadow.id != owned.id:
                await _move_battle_tag_identity(session, shadow=shadow, target=owned)

    if user is None:
        user = await _find_user_by_battle_tag(session, battle_tag)

    if user is None:
        user = models.User(name=battle_tag, auth_user_id=auth_user_id)
        session.add(user)
        await session.flush()

    for tag in tags:
        if known_handles is not None and "#" in tag:
            key = _handle_key(user.id, tag)
            if key in known_handles:
                continue
            known_handles.add(key)
        await _ensure_user_battle_tag(session, user, tag)

    if linked_member is None or linked_member.player_id != user.id:
        await _anchor_registration_member(
            session,
            registration,
            player_id=user.id,
            workspace_id=workspace_id,
            defer_collision_to_db=defer_member_collision_to_db,
        )
    return user.id


async def create_registration(
    session: AsyncSession,
    *,
    tournament_id: int,
    workspace_id: int,
    auth_user_id: int,
    battle_tag: str | None,
    smurf_tags: list[str] | None,
    discord_nick: str | None,
    twitch_nick: str | None,
    stream_pov: bool,
    notes: str | None,
    custom_fields: dict[str, Any] | None,
    auto_approve: bool = False,
    auth_user: models.AuthUser | None = None,
) -> models.BalancerRegistration:
    """Create a self-service registration and auto-enroll the registrant.

    ``auth_user`` is the gateway-rehydrated identity (carrying the cached RBAC
    deny overlay) for the registering account, used to gate on the
    ``registration.self_register`` capability. It is ``None`` only for
    non-self-service callers (there are none today — sheet/CSV imports and
    admin-created rows go through ``create_manual_registration`` instead,
    which has no auth_user and is intentionally untouched here); when absent,
    the gate and auto-enroll are both skipped since there's no account to
    enroll or deny.
    """
    if auth_user is not None and not auth_user.can_capability(
        "registration", "self_register", workspace_id=workspace_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Registration is not allowed for this user in this workspace",
        )

    cleaned_battle_tag = _clean_battle_tag(battle_tag)
    cleaned_smurf_tags = [_clean_battle_tag(tag) for tag in (smurf_tags or [])]
    cleaned_smurf_tags = [tag for tag in cleaned_smurf_tags if tag]

    registration = models.BalancerRegistration(
        tournament_id=tournament_id,
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
    # event so it carries the resolved player. ensure_player_identity itself
    # anchors registration.workspace_member_id on the resolved player's member
    # row for this workspace (idempotently created via
    # get_or_create_workspace_member) — the row's only identity column since
    # dbarch02 dropped user_id.
    # defer_member_collision_to_db: a member collision on this path means a
    # concurrent duplicate self-registration — let the partial unique index
    # raise IntegrityError at commit (mapped to 409 by
    # submit_public_registration), matching the historical behavior.
    player_id = await ensure_player_identity(
        session,
        registration,
        auth_user_id=auth_user_id,
        workspace_id=workspace_id,
        defer_member_collision_to_db=True,
    )
    if auth_user_id is not None and player_id is not None:
        # Every self-service registration that resolved a domain player grants
        # the baseline "player" RBAC role (the workspace_member enrollment
        # already happened inside ensure_player_identity above). Idempotent,
        # so re-registering (e.g. a second tournament in the same workspace)
        # is a no-op past the first time.
        #
        # assign_workspace_system_role() calls ensure_workspace_system_roles()
        # internally, so we don't seed the catalog explicitly here — doing so
        # would re-upsert the whole permission catalog twice per registration
        # on this hot path for no behavioural gain.
        await assign_workspace_system_role(session, user_id=auth_user_id, workspace_id=workspace_id, role_name="player")
    elif auth_user_id is not None:
        # ensure_player_identity returns None when the registration has no
        # battle_tag (see its docstring) — there's no domain player to anchor
        # a workspace_member on, so auto-enroll is skipped for this
        # registration. Logged (not raised) since a missing battle_tag is a
        # form-config choice, not an error.
        logger.debug(
            "Skipping workspace_member auto-enroll: no player_id resolved (no battle_tag)",
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
        )
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


# ── public self-service use-cases (called by rpc/public_rpc.py) ──────────────


async def submit_public_registration(
    session: AsyncSession,
    *,
    tournament_id: int,
    auth_user: models.AuthUser,
    body: RegistrationCreate,
) -> RegistrationRead:
    """Full public self-registration use-case.

    Validates form state, subrole/hero catalogs and verified-identity fields,
    rejects duplicates, creates the registration + role rows and returns the
    serialized read model. Commits internally.
    """
    form = await get_registration_form(session, tournament_id)
    tournament = await session.get(models.Tournament, tournament_id)
    if form is None or tournament is None or not is_registration_open(tournament, form):
        raise HTTPException(status_code=400, detail="Registration is not open for this tournament")

    workspace_id = form.workspace_id

    subrole_catalog = await resolve_subrole_catalog(session, workspace_id)
    hero_catalog, max_heroes = await _resolve_top_heroes_config(session, form)
    validate_registration_input(
        form,
        body,
        subrole_catalog=subrole_catalog,
        hero_catalog=hero_catalog,
    )

    existing = await get_registration(session, tournament_id, auth_user.id)
    if existing is not None:
        if existing.status == "withdrawn":
            raise HTTPException(status_code=409, detail="Withdrawn registrations cannot be submitted again")
        raise HTTPException(status_code=409, detail="Already registered for this tournament")

    # Resolve player profile from auth_user (explicit query to avoid lazy load).
    # Only needed for the verified-identity validation below —
    # create_registration/ensure_player_identity re-resolve the owned player
    # from auth_user_id themselves when anchoring the workspace_member.
    user_player_id: int | None = await session.scalar(
        sa.select(models.User.id).where(models.User.auth_user_id == auth_user.id)
    )

    # Identity fields flagged ``require_verified`` must match an
    # OAuth-verified social account on the registrant's player profile.
    await validate_verified_identity(
        session,
        form=form,
        payload=body,
        player_id=user_player_id,
    )

    role_entries = build_registration_roles(
        body.roles,
        hero_catalog=hero_catalog,
        max_heroes=max_heroes,
    )

    try:
        registration = await create_registration(
            session,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            auth_user_id=auth_user.id,
            battle_tag=body.battle_tag,
            smurf_tags=body.smurf_tags,
            discord_nick=body.discord_nick,
            twitch_nick=body.twitch_nick,
            stream_pov=body.stream_pov,
            notes=body.notes,
            custom_fields=body.custom_fields,
            auto_approve=form.auto_approve,
            auth_user=auth_user,
        )

        # Write normalized roles
        for entry in role_entries:
            entry.registration_id = registration.id
            session.add(entry)
        await session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Already registered for this tournament")

    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(models.BalancerRegistration.id == registration.id)
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero),
            # _reg_to_read serializes user_id from workspace_member.player_id.
            selectinload(models.BalancerRegistration.workspace_member),
        )
    )
    registration = result.scalar_one()
    status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
    return _reg_to_read(
        registration,
        workspace_id=workspace_id,
        status_meta_map=status_meta_map,
        show_ranks=form.show_ranks,
    )


async def build_public_registration_list(
    session: AsyncSession,
    *,
    tournament_id: int,
) -> RegistrationListResponse:
    """Anonymous participants-list read model.

    The registration list must always reflect live data. Every read below is a
    plain ``session.execute`` (or a helper that itself only runs raw ORM reads:
    get_status_metas_map / get_registration_form / resolve_profiles_open) — none
    of them go through the cashews cache, so no cache bypass is needed here.
    NB: do NOT reintroduce ``cache.disabling(...)`` — it flips a *process-global*
    flag on the shared cashews backend and races with every concurrent request
    on this worker (see lesson_cashews_disabling_shared_cache).
    """
    workspace_id = await _resolve_tournament_workspace(session, tournament_id)

    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            # tournament_id already pins this to a single workspace
            # (BalancerRegistration has no denormalized workspace_id).
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero),
            # Needed by _build_tournament_history and _reg_to_read below —
            # the member is the registration's only identity anchor.
            selectinload(models.BalancerRegistration.workspace_member),
        )
        .order_by(models.BalancerRegistration.submitted_at.asc())
    )
    registrations = result.scalars().all()
    status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)

    form = await get_registration_form(session, tournament_id)
    profiles_open_map: dict[int, bool | None] = (
        await resolve_profiles_open(session, registrations, scope=form.open_profile_scope)
        if form is not None and form.require_open_profile
        else {}
    )
    show_ranks = form.show_ranks if form is not None else False

    history_map, history_count_map, division_grids = await _build_tournament_history(
        session,
        registrations,
        tournament_id,
        workspace_id,
    )

    registrations_read = [
        RegistrationListRead(
            **_reg_to_read(
                r,
                workspace_id=workspace_id,
                status_meta_map=status_meta_map,
                show_ranks=show_ranks,
                # Anonymous endpoint: strip custom fields (may hold PII,
                # admin-only). Notes and smurf tags stay public — see
                # _reg_to_read.
                include_private=False,
                profiles_open=profiles_open_map.get(r.id),
            ).model_dump(),
            tournament_history=history_map.get(r.id, []),
            tournament_history_count=history_count_map.get(r.id, 0),
        )
        for r in registrations
    ]
    return RegistrationListResponse(
        registrations=registrations_read,
        division_grids=division_grids,
    )


async def upsert_registration_form(
    session: AsyncSession,
    tournament_id: int,
    body: RegistrationFormUpsert,
    *,
    workspace_id: int,
) -> models.BalancerRegistrationForm:
    """Create-or-update the tournament's registration form. Commits internally.

    ``workspace_id`` is the tournament's already-resolved workspace (the RPC
    handler resolves it for the permission check anyway).
    """
    form = await get_registration_form(session, tournament_id)
    built_in_fields_json = {key: value.model_dump(exclude_none=True) for key, value in body.built_in_fields.items()}
    custom_fields_json = [field.model_dump(exclude_none=True) for field in body.custom_fields]

    if form is None:
        form = models.BalancerRegistrationForm(
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            is_open=body.is_open,
            auto_approve=body.auto_approve,
            require_open_profile=body.require_open_profile,
            open_profile_scope=body.open_profile_scope,
            show_ranks=body.show_ranks,
            built_in_fields_json=built_in_fields_json,
            custom_fields_json=custom_fields_json,
        )
        session.add(form)
    else:
        form.is_open = body.is_open
        form.auto_approve = body.auto_approve
        form.require_open_profile = body.require_open_profile
        form.open_profile_scope = body.open_profile_scope
        form.show_ranks = body.show_ranks
        form.built_in_fields_json = built_in_fields_json
        form.custom_fields_json = custom_fields_json

    await session.commit()
    await session.refresh(form)
    return form
