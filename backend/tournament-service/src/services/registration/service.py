"""Registration service — database operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import GAME_PROVIDERS, normalize_social_handle
from shared.disciplines import identity_provider as discipline_identity_provider
from shared.domain.forms import (
    ErrorCode,
    FieldError,
    FormSchema,
    identity_key,
    identity_provider,
    raise_field_errors,
    schema_from_form,
)
from shared.hero_catalog import HeroCatalog
from shared.rbac import assign_workspace_system_role
from shared.registration_statuses import get_status_metas_map
from shared.repository import (
    CatalogRoleRepository,
    RegistrationRepository,
    SocialAccountRepository,
    TournamentRepository,
    UserRepository,
    get_or_create_workspace_member,
)
from shared.services.realtime import Resource, Scope, emit
from shared.services.social_identity import social_identity_service
from src.core.clients import subscription_resolver
from src.schemas.registration import (
    RegistrationListRead,
    RegistrationListResponse,
    RegistrationRead,
    RegistrationSubmit,
)
from src.schemas.registration_build import (
    AdmissionChips,
    QueuePlace,
    _build_tournament_history,
    _public_rosters,
    _reg_to_read,
    _resolve_top_heroes_config,
    registration_public_keys,
    registration_read_loaders,
)
from src.schemas.registration_form import RegistrationFormRead
from src.services.admission import AdmissionConfig, AdmissionEvaluation
from src.services.admission.resolve import resolve_admission
from src.services.registration._common import (
    _common_service,
)
from src.services.registration.answers import answer_service
from src.services.registration.self_edit import self_edit_policy, submitted_late
from src.services.registration.serializers import serialize_registration_form
from src.services.registration.subscription_config import subscription_config_service
from src.services.registration.windows import (
    is_check_in_window_active,
    is_registration_open,
    windows_service,
)
from src.services.tournament.events import enqueue_registration_approved

__all__ = (
    "RegistrationService",
    "TeamPlacement",
    "registration_service",
)


#: The body of a team-flow acceptance may be absent (an invitee who already
#: registered has nothing left to answer); a NEW invitee has no such excuse.
_ANSWERS_REQUIRED = "This tournament's registration form has to be answered."

_FORM_VERSION_STALE = "The registration form changed; reload and try again."

_LOCKED_ANSWER = "This answer cannot be changed after submitting; ask an organizer."

_GAME_IDENTITY_CONFLICT = "This game handle already belongs to another player; ask an organizer to merge them."


def _require_current_schema(
    form: models.RegistrationForm,
    submitted_version_id: int | None,
) -> FormSchema:
    """The form's CURRENT schema, refusing a submission aimed at another version.

    The server never validates against the version the client happened to hold:
    a stale ``form_version_id`` is ``409 form_version_stale``, which
    is the client's cue to reload the questions rather than have its answers
    judged by rules the registrant never saw. A form with no version at all
    cannot be answered and lands in the same branch.
    """
    schema = schema_from_form(form)
    if schema is None or submitted_version_id != form.current_version_id:
        raise_field_errors(
            [FieldError("form_version_id", ErrorCode.FORM_VERSION_STALE.value, _FORM_VERSION_STALE)],
            status_code=409,
        )
    return schema


@dataclass(frozen=True)
class TeamPlacement:
    """Where a registration sits on a registering team's roster.

    Threaded into :meth:`RegistrationService.write_public_registration` so the
    captain and invitee flows reuse the one validated self-registration writer
    instead of copying its form/subrole/hero/verified-identity validation.
    ``None`` (the default) is a solo registration.
    """

    registration_team_id: int
    slot_code: str
    is_substitute: bool = False


def _role_counts(registrations: Sequence[models.Registration]) -> dict[str, int]:
    """Primary role -> number of registrations declaring it. One bucket per row.

    The primary role, or the highest-priority one when nothing is flagged primary.
    ``_primary_role_select`` is the SQL form of this rule; the two must agree.
    """
    counts: dict[str, int] = {}
    for registration in registrations:
        roles = sorted(registration.roles or [], key=lambda role: (not role.is_primary, role.priority))
        if not roles:
            continue
        counts[roles[0].role] = counts.get(roles[0].role, 0) + 1
    return counts


def _in_field(registrations: Iterable[models.Registration]) -> list[models.Registration]:
    """The rows the public aggregate counts: every live registration but a withdrawn one.

    Same rule as ``get_registration_count_by_tournament``, so the list's ``total``
    and ``Tournament.registrations_count`` agree. Only the aggregate is filtered:
    the visible list still ships withdrawn rows for its Withdrawn filter.
    """
    return [registration for registration in registrations if registration.status != "withdrawn"]


def _primary_role_select(tournament_id: int) -> sa.Subquery:
    """``(registration_id, role)`` — one row per live registration, its primary role.

    The SQL form of the rule ``_role_counts`` applies in Python: the role flagged
    primary, or the highest-priority one when none is. ``DISTINCT ON`` rather
    than a window function because the answer is one row, not a ranking.
    """
    return (
        sa.select(
            models.RegistrationRole.registration_id.label("registration_id"),
            models.RegistrationRole.role.label("role"),
        )
        .join(
            models.Registration,
            models.Registration.id == models.RegistrationRole.registration_id,
        )
        .where(
            models.Registration.tournament_id == tournament_id,
            models.Registration.deleted_at.is_(None),
        )
        .distinct(models.RegistrationRole.registration_id)
        .order_by(
            models.RegistrationRole.registration_id,
            models.RegistrationRole.is_primary.desc(),
            models.RegistrationRole.priority.asc(),
        )
        .subquery()
    )


def _owned_by(auth_user_id: int) -> sa.ColumnElement[bool]:
    """Is this registration owned by that account?

    ``workspace_member`` carries no ``auth_user_id`` — identity runs through
    ``player_id``, so the chain is member -> player -> auth user. Spelled once so
    the self-service and team flows cannot drift from each other.
    """
    return models.Registration.workspace_member.has(
        models.WorkspaceMember.player.has(models.User.auth_user_id == auth_user_id)
    )


class RegistrationService:
    """Self-service registration reads and writes, plus the public read models."""

    def __init__(
        self,
        *,
        registration_repo: RegistrationRepository = RegistrationRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        user_repo: UserRepository = UserRepository(),
        social_account_repo: SocialAccountRepository = SocialAccountRepository(),
    ) -> None:
        self.registration_repo = registration_repo
        self.tournament_repo = tournament_repo
        self.user_repo = user_repo
        self.social_account_repo = social_account_repo

    async def _registration_changed(
        self,
        session: AsyncSession,
        registration: models.Registration,
    ) -> None:
        await emit(
            session,
            scope=Scope.tournament(registration.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
            # A row created in this same transaction has no id until it flushes;
            # entity_ids is optional precision, so no id just means no narrowing.
            entity_ids={"registration_ids": [registration.id]} if registration.id is not None else None,
        )

    async def get_registration(
        self,
        session: AsyncSession,
        tournament_id: int,
        auth_user_id: int,
    ) -> models.Registration | None:
        # Feeds ``_reg_to_read``: ``registration_read_loaders()`` carries the nested
        # hero catalog, the tournament, the member's player and the team brief, none
        # of which may lazy-load in async code.
        result = await session.execute(
            self.registration_repo.select()
            .where(
                models.Registration.tournament_id == tournament_id,
                _owned_by(auth_user_id),
                models.Registration.deleted_at.is_(None),
            )
            .options(*registration_read_loaders())
        )
        return result.scalar_one_or_none()

    async def _find_user_by_handles(
        self,
        session: AsyncSession,
        *,
        provider: str,
        handles: Sequence[str],
        exclude_player_id: int | None = None,
    ) -> tuple[models.User, str] | None:
        """The first player (other than ``exclude_player_id``) owning one of ``handles``
        (all ``provider``'s), with the handle it matched on."""
        for handle in handles:
            holders = await self.social_account_repo.find_players_by_handle(
                session, provider=provider, username_normalized=normalize_social_handle(provider, handle)
            )
            holder = next((user for user in holders if user.id != exclude_player_id), None)
            if holder is not None:
                return holder, handle
        return None

    async def _find_owned_user(self, session: AsyncSession, auth_user_id: int | None) -> models.User | None:
        """The player already linked to this auth account via ``players.user.auth_user_id``."""
        if auth_user_id is None:
            return None
        return await self.user_repo.get_by_auth_user_id(session, auth_user_id)

    async def _move_game_identity(
        self,
        session: AsyncSession,
        *,
        provider: str,
        shadow: models.User,
        target: models.User,
        handle: str,
    ) -> None:
        """Collapse ``shadow``'s duplicate of ``handle`` into the auth-owned ``target`` — or refuse.

        A submitted handle is not authority to take another player's accounts. The
        collapse is allowed only with ownership proof: the shadow has no auth
        account, and ``target`` already holds this very handle as a VERIFIED,
        provider-subject-backed account (OAuth proved it is theirs). Then only the
        shadow's unverified duplicate of that one handle is dropped. Anything else
        raises ``409 game_identity_conflict`` before any write: auth linkage,
        verified flags, provider subjects, stats and the shadow's other accounts
        never move — the admin user-merge is the path for those.

        A target that holds the handle only as a self-declared (unverified) account proves
        nothing against another player's account, so it is refused the same way.
        Flushes only; caller commits.
        """
        proof = await social_identity_service.find_by_handle(
            session, provider=provider, username=handle, user_id=target.id
        )
        duplicate = await social_identity_service.find_by_handle(
            session, provider=provider, username=handle, user_id=shadow.id
        )
        if (
            shadow.auth_user_id is not None
            or proof is None
            or not proof.is_verified
            or proof.provider_user_id is None
            or duplicate is None
            or duplicate.is_verified
        ):
            raise ApiHTTPException(
                409,
                [ApiExc(msg=_GAME_IDENTITY_CONFLICT, code="game_identity_conflict", field=identity_key(provider))],
            )
        await social_identity_service.delete(session, account_id=duplicate.id, user_id=shadow.id)
        await session.flush()
        logger.warning(
            "Dropped a colliding shadow player's duplicate of an OAuth-verified game handle; "
            "historical stats/achievements remain attributed to the shadow player id and are "
            "NOT reassigned — run the admin user-merge tool to fully consolidate if needed",
            provider=provider,
            shadow_player_id=shadow.id,
            target_player_id=target.id,
        )

    async def _anchor_registration_member(
        self,
        session: AsyncSession,
        registration: models.Registration,
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
        ensured).

        ``defer_collision_to_db=True`` disables that pre-check and lets the unique
        index raise ``IntegrityError`` at flush/commit instead — used by the
        self-service path, where a collision means a concurrent duplicate
        registration and must surface as a 409, not a silently unanchored row.
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
                    models.Registration.tournament_id == registration.tournament_id,
                    models.Registration.workspace_member_id == member.id,
                    models.Registration.deleted_at.is_(None),
                    models.Registration.id != registration.id,
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
        registration: models.Registration,
        *,
        provider: str,
        auth_user_id: int | None = None,
        workspace_id: int | None = None,
        known_handles: set[tuple[int, str, str]] | None = None,
        defer_member_collision_to_db: bool = False,
    ) -> int | None:
        """Find-or-create the domain player (players.user) for a registration's identities.

        ``provider`` is the OWNING tournament's identity provider
        (``identity_provider(tournament.discipline)``): the one game whose handle
        says which player this is. Another game's handle on the same registration
        never finds, creates or names a player.

        Anchors the registration on that player's ``workspace_member`` row
        (``registration.workspace_member_id`` — the row's ONLY identity column)
        and upserts a ``social_account`` for
        every handle the registration carries: the owner provider's primary and
        extras, and every other provider's handle unless ANOTHER player already
        owns that normalized handle (skipped with a warning, never moved). This
        is what lets first-time registrants — who aren't yet in the analytics
        system — be picked up by rank collection / the open-profile gate, and what
        keeps the player's profile showing the socials they just typed into the
        form. Dedup is by the normalized handle (case-insensitive), so a later
        log/CSV import reconciles to the same player. A handle that LEAVES a
        registration is never removed from the profile. Returns the resolved
        player id (``players.user.id`` == the member's ``player_id``). Flushes
        only; caller commits.

        A registration with no owner-provider handle and no authenticated account
        resolves to no player at all.

        ``registration.identities`` must be eager-loaded (or freshly written in
        this session) — it is read directly here, as everywhere else in async code.

        ``auth_user_id`` is the *registering* account's auth identity, passed explicitly
        by self-service callers (``create_registration``); manual/sheet-sync callers have
        no auth identity to offer and leave it ``None``. ``Registration``
        has no ``auth_user_id`` column, so it cannot be read off the row.

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
           (``players.user.auth_user_id``), that player is reused — the owner
           handle is attached to it rather than find-or-create-by-handle. If a
           *different* shadow player (no auth link) already owns that handle, it
           collapses onto the account-owned player ONLY with ownership proof (see
           ``_move_game_identity``); otherwise ``409 game_identity_conflict`` and
           nothing is written.
        3. Else, the first player owning any owner-provider handle of this
           registration (primary first, then the extras).
        4. Else, create a new bare player named after the primary owner handle
           (linked to the auth account when present; a taken name is suffixed,
           ``UserRepository.create_player``).

        ``known_handles`` is an optional bulk-prefetched cache of
        ``(player_id, provider, normalized_handle)`` triples used by the sheet-sync
        loop (which calls this once per row every 5 minutes): when the registration
        is already anchored and every handle is already known for that player,
        the call is a no-op with ZERO queries — provided the caller eager-loaded
        ``registration.workspace_member`` so the ``session.get`` below hits the
        identity map. The set is mutated (newly ensured handles are added) so
        repeated handles within one sync are also deduplicated.
        """
        # INTENTIONALLY ``session.get`` and not ``WorkspaceMemberRepository.get``:
        # only ``session.get`` is served from the identity map, which is what makes
        # the ``known_handles`` fast path below cost ZERO queries. A repository read
        # issues a SELECT unconditionally and would add one round trip per row to
        # the 5-minute sheet-sync loop.
        linked_member: models.WorkspaceMember | None = None
        if registration.workspace_member_id is not None:
            linked_member = await session.get(models.WorkspaceMember, registration.workspace_member_id)
        linked_player_id = linked_member.player_id if linked_member is not None else None

        # Owner handles primary first; every other handle keeps the relationship order.
        rows = [row for row in registration.identities if row.handle]
        owner_handles = [row.handle for row in sorted(rows, key=lambda row: row.position) if row.provider == provider]
        handles = [(provider, handle) for handle in owner_handles] + [
            (row.provider, row.handle) for row in rows if row.provider != provider
        ]

        if not owner_handles:
            if linked_player_id is not None:
                player_id = linked_player_id
            else:
                # No owner-provider identity on the form: the only player we can still
                # anchor is the registering account's own.
                owned = await self._find_owned_user(session, auth_user_id)
                if owned is None:
                    return None
                player_id = owned.id
                await self._anchor_registration_member(
                    session,
                    registration,
                    player_id=player_id,
                    workspace_id=workspace_id,
                    defer_collision_to_db=defer_member_collision_to_db,
                )
            await self._ensure_social_accounts(session, player_id, handles, known_handles=known_handles)
            return player_id

        if linked_player_id is not None and known_handles is not None:
            keys = [
                (linked_player_id, row_provider, normalize_social_handle(row_provider, handle))
                for row_provider, handle in handles
            ]
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
                found = await self._find_user_by_handles(
                    session, provider=provider, handles=owner_handles, exclude_player_id=owned.id
                )
                if found is not None:
                    shadow, matched_handle = found
                    await self._move_game_identity(
                        session, provider=provider, shadow=shadow, target=owned, handle=matched_handle
                    )

        if user is None:
            found = await self._find_user_by_handles(session, provider=provider, handles=owner_handles)
            user = found[0] if found is not None else None

        if user is None:
            user = await self.user_repo.create_player(
                session,
                name=owner_handles[0],
                auth_user_id=auth_user_id,
                identity=(provider, normalize_social_handle(provider, owner_handles[0])),
            )

        await self._ensure_social_accounts(session, user.id, handles, known_handles=known_handles)

        if linked_member is None or linked_member.player_id != user.id:
            await self._anchor_registration_member(
                session,
                registration,
                player_id=user.id,
                workspace_id=workspace_id,
                defer_collision_to_db=defer_member_collision_to_db,
            )
        return user.id

    async def _ensure_social_accounts(
        self,
        session: AsyncSession,
        player_id: int,
        handles: Sequence[tuple[str, str]],
        *,
        known_handles: set[tuple[int, str, str]] | None = None,
    ) -> None:
        """Upsert every registration handle onto the player's profile.

        Idempotent on (player, provider, normalized handle); seeds global
        visibility, so a handle the registrant typed into the form shows up on
        their profile without a second "export" step. A handle another player
        already owns (and this one does not) is skipped, never moved: a form
        naming two different people must not pool them onto one profile.
        """
        for provider, handle in handles:
            normalized = normalize_social_handle(provider, handle)
            if known_handles is not None:
                key = (player_id, provider, normalized)
                if key in known_handles:
                    continue
                known_handles.add(key)
            owners = await self.social_account_repo.find_players_by_handle(
                session, provider=provider, username_normalized=normalized
            )
            if owners and player_id not in {owner.id for owner in owners}:
                logger.warning(
                    "Registration handle is owned by another player; not attaching it to the resolved player",
                    provider=provider,
                    player_id=player_id,
                    owner_player_ids=sorted(owner.id for owner in owners),
                )
                continue
            await social_identity_service.upsert(session, user_id=player_id, provider=provider, username=handle)

    async def create_registration(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        workspace_id: int,
        auth_user_id: int,
        values: Mapping[str, Any],
        schema: FormSchema,
        hero_catalog: HeroCatalog | None = None,
        form_version_id: int | None = None,
        auto_approve: bool = False,
        auth_user: models.AuthUser | None = None,
        commit: bool = True,
        tournament: models.Tournament | None = None,
    ) -> models.Registration:
        """Create a self-service registration and auto-enroll the registrant.

        ``values`` is an already-validated answer document (see
        :meth:`RegistrationAnswerService.validate`); every column, identity row
        and role row it produces is written by the answer service, so this method
        owns only what an answer cannot say: the gate, the review state and the
        enrolment.

        ``auth_user`` is the gateway-rehydrated identity (carrying the cached RBAC
        deny overlay) for the registering account, used to gate on the
        ``registration.self_register`` capability. When it is ``None`` the gate
        and auto-enroll are both skipped: there is no account to enroll or deny.

        ``commit=False`` flushes instead, so a caller that must land this row
        together with something else (the team flows) really can.

        ``tournament`` saves the re-read when the caller already holds the row.

        The registrant's ``reserve`` answer is theirs alone: it is an
        availability note ("I play, and I am fine being called in if somebody
        drops or I cannot start on time"), never a verdict this method imposes.
        """
        if auth_user is not None and not auth_user.can_capability(
            "registration", "self_register", workspace_id=workspace_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Registration is not allowed for this user in this workspace",
            )

        registration = models.Registration(
            tournament_id=tournament_id,
            form_version_id=form_version_id,
            status="approved" if auto_approve else "pending",
            submitted_at=datetime.now(UTC),
            reviewed_at=datetime.now(UTC) if auto_approve else None,
            identities=[],
        )
        # Before the INSERT: the answers carry the game handle the row is named
        # after, and ``ensure_player_identity`` below resolves the domain player
        # from it.
        await self.ensure_unique_primary_game_handles(session, tournament_id=tournament_id, values=values)
        tournament = tournament or await self.tournament_repo.get(session, tournament_id)
        catalog_roles = await CatalogRoleRepository().rated_rows(
            session, discipline=tournament.discipline, workspace_id=workspace_id
        )
        answer_service.apply(
            registration, values, schema=schema, hero_catalog=hero_catalog, catalog_roles=catalog_roles
        )
        provider = discipline_identity_provider(tournament.discipline)
        primary_identity = registration.primary_game_identity(provider=provider)
        registration.display_name = primary_identity.handle if primary_identity is not None else None
        registration = await self.registration_repo.create(session, registration)
        # Provisioned before the approval event so the event carries the player;
        # first-time registrants become visible to rank collection and the
        # open-profile gate. ensure_player_identity also anchors
        # registration.workspace_member_id on that player's member row.
        # defer_member_collision_to_db: a member collision here is a concurrent
        # duplicate self-registration, so the partial unique index raises
        # IntegrityError at commit (mapped to 409 by submit_public_registration).
        player_id = await self.ensure_player_identity(
            session,
            registration,
            provider=provider,
            auth_user_id=auth_user_id,
            workspace_id=workspace_id,
            defer_member_collision_to_db=True,
        )
        if auth_user_id is not None and player_id is not None:
            # Grant the baseline "player" RBAC role (enrollment already happened
            # inside ensure_player_identity); idempotent across tournaments of one
            # workspace. No explicit ensure_workspace_system_roles(): the assign call
            # seeds only when the workspace lacks the role, so this hot path never
            # touches the permission catalog.
            await assign_workspace_system_role(
                session, user_id=auth_user_id, workspace_id=workspace_id, role_name="player"
            )
        elif auth_user_id is not None:
            # No game identity and no account-owned player: nothing to anchor a
            # workspace_member on. Logged, not raised: a form without a game
            # identity question is a config choice, not an error.
            logger.debug(
                "Skipping workspace_member auto-enroll: no player_id resolved (no game identity)",
                tournament_id=tournament_id,
                workspace_id=workspace_id,
                auth_user_id=auth_user_id,
            )
        if auto_approve:
            await enqueue_registration_approved(session, registration)
        else:
            await emit(
                session,
                scope=Scope.tournament(tournament_id),
                invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
            )
        if commit:
            await session.commit()
            await session.refresh(registration)
        else:
            await session.flush()
        return registration

    async def _reload_for_read(
        self,
        session: AsyncSession,
        registration: models.Registration,
    ) -> models.Registration:
        """Re-read a just-written row with every loader its read model needs.

        NOT ``session.refresh``: refresh re-runs the strategy each relationship
        was loaded under but NOT the chain nested beneath it, so ``roles`` would
        come back with ``hero_entries`` unloaded and the roster engine's walk of
        it would raise ``MissingGreenlet``. ``populate_existing`` also re-resolves
        the ``form_version`` an edit just moved, which a stale relationship would
        keep pointing at the version the row answered before.
        """
        await session.get(
            models.Registration,
            registration.id,
            options=list(registration_read_loaders()),
            populate_existing=True,
        )
        return registration

    async def update_registration(
        self,
        session: AsyncSession,
        registration: models.Registration,
        *,
        tournament: models.Tournament,
        values: Mapping[str, Any],
        schema: FormSchema,
        hero_catalog: HeroCatalog | None = None,
        form_version_id: int | None = None,
    ) -> models.Registration:
        """Apply a validated PARTIAL answer document to an existing registration.

        The REGISTRANT's own edit, so it is gated by ``self_edit_policy``: the
        form schema says which questions may be rewritten (closed by default),
        and three keys are floored regardless. An organizer's edit goes through
        ``lifecycle.update_registration_profile`` and is gated by none of it.

        Only the questions the document mentions move; the registration's
        ``form_version_id`` advances to the version it was validated against, so
        the stale badge and the read-side public-key set follow the edit.
        """
        policy = self_edit_policy(registration, tournament, schema)
        if not policy.can_edit:
            raise HTTPException(status_code=409, detail=policy.reason)
        # Reported per key, not as one refusal: the message belongs under the
        # control the registrant just touched. An answer equal to the stored one
        # touches nothing -- a client sending back the document it read edits
        # only what it changed.
        stored = answer_service.answers_of(registration)
        locked = sorted(key for key in set(values) - policy.writable_keys if values[key] != stored.get(key))
        if locked:
            raise_field_errors(
                [FieldError(key, ErrorCode.LOCKED.value, _LOCKED_ANSWER) for key in locked],
                status_code=409,
            )
        await self.ensure_unique_primary_game_handles(
            session, tournament_id=registration.tournament_id, values=values, exclude_registration_id=registration.id
        )
        catalog_roles = await CatalogRoleRepository().rated_rows(
            session, discipline=tournament.discipline, workspace_id=tournament.workspace_id
        )
        answer_service.apply(
            registration, values, schema=schema, hero_catalog=hero_catalog, catalog_roles=catalog_roles
        )
        if form_version_id is not None:
            registration.form_version_id = form_version_id
        if any(identity_provider(key) for key in values):
            # A handle the registrant just added belongs on their profile now,
            # same as on submit; an anchored row keeps its player.
            await self.ensure_player_identity(
                session,
                registration,
                provider=discipline_identity_provider(tournament.discipline),
                workspace_id=tournament.workspace_id,
            )
        await self._registration_changed(session, registration)
        await session.commit()
        return await self._reload_for_read(session, registration)

    async def ensure_unique_primary_game_handles(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        values: Mapping[str, Any],
        exclude_registration_id: int | None = None,
    ) -> None:
        """No two live registrations of a tournament share a primary game handle.

        Only the PRIMARY handle of each game provider is unique: smurfs are the
        same person playing, and non-game identities (discord, boosty) are
        deliberately shareable. App-level because the handles live in a child
        table and "live" means ``deleted_at IS NULL``; every write path (public
        submit, self-edit, organizer create/edit) calls it.

        The check and the caller's INSERT are made atomic by a transaction-scoped
        advisory lock per (tournament, provider, handle): a concurrent writer of
        the same handle waits here until this transaction ends, then sees its row.
        Taken in ``GAME_PROVIDERS`` order, so two multi-handle writers cannot
        deadlock.
        """
        for provider in GAME_PROVIDERS:
            handles = values.get(identity_key(provider)) or []
            if not handles:
                continue
            normalized = normalize_social_handle(provider, handles[0])
            await session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"registration.primary_handle:{tournament_id}:{provider}:{normalized}"},
            )
            filters: list[sa.ColumnElement[bool]] = [
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
                models.Registration.identities.any(
                    sa.and_(
                        models.RegistrationIdentity.provider == provider,
                        models.RegistrationIdentity.position == 0,
                        models.RegistrationIdentity.handle_normalized == normalized,
                    )
                ),
            ]
            if exclude_registration_id is not None:
                filters.append(models.Registration.id != exclude_registration_id)
            if await self.registration_repo.exists(session, filters=filters):
                raise HTTPException(
                    status_code=409, detail="A registration with this handle already exists in this tournament"
                )

    async def get_registration_count_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> int:
        return await self.registration_repo.count(
            session,
            filters=[
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
                models.Registration.status != "withdrawn",
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
            sa.select(models.Registration.tournament_id, sa.func.count())
            .where(
                models.Registration.tournament_id.in_(tournament_ids),
                models.Registration.deleted_at.is_(None),
                models.Registration.status != "withdrawn",
            )
            .group_by(models.Registration.tournament_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def withdraw_registration(
        self,
        session: AsyncSession,
        registration: models.Registration,
    ) -> None:
        # Check-in is the point where the attendee list becomes load-bearing: the
        # balancer and the draft are run against it. Letting a participant drop
        # themselves afterwards silently invalidates a composed roster, so
        # self-withdrawal is final here. Organizers can still withdraw them through
        # the admin path (lifecycle_service.withdraw_registration), which owns that call.
        if registration.checked_in:
            raise HTTPException(status_code=409, detail="Cannot withdraw after check-in")
        registration.status = "withdrawn"
        await self._registration_changed(session, registration)
        await session.commit()

    async def check_in_registration(
        self,
        session: AsyncSession,
        registration: models.Registration,
        *,
        checked_in_by: int | None,
    ) -> models.Registration:
        if registration.status != "approved":
            raise HTTPException(status_code=409, detail="Registration must be approved before check-in")

        if not is_check_in_window_active(registration.tournament):
            raise HTTPException(status_code=409, detail="Check-in is not active for this tournament")

        registration.checked_in = True
        registration.checked_in_at = datetime.now(UTC)
        registration.checked_in_by = checked_in_by
        await self._registration_changed(session, registration)
        await session.commit()
        return await self._reload_for_read(session, registration)

    # ── public self-service use-cases (called by rpc/public_rpc.py) ──────────

    async def write_public_registration(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
        body: RegistrationSubmit | None,
        team_placement: TeamPlacement | None = None,
        commit: bool = True,
        form: models.RegistrationForm | None = None,
    ) -> models.Registration:
        """Validate and write a public self-registration; no read model is built.

        Validates the answers against the form's CURRENT version, rejects
        duplicates and writes the registration with its identity and role rows.
        :meth:`submit_public_registration` serializes the result; the team flows
        only need the row, under a lock where a read model would be built and thrown
        away.

        ``body is None`` is the team-invite shape: an invitee who already
        registered sends no form, and that branch never reaches here. A NEW
        invitee reaching this call with nothing to submit is refused rather than
        written as a blank row.

        ``team_placement`` binds the new registration to a registering team's roster
        slot. The caller owns the slot decision and must already hold the team's row
        lock — this function only writes what it is told, so that the check and the
        write cannot be separated by a concurrent acceptance.

        ``commit=False`` flushes instead, leaving the transaction boundary to the
        caller. The team flows need it because consuming an invite, writing the
        registration and updating the team's denormalized status must land together
        or not at all. A caller that passes it also owns mapping ``IntegrityError``
        at its own commit, since that fires outside this function's ``try``.

        ``form`` is the caller's already-loaded form (``current_version`` eager),
        saving the re-read.
        """
        form = form or await _common_service.get_registration_form(session, tournament_id)
        tournament = await self.tournament_repo.get(session, tournament_id)
        # ``form is None`` gates too: a tournament with no registration form has
        # nothing to submit against. Openness itself is the schedule's alone.
        if form is None or tournament is None or not is_registration_open(tournament):
            raise HTTPException(status_code=400, detail="Registration is not open for this tournament")
        if body is None:
            raise_field_errors([FieldError("answers", ErrorCode.REQUIRED.value, _ANSWERS_REQUIRED)])

        workspace_id = form.workspace_id
        schema = _require_current_schema(form, body.form_version_id)
        hero_catalog, _ = await _resolve_top_heroes_config(session, form, discipline=tournament.discipline)

        # Resolved before validation, not after: the ``require_verified`` gate
        # matches the submitted handles against THIS player's OAuth rows.
        user_player_id: int | None = await self.user_repo.get_id_by_auth_user_id(session, auth_user.id)
        values = await answer_service.validate(
            session,
            schema=schema,
            answers=body.answers,
            partial=False,
            enforce_required=True,
            player_id=user_player_id,
            workspace_id=workspace_id,
            discipline=tournament.discipline,
            hero_catalog=hero_catalog,
        )

        existing_status = await session.scalar(
            sa.select(models.Registration.status).where(
                models.Registration.tournament_id == tournament_id,
                _owned_by(auth_user.id),
                models.Registration.deleted_at.is_(None),
            )
        )
        if existing_status is not None:
            if existing_status == "withdrawn":
                raise HTTPException(status_code=409, detail="Withdrawn registrations cannot be submitted again")
            raise HTTPException(status_code=409, detail="Already registered for this tournament")

        try:
            registration = await self.create_registration(
                session,
                tournament_id=tournament_id,
                workspace_id=workspace_id,
                auth_user_id=auth_user.id,
                values=values,
                schema=schema,
                hero_catalog=hero_catalog,
                form_version_id=form.current_version_id,
                auto_approve=form.auto_approve,
                auth_user=auth_user,
                # One transaction for the row, its answers and (below) its team
                # slot: a registration with a team_id but no slot_code would be
                # counted by the roster reader and placed nowhere.
                commit=False,
                tournament=tournament,
            )
            if team_placement is not None:
                registration.registration_team_id = team_placement.registration_team_id
                registration.team_slot_code = team_placement.slot_code
                registration.is_substitute = team_placement.is_substitute
            if commit:
                await session.commit()
            else:
                await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="Already registered for this tournament")
        return registration

    async def submit_public_registration(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
        body: RegistrationSubmit | None,
        form: models.RegistrationForm | None = None,
    ) -> RegistrationRead:
        """Solo sign-up: write the row (one commit) and answer with the registrant's own card."""
        form = form or await _common_service.get_registration_form(session, tournament_id)
        registration = await self.write_public_registration(
            session, tournament_id=tournament_id, auth_user=auth_user, body=body, form=form
        )
        return await self.build_own_read(session, await self._reload_for_read(session, registration), form=form)

    async def build_own_read(
        self,
        session: AsyncSession,
        registration: models.Registration,
        *,
        form: models.RegistrationForm | None,
        chips: AdmissionChips | None = None,
    ) -> RegistrationRead:
        """The registrant's own card: sign-up, get-me, self-edit and check-in all answer with it.

        The row must carry ``registration_read_loaders()``; the tournament (phase
        schedule included) comes off it and the form is the caller's, so neither is
        read again. ``chips`` is the admission verdict, when the caller resolved one.
        """
        tournament = registration.tournament
        workspace_id = form.workspace_id if form is not None else tournament.workspace_id
        schema = schema_from_form(form)
        chips = chips or AdmissionChips.of(None)
        rosters = await _public_rosters(session, [registration], form=form)
        return _reg_to_read(
            registration,
            workspace_id=workspace_id,
            provider=discipline_identity_provider(tournament.discipline),
            status_meta_map=await get_status_metas_map(session, workspace_id=workspace_id),
            show_ranks=form.show_ranks if form is not None else False,
            admission=chips.admission,
            profiles_open=chips.profiles_open,
            subscription_outcome=chips.subscription_outcome,
            subscription_verdicts=chips.subscription_verdicts,
            roster=rosters.get(registration.id),
            queue=await self.queue_position(session, registration),
            # Their OWN card: no public-key filter (they wrote every answer), but it
            # must say when the questions moved on.
            current_version_id=form.current_version_id if form is not None else None,
            # No schema means no questions to rewrite: ``None`` reads as
            # ``can_edit=False``, which is the truth.
            self_edit=self_edit_policy(registration, tournament, schema) if schema is not None else None,
            submitted_late=submitted_late(registration, tournament),
        )

    async def resolve_admission_list(
        self,
        session: AsyncSession,
        registrations: Sequence[Any],
        *,
        form: models.RegistrationForm | None,
    ) -> dict[int, AdmissionEvaluation]:
        """One admission evaluation per registration, for a whole list.

        Shared by the public participants list and the admin registrations table
        so both render the same object instead of re-deriving "is this player
        admitted" client-side. The evaluation carries every requirement, its
        reasons and the per-provider detail the row chips need, so no consumer has
        to ask a second time.

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

        resolver = subscription_resolver(session)
        # Gated on the form flag, not on ``enforces_subscription``: that property is
        # derived FROM the rule we are about to load. A tournament with the toggle
        # off pays nothing.
        rule = (
            await resolver.load_requirement(workspace_id=form.workspace_id)
            if form is not None and form.require_subscription and form.workspace_id is not None
            else None
        )
        config = AdmissionConfig.from_form(form, subscription_rule=rule)
        return await resolve_admission(session, registrations, config=config, resolver=resolver)

    async def queue_position(self, session: AsyncSession, reg: models.Registration) -> QueuePlace:
        """Where this entry sits in the queue, overall and inside its own role.

        Ordered by ``(submitted_at, id)`` — the list's own ``ORDER BY
        submitted_at`` plus a deterministic tiebreak, so "position 5" is the
        fifth row of the participants table and not a second opinion about it.
        ``submitted_at`` is NOT NULL, so the row comparison has no null branch.

        The role place is the one that actually answers "am I getting in": a
        tournament fills role by role, so 2nd of 119 means nothing next to 42
        other DPS. ``role`` is the registration's PRIMARY role, resolved by the
        same rule ``_role_counts`` applies to the public split — the label the
        client prints must name the bucket the number was counted in.

        Two statements, and deliberately not one: inlining the role lookup as a
        scalar subquery made SQLAlchemy repeat that whole ``DISTINCT ON`` block
        three times in the emitted SQL. Splitting it costs one trivial round
        trip and keeps the invariant that matters — all four counts come from a
        single scan, so a place can never fall outside its own total.

        Counted over the same ``deleted_at IS NULL`` rows as the list, which is
        also why the total is not read off the separately cached
        ``Tournament.registrations_count``: two caches can disagree, and "5 of
        4" is worse than one aggregate.
        """
        mine = _primary_role_select(reg.tournament_id)
        role = await session.scalar(sa.select(mine.c.role).where(mine.c.registration_id == reg.id))
        by_row = _primary_role_select(reg.tournament_id)
        ordered = sa.tuple_(models.Registration.submitted_at, models.Registration.id) <= sa.tuple_(
            reg.submitted_at, reg.id
        )
        same_role = by_row.c.role == role
        result = await session.execute(
            sa.select(
                sa.func.count().filter(ordered),
                sa.func.count(),
                sa.func.count().filter(sa.and_(same_role, ordered)),
                sa.func.count().filter(same_role),
            )
            .select_from(models.Registration)
            # OUTER: a registration that declared no role is still one of the
            # entries, it just lands in no role bucket.
            .outerjoin(by_row, by_row.c.registration_id == models.Registration.id)
            .where(
                models.Registration.tournament_id == reg.tournament_id,
                models.Registration.deleted_at.is_(None),
            )
        )
        position, total, role_position, role_total = result.one()
        return QueuePlace(
            position=int(position),
            total=int(total),
            # No declared role means no role queue to be in — reported as absent
            # rather than as "1 of 1", which would read as a place nobody holds.
            role=role,
            role_position=int(role_position) if role else None,
            role_total=int(role_total) if role else None,
        )

    async def get_public_form(self, session: AsyncSession, tournament_id: int) -> RegistrationFormRead | None:
        """The registration form as a registrant sees it; ``None`` when the tournament has none."""
        form = await _common_service.get_registration_form(session, tournament_id)
        if form is None:
            return None
        discipline = await _common_service.get_tournament_discipline(session, form.tournament_id)
        subrole_catalog = await resolve_subrole_catalog(session, form.workspace_id, discipline=discipline)
        # The requirement is the workspace's rule; read here so the sync serializer stays free of round trips.
        requirement = await subscription_config_service.load_workspace_requirement_blob(session, form.workspace_id)
        is_open, registration_late = await windows_service.load_registration_state(session, tournament_id)
        return serialize_registration_form(
            form,
            discipline=discipline,
            is_open=is_open,
            registration_late=registration_late,
            subrole_catalog=subrole_catalog,
            subscription_requirement=requirement,
            stale_registrations=None,
        )

    async def build_public_registration_list(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
    ) -> RegistrationListResponse:
        """Anonymous participants-list read model.

        ``public_list.build_registration_list`` caches this payload
        (``registration_list:v2:{id}:``, same TTL as other tournament reads) and
        coalesces concurrent misses. ``registration_changed`` invalidates it; TTL
        bounds admin writes that only hit the balancer WS topic.

        ``get_status_metas_map`` is cashews-backed per workspace. That is safe
        because it caches the status *catalog*, not registrations, and all five
        catalog writes invalidate it after commit (see
        ``shared.registration_statuses``). Never wrap this in
        ``cache.disabling(...)``: it flips a *process-global* flag on the shared
        cashews backend and races with every concurrent request on this worker.
        """
        # One row for two answers: the workspace this list belongs to, and the
        # phase schedule each row's ``submitted_late`` is measured against.
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        workspace_id = tournament.workspace_id

        form = await _common_service.get_registration_form(session, tournament_id)
        max_participants = form.max_participants if form is not None else None

        # The organizer publishes the shape of the field, not the field. Enforced
        # HERE and not in the client because this payload is cached per tournament
        # with no viewer in the key (``registration_list:v2:{id}:``) -- a per-viewer
        # branch would serve one reader's answer to the next. Organizers read the
        # full roster through the admin registrations table.
        if form is not None and form.hide_registrations:
            hidden_rows = _in_field(
                await session.scalars(
                    self.registration_repo.select()
                    .where(
                        models.Registration.tournament_id == tournament_id,
                        models.Registration.deleted_at.is_(None),
                    )
                    # Roles only: no identity, no team, no history, no admission.
                    # ponytail: counted in Python over two light queries rather than
                    # one GROUP BY, so both paths share ``_in_field`` + ``_role_counts``
                    # and cannot drift. Push it into SQL if a field ever gets big enough to care.
                    .options(selectinload(models.Registration.roles))
                )
            )
            return RegistrationListResponse(
                hidden=True,
                total=len(hidden_rows),
                role_counts=_role_counts(hidden_rows),
                max_participants=max_participants,
            )

        # Analytical: the whole participants table in one ordered read with every
        # loader the serializer needs.
        result = await session.execute(
            self.registration_repo.select()
            .where(
                # tournament_id already pins this to a single workspace
                # (Registration has no denormalized workspace_id).
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
            )
            # Needed by _build_tournament_history and _reg_to_read below — the
            # member is the registration's only identity anchor, and the team brief
            # feeds the participants table's team column.
            .options(*registration_read_loaders())
            .order_by(models.Registration.submitted_at.asc())
        )
        registrations = result.scalars().all()
        status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)

        admissions = await self.resolve_admission_list(session, registrations, form=form)
        show_ranks = form.show_ranks if form is not None else False
        rosters = await _public_rosters(session, registrations, form=form)

        history_map, history_count_map, division_grids = await _build_tournament_history(
            session,
            registrations,
            tournament_id,
            workspace_id,
        )

        # Anonymous surface: the organizer chose what is public, per version, and
        # the payload is cached per tournament with no viewer in its key.
        public_keys_for = registration_public_keys(form)
        current_version_id = form.current_version_id if form is not None else None
        provider = discipline_identity_provider(tournament.discipline)
        registrations_read = []
        for r in registrations:
            chips = AdmissionChips.of(admissions.get(r.id))
            read = _reg_to_read(
                r,
                workspace_id=workspace_id,
                provider=provider,
                status_meta_map=status_meta_map,
                show_ranks=show_ranks,
                admission=chips.admission,
                profiles_open=chips.profiles_open,
                subscription_outcome=chips.subscription_outcome,
                subscription_verdicts=chips.subscription_verdicts,
                roster=rosters.get(r.id),
                public_keys=public_keys_for(r),
                current_version_id=current_version_id,
                submitted_late=submitted_late(r, tournament),
            )
            # ``dict(read)``, not ``model_dump()``: the nested reads stay model
            # instances, which pydantic accepts as-is instead of dumping them to
            # dicts and validating the whole tree a second time per row.
            registrations_read.append(
                RegistrationListRead(
                    **dict(read),
                    tournament_history=history_map.get(r.id, []),
                    tournament_history_count=history_count_map.get(r.id, 0),
                )
            )
        in_field = _in_field(registrations)
        return RegistrationListResponse(
            registrations=registrations_read,
            division_grids=division_grids,
            total=len(in_field),
            role_counts=_role_counts(in_field),
            max_participants=max_participants,
        )


registration_service = RegistrationService()
