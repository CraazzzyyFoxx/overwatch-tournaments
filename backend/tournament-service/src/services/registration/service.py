"""Registration service — database operations."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
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
from shared.domain.roster import FlexRoleMode, flex_role_mode
from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, HeroCatalog, build_hero_entries
from shared.rbac import assign_workspace_system_role
from shared.repository import (
    BalancerRegistrationRepository,
    BalancerRegistrationRoleRepository,
    RegistrationFormRepository,
    SocialAccountRepository,
    TournamentRepository,
    UserRepository,
    get_or_create_workspace_member,
)
from shared.services import social_identity
from shared.services.admission import AdmissionConfig, AdmissionEvaluation
from shared.services.admission.resolve import resolve_admission
from shared.services.subscriptions.wiring import build_resolver
from src import models
from src.core.broker import optional_broker
from src.core.config import settings
from src.core.redis import get_realtime_redis
from src.schemas.registration import (
    RegistrationCreate,
    RegistrationFormUpsert,
    RegistrationListRead,
    RegistrationListResponse,
    RegistrationRead,
)
from src.schemas.registration_build import (
    AdmissionChips,
    _build_tournament_history,
    _public_rosters,
    _reg_to_read,
    _resolve_top_heroes_config,
    _resolve_tournament_workspace,
    registration_read_loaders,
)
from src.services.registration._common import (
    _common_service,
    apply_all_roles,
)
from src.services.registration.validation import validate_registration_input, validation_service
from src.services.registration.windows import is_check_in_window_active, is_registration_open
from src.services.tournament.events import enqueue_registration_approved
from src.services.tournament.realtime_commit import register_tournament_realtime_update

__all__ = (
    "RegistrationService",
    "TeamPlacement",
    "build_registration_roles",
    "registration_service",
)


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
    mode: FlexRoleMode = "optional",
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
    if mode in ("all_roles", "forced"):
        entries = apply_all_roles(entries, force_primary=mode == "forced")
    return entries


# ``RegistrationUpdate`` field -> ORM column for the public self-service PATCH.
#
# Explicit because the previous implementation did ``setattr(registration, key,
# value)`` straight off the payload keys: every key whose name did not happen to
# match a mapped column landed in the instance ``__dict__`` and died with the
# session. ``custom_fields`` (the column is ``custom_fields_json``) and the long
# removed ``primary_role`` were both silently dropped that way.
_SELF_UPDATE_COLUMNS: dict[str, str] = {
    "battle_tag": "battle_tag",
    "discord_nick": "discord_nick",
    "twitch_nick": "twitch_nick",
    "boosty_nick": "boosty_nick",
    "stream_pov": "stream_pov",
    "notes": "notes",
    "custom_fields": "custom_fields_json",
}


@dataclass(frozen=True)
class TeamPlacement:
    """Where a registration sits on a registering team's roster.

    Threaded into :meth:`RegistrationService.submit_public_registration` so the
    captain and invitee flows reuse the one validated self-registration writer
    instead of copying its form/subrole/hero/verified-identity validation.
    ``None`` (the default) is exactly today's solo behaviour.
    """

    registration_team_id: int
    slot_code: str
    is_substitute: bool = False


class RegistrationService:
    """Self-service registration reads and writes, plus the public read models."""

    def __init__(
        self,
        *,
        registration_repo: BalancerRegistrationRepository = BalancerRegistrationRepository(),
        role_repo: BalancerRegistrationRoleRepository = BalancerRegistrationRoleRepository(),
        form_repo: RegistrationFormRepository = RegistrationFormRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        user_repo: UserRepository = UserRepository(),
        social_account_repo: SocialAccountRepository = SocialAccountRepository(),
        validation: Any = validation_service,
    ) -> None:
        self.registration_repo = registration_repo
        self.role_repo = role_repo
        self.form_repo = form_repo
        self.tournament_repo = tournament_repo
        self.user_repo = user_repo
        self.social_account_repo = social_account_repo
        self.validation = validation

    async def get_registration(
        self,
        session: AsyncSession,
        tournament_id: int,
        auth_user_id: int,
    ) -> models.BalancerRegistration | None:
        # Not ``get_active_for_user``: that repository method eager-loads only
        # ``roles``, and this read feeds ``_reg_to_read``, which needs the nested
        # hero catalog plus every loader in ``registration_read_loaders()``.
        result = await session.execute(
            self.registration_repo.select()
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
            # _reg_to_read serializes user_id from workspace_member.player_id and the
            # team brief from registration_team; neither may lazy-load in async code.
            .options(*registration_read_loaders())
        )
        return result.scalar_one_or_none()

    async def _find_user_by_battle_tag(self, session: AsyncSession, battle_tag: str) -> models.User | None:
        user_id = await social_identity.find_player_id_by_handle(
            session, provider=SocialProvider.BATTLENET, username=battle_tag
        )
        if user_id is None:
            return None
        return await self.user_repo.get(session, user_id)

    async def _find_owned_user(self, session: AsyncSession, auth_user_id: int | None) -> models.User | None:
        """The player already linked to this auth account via ``players.user.auth_user_id``."""
        if auth_user_id is None:
            return None
        return await self.user_repo.get_by_auth_user_id(session, auth_user_id)

    async def _move_battle_tag_identity(
        self,
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
                await self.social_account_repo.delete(session, account)
            else:
                account.user_id = target.id
                account.is_primary = False
        await session.flush()
        for provider in (SocialProvider.BATTLENET,):
            # Ordered by creation, not by ``SocialAccountRepository.list_by_user``'s
            # (provider, is_primary desc, id): the oldest account is the one promoted
            # to primary below, and that repository ordering would pick a different row.
            rows = (
                (
                    await session.execute(
                        self.social_account_repo.select()
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

    async def _ensure_user_battle_tag(self, session: AsyncSession, user: models.User, battle_tag: str) -> None:
        if "#" not in battle_tag:
            return
        # Idempotent on (user, battlenet, normalized handle); seeds global visibility.
        await social_identity.upsert_social_account(
            session, user_id=user.id, provider=SocialProvider.BATTLENET, username=battle_tag
        )

    async def _anchor_registration_member(
        self,
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
            workspace_id = await self.tournament_repo.get_workspace_id(session, registration.tournament_id)
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
            collides = await self.registration_repo.exists(
                session,
                filters=[
                    models.BalancerRegistration.tournament_id == registration.tournament_id,
                    models.BalancerRegistration.workspace_member_id == member.id,
                    models.BalancerRegistration.deleted_at.is_(None),
                    models.BalancerRegistration.id != registration.id,
                ],
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
        self,
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
        # Resolve the currently-anchored player, if any.
        #
        # INTENTIONALLY ``session.get`` and not ``WorkspaceMemberRepository.get``:
        # only ``session.get`` is served from the identity map, which is what makes
        # the ``known_handles`` fast path below cost ZERO queries. A repository read
        # issues a SELECT unconditionally and would add one round trip per row to
        # the 5-minute sheet-sync loop. Do not "fix" this.
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
            owned = await self._find_owned_user(session, auth_user_id)
            if owned is None:
                return None
            await self._anchor_registration_member(
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
            user = await self.user_repo.get(session, linked_player_id)

        if user is None:
            owned = await self._find_owned_user(session, auth_user_id)
            if owned is not None:
                user = owned
                shadow = await self._find_user_by_battle_tag(session, battle_tag)
                if shadow is not None and shadow.id != owned.id:
                    await self._move_battle_tag_identity(session, shadow=shadow, target=owned)

        if user is None:
            user = await self._find_user_by_battle_tag(session, battle_tag)

        if user is None:
            user = await self.user_repo.create(session, models.User(name=battle_tag, auth_user_id=auth_user_id))

        for tag in tags:
            if known_handles is not None and "#" in tag:
                key = _handle_key(user.id, tag)
                if key in known_handles:
                    continue
                known_handles.add(key)
            await self._ensure_user_battle_tag(session, user, tag)

        if linked_member is None or linked_member.player_id != user.id:
            await self._anchor_registration_member(
                session,
                registration,
                player_id=user.id,
                workspace_id=workspace_id,
                defer_collision_to_db=defer_member_collision_to_db,
            )
        return user.id

    async def create_registration(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        workspace_id: int,
        auth_user_id: int,
        battle_tag: str | None,
        smurf_tags: list[str] | None,
        discord_nick: str | None,
        twitch_nick: str | None,
        boosty_nick: str | None,
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

        registration = await self.registration_repo.create(
            session,
            models.BalancerRegistration(
                tournament_id=tournament_id,
                display_name=cleaned_battle_tag,
                battle_tag=cleaned_battle_tag,
                battle_tag_normalized=_normalize_battle_tag(cleaned_battle_tag),
                smurf_tags_json=cleaned_smurf_tags or None,
                discord_nick=discord_nick,
                twitch_nick=twitch_nick,
                boosty_nick=boosty_nick,
                stream_pov=stream_pov,
                notes=notes,
                custom_fields_json=custom_fields,
                status="approved" if auto_approve else "pending",
                submitted_at=datetime.now(UTC),
                reviewed_at=datetime.now(UTC) if auto_approve else None,
            ),
        )
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
        player_id = await self.ensure_player_identity(
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
            await assign_workspace_system_role(
                session, user_id=auth_user_id, workspace_id=workspace_id, role_name="player"
            )
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
            register_tournament_realtime_update(session, tournament_id, "registration_changed")
        await session.commit()
        await session.refresh(registration)
        return registration

    async def update_registration(
        self,
        session: AsyncSession,
        registration: models.BalancerRegistration,
        **kwargs: Any,
    ) -> models.BalancerRegistration:
        if registration.status != "pending":
            raise HTTPException(status_code=400, detail="Cannot update a registration that is not pending")
        for key, value in kwargs.items():
            column = _SELF_UPDATE_COLUMNS.get(key)
            if column is None:
                # A schema field with no column mapping is a bug in this module, not
                # a client error — raise instead of dropping the value on the floor.
                raise ValueError(f"update_registration: unmapped payload field {key!r}")
            if value is None:
                continue
            if key == "battle_tag":
                value = _clean_battle_tag(value)
                registration.battle_tag_normalized = _normalize_battle_tag(value)
            elif key == "custom_fields":
                # Merged, not replaced: ``_validate_custom_field`` skips definitions
                # the payload omits when ``partial=True``, i.e. a subset is a legal
                # PATCH body — replacing wholesale would wipe the omitted answers.
                value = {**(registration.custom_fields_json or {}), **value}
            setattr(registration, column, value)
        register_tournament_realtime_update(session, registration.tournament_id, "registration_changed")
        await session.commit()
        await session.refresh(registration)
        return registration

    async def get_registration_count_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> int:
        return await self.registration_repo.count(
            session,
            filters=[
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.status != "withdrawn",
            ],
        )

    async def get_registration_count_by_tournament_bulk(
        self,
        session: AsyncSession,
        tournament_ids: list[int],
    ) -> dict[int, int]:
        if not tournament_ids:
            return {}
        # Analytical: grouped aggregate over many tournaments in one round trip.
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
        self,
        session: AsyncSession,
        registration: models.BalancerRegistration,
    ) -> None:
        # Check-in is the point where the attendee list becomes load-bearing: the
        # balancer and the draft are run against it. Letting a participant drop
        # themselves afterwards silently invalidates a composed roster, so
        # self-withdrawal is final here. Organizers can still withdraw them through
        # the admin path (lifecycle_service.withdraw_registration), which owns that call.
        if registration.checked_in:
            raise HTTPException(status_code=409, detail="Cannot withdraw after check-in")
        registration.status = "withdrawn"
        register_tournament_realtime_update(session, registration.tournament_id, "registration_changed")
        await session.commit()

    async def check_in_registration(
        self,
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
        register_tournament_realtime_update(session, registration.tournament_id, "registration_changed")
        await session.commit()
        await session.refresh(registration)
        return registration

    # ── public self-service use-cases (called by rpc/public_rpc.py) ──────────

    async def submit_public_registration(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
        body: RegistrationCreate,
        team_placement: TeamPlacement | None = None,
        commit: bool = True,
    ) -> RegistrationRead:
        """Full public self-registration use-case.

        Validates form state, subrole/hero catalogs and verified-identity fields,
        rejects duplicates, creates the registration + role rows and returns the
        serialized read model.

        ``team_placement`` binds the new registration to a registering team's roster
        slot. The caller owns the slot decision and must already hold the team's row
        lock — this function only writes what it is told, so that the check and the
        write cannot be separated by a concurrent acceptance.

        ``commit=False`` flushes instead, leaving the transaction boundary to the
        caller — the same split the team-export orchestrator uses. The team flows need
        it because consuming an invite, writing the registration and updating the
        team's denormalized status must land together or not at all. A caller that
        passes it also owns mapping ``IntegrityError`` at its own commit, since that
        now fires outside this function's ``try``.
        """
        form = await _common_service.get_registration_form(session, tournament_id)
        tournament = await self.tournament_repo.get(session, tournament_id)
        # ``form is None`` still gates: a tournament with no registration form has
        # nothing to submit against. Openness itself is now purely the schedule.
        if form is None or tournament is None or not is_registration_open(tournament):
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

        existing = await self.get_registration(session, tournament_id, auth_user.id)
        if existing is not None:
            if existing.status == "withdrawn":
                raise HTTPException(status_code=409, detail="Withdrawn registrations cannot be submitted again")
            raise HTTPException(status_code=409, detail="Already registered for this tournament")

        # Resolve player profile from auth_user (explicit query to avoid lazy load).
        # Only needed for the verified-identity validation below —
        # create_registration/ensure_player_identity re-resolve the owned player
        # from auth_user_id themselves when anchoring the workspace_member.
        user_player_id: int | None = await self.user_repo.get_id_by_auth_user_id(session, auth_user.id)

        # Identity fields flagged ``require_verified`` must match an
        # OAuth-verified social account on the registrant's player profile.
        await self.validation.validate_verified_identity(
            session,
            form=form,
            payload=body,
            player_id=user_player_id,
        )

        role_entries = build_registration_roles(
            body.roles,
            hero_catalog=hero_catalog,
            max_heroes=max_heroes,
            mode=flex_role_mode(form),
        )

        try:
            registration = await self.create_registration(
                session,
                tournament_id=tournament_id,
                workspace_id=workspace_id,
                auth_user_id=auth_user.id,
                battle_tag=body.battle_tag,
                smurf_tags=body.smurf_tags,
                discord_nick=body.discord_nick,
                twitch_nick=body.twitch_nick,
                boosty_nick=body.boosty_nick,
                stream_pov=body.stream_pov,
                notes=body.notes,
                custom_fields=body.custom_fields,
                auto_approve=form.auto_approve,
                auth_user=auth_user,
            )

            if team_placement is not None:
                # Set before the commit that also writes the roles, so a team member's
                # registration can never be visible without its slot: a row with a
                # team_id but no slot_code would be counted by the roster reader and
                # placed nowhere.
                registration.registration_team_id = team_placement.registration_team_id
                registration.team_slot_code = team_placement.slot_code
                registration.is_substitute = team_placement.is_substitute
            # Write normalized roles
            for entry in role_entries:
                entry.registration_id = registration.id
            await self.role_repo.create_many(session, role_entries)
            if commit:
                await session.commit()
            else:
                await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="Already registered for this tournament")

        registration = await self.registration_repo.get(
            session,
            registration.id,
            options=[
                selectinload(models.BalancerRegistration.roles)
                .selectinload(models.BalancerRegistrationRole.hero_entries)
                .selectinload(models.BalancerRegistrationRoleHero.hero),
                *registration_read_loaders(),
            ],
        )
        status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
        rosters = await _public_rosters(session, [registration], show_ranks=form.show_ranks)
        return _reg_to_read(
            registration,
            workspace_id=workspace_id,
            status_meta_map=status_meta_map,
            show_ranks=form.show_ranks,
            roster=rosters.get(registration.id),
        )

    async def resolve_admission_list(
        self,
        session: AsyncSession,
        registrations: Sequence[Any],
        *,
        form: models.BalancerRegistrationForm | None,
    ) -> dict[int, AdmissionEvaluation]:
        """One admission evaluation per registration, for a whole list.

        Shared by the public participants list and the admin registrations table,
        which is the entire point: both surfaces used to ship five raw fields and
        let the client re-derive "is this player admitted" from them, in five
        places, two of which deliberately disagreed. They now render the same
        object.

        The predecessor of this method flattened the profile verdict back to
        ``bool | None`` and threw the reasons away. Nothing here does: the
        evaluation carries every requirement, its reasons and the per-provider
        detail the row chips need, so no consumer has to ask a second time.

        Batched deliberately -- resolving per registration serializes behind
        Discord's per-guild rate-limit bucket and makes a 200-row page unusable --
        and ``resolve_admission`` never forces a provider call. ``stage`` stays at
        its ``check_in`` default: stages are ordered, so the last gate is the only
        one at which every requirement is in force, and a badge that called a
        requirement harmless because its gate is still ahead would tell a player
        they are fine right up until check-in refuses them.
        """
        if not registrations:
            # Before building the resolver or reading the workspace rule: an empty
            # list has nothing to resolve, and ``resolve_admission`` would return
            # ``{}`` after we had already paid for both.
            return {}

        resolver = build_resolver(
            session,
            discord_bot_token=settings.discord_token,
            twitch_client_id=settings.twitch_client_id,
            broker=optional_broker(),
            proxy=settings.proxy_url,
            redis=get_realtime_redis(),
        )
        # Gated on the form flag, not on ``enforces_subscription``: that property is
        # derived FROM the rule we are about to load. A tournament with the toggle
        # off pays nothing, which is the guarantee ``build_subscription_reads``
        # made with the same cheapest-guard-first ordering.
        rule = (
            await resolver.load_requirement(workspace_id=form.workspace_id)
            if form is not None and form.require_subscription and form.workspace_id is not None
            else None
        )
        config = AdmissionConfig.from_form(form, subscription_rule=rule)
        return await resolve_admission(session, registrations, config=config, resolver=resolver)

    async def build_public_registration_list(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
    ) -> RegistrationListResponse:
        """Anonymous participants-list read model.

        The public RPC caches this payload (``registration_list:{id}:``, same
        TTL as other tournament reads). ``registration_changed`` invalidates it;
        TTL still bounds admin writes that only hit the balancer WS topic.
        In-process coalescing on the RPC builder still collapses miss herds.

        ``get_status_metas_map`` is cashews-backed per workspace. That is safe
        because it caches the status *catalog*, not registrations, and all five
        catalog writes invalidate it after commit (see
        ``shared.balancer_registration_statuses``).
        NB: do NOT reintroduce ``cache.disabling(...)`` — it flips a *process-global*
        flag on the shared cashews backend and races with every concurrent request
        on this worker (see lesson_cashews_disabling_shared_cache).
        """
        workspace_id = await _resolve_tournament_workspace(session, tournament_id)

        # Analytical: the whole participants table in one ordered read with every
        # loader the serializer needs.
        result = await session.execute(
            self.registration_repo.select()
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
                # the member is the registration's only identity anchor, and the team
                # brief feeds the participants table's team column.
                *registration_read_loaders(),
            )
            .order_by(models.BalancerRegistration.submitted_at.asc())
        )
        registrations = result.scalars().all()
        status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)

        form = await _common_service.get_registration_form(session, tournament_id)
        admissions = await self.resolve_admission_list(session, registrations, form=form)
        show_ranks = form.show_ranks if form is not None else False
        rosters = await _public_rosters(session, registrations, show_ranks=show_ranks)

        history_map, history_count_map, division_grids = await _build_tournament_history(
            session,
            registrations,
            tournament_id,
            workspace_id,
        )

        registrations_read = []
        for r in registrations:
            chips = AdmissionChips.of(admissions.get(r.id))
            registrations_read.append(
                RegistrationListRead(
                    **_reg_to_read(
                        r,
                        workspace_id=workspace_id,
                        status_meta_map=status_meta_map,
                        show_ranks=show_ranks,
                        admission=chips.admission,
                        profiles_open=chips.profiles_open,
                        subscription_outcome=chips.subscription_outcome,
                        subscription_verdicts=chips.subscription_verdicts,
                        roster=rosters.get(r.id),
                    ).model_dump(),
                    tournament_history=history_map.get(r.id, []),
                    tournament_history_count=history_count_map.get(r.id, 0),
                )
            )
        return RegistrationListResponse(
            registrations=registrations_read,
            division_grids=division_grids,
        )

    async def upsert_registration_form(
        self,
        session: AsyncSession,
        tournament_id: int,
        body: RegistrationFormUpsert,
        *,
        workspace_id: int,
    ) -> models.BalancerRegistrationForm:
        """Create-or-update the tournament's registration form. Commits internally.

        ``workspace_id`` is the tournament's already-resolved workspace (the RPC
        handler resolves it for the permission check anyway).

        ``require_subscription`` is written here because the toggle is the tournament's
        decision; the rule itself belongs to the workspace and is written through
        ``subscription_config.upsert_workspace_requirement``.
        """
        form = await _common_service.get_registration_form(session, tournament_id)
        built_in_fields_json = {key: value.model_dump(exclude_none=True) for key, value in body.built_in_fields.items()}
        custom_fields_json = [field.model_dump(exclude_none=True) for field in body.custom_fields]

        if form is None:
            form = await self.form_repo.create(
                session,
                models.BalancerRegistrationForm(
                    tournament_id=tournament_id,
                    workspace_id=workspace_id,
                    auto_approve=body.auto_approve,
                    require_open_profile=body.require_open_profile,
                    open_profile_scope=body.open_profile_scope,
                    show_ranks=body.show_ranks,
                    require_subscription=body.require_subscription,
                    subscription_stage=body.subscription_stage.value,
                    max_substitutes=body.max_substitutes,
                    built_in_fields_json=built_in_fields_json,
                    custom_fields_json=custom_fields_json,
                ),
            )
        else:
            form.auto_approve = body.auto_approve
            form.require_open_profile = body.require_open_profile
            form.open_profile_scope = body.open_profile_scope
            form.show_ranks = body.show_ranks
            form.require_subscription = body.require_subscription
            form.subscription_stage = body.subscription_stage.value
            form.max_substitutes = body.max_substitutes
            form.built_in_fields_json = built_in_fields_json
            form.custom_fields_json = custom_fields_json

        # Staged BEFORE the commit, like every other write in this service: the
        # realtime rail persists the event row in this transaction's flush and
        # publishes it from after_commit. Until this existed a form edit emitted
        # nothing at all, so open tabs only learned about it by accident, riding
        # along with the next unrelated registration event.
        register_tournament_realtime_update(session, tournament_id, "registration_form_changed")
        await session.commit()
        await session.refresh(form)
        return form


registration_service = RegistrationService()
