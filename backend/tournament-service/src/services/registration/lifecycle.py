"""Registration lifecycle CRUD for the admin surface.

Listing, manual creation, profile edits, review transitions
(approve/reject/withdraw/restore), soft delete, balancer inclusion/status and
check-in.

Note for tests: ``lifecycle_service`` resolves its collaborators from
constructor-injected attributes (``self.registration_repo``, ``self.common``,
``self.registrations``), so intercept e.g. ``get_registration_by_id`` by
patching the attribute or the method on ``lifecycle_service`` — not a module
global. Free functions imported here (``enqueue_registration_approved`` and
friends) are still module globals of *this* module and patch as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import balancer_pool_excluded_clause, balancer_pool_included_clause
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.roster import flex_role_mode
from shared.repository import (
    BalancerRegistrationRepository,
    RegistrationStatusRepository,
    TournamentRepository,
)
from shared.services.roster import registration_load_options, roster_engine
from src import models
from src.domain.registration.utils import (
    normalize_battle_tag,
    normalize_battle_tag_key,
)
from src.schemas.registration_build import registration_read_loaders
from src.services.registration._common import (
    AUTO_MANAGED_BALANCER_STATUSES,
    EXCLUDED_BALANCER_STATUS,
    NOT_ADDED_BALANCER_STATUS,
    VALID_BALANCER_STATUSES,
    VALID_REGISTRATION_STATUSES,
    RegistrationCommonService,
    _common_service,
    included_balancer_status,
    replace_registration_roles,
    resolve_roster,
    sync_included_balancer_status,
)
from src.services.registration.service import RegistrationService, registration_service
from src.services.tournament.events import (
    enqueue_registration_approved,
    enqueue_registration_rejected,
)

__all__ = ("RegistrationLifecycleService", "lifecycle_service")


def _reject_auto_managed_status(balancer_status: str) -> None:
    """`ready`/`incomplete` are derived from role ranks -- reject any write
    path that tries to set them as a literal, explicit value. The only writer
    of these two values is `sync_included_balancer_status`.
    """
    if balancer_status in AUTO_MANAGED_BALANCER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"'{balancer_status}' is computed automatically from role ranks and cannot be set directly; "
                "add the registration to the balancer pool instead."
            ),
        )


def _registration_read_options() -> list[Any]:
    """Eager loads every admin serializer of a single registration needs."""
    return [
        selectinload(models.BalancerRegistration.roles)
        .selectinload(models.BalancerRegistrationRole.hero_entries)
        .selectinload(models.BalancerRegistrationRoleHero.hero),
        selectinload(models.BalancerRegistration.reviewer),
        selectinload(models.BalancerRegistration.checked_in_by_user),
        selectinload(models.BalancerRegistration.google_sheet_binding),
        selectinload(models.BalancerRegistration.tournament),
        *registration_read_loaders(),
    ]


async def _workspace_id_for(session: AsyncSession, registration: Any) -> int | None:
    """The registration's tenancy, which every inherited rank layer is scoped by.

    Read as a scalar unless ``tournament`` is already in the instance dict:
    several callers here load only ``roles``, and touching an unloaded
    relationship on an async session raises instead of lazy-loading.
    """
    tournament = registration.__dict__.get("tournament")
    if tournament is not None:
        return tournament.workspace_id
    return await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == registration.tournament_id)
    )


class RegistrationLifecycleService:
    """Admin-side registration lifecycle: listing, creation, edits, review
    transitions, balancer status and check-in."""

    def __init__(
        self,
        *,
        registration_repo: BalancerRegistrationRepository = BalancerRegistrationRepository(),
        status_repo: RegistrationStatusRepository = RegistrationStatusRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        common: RegistrationCommonService = _common_service,
        registrations: RegistrationService = registration_service,
    ) -> None:
        self.registration_repo = registration_repo
        self.status_repo = status_repo
        self.tournament_repo = tournament_repo
        self.common = common
        self.registrations = registrations

    async def list_registrations(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        status_filter: str | None = None,
        inclusion_filter: str | None = None,
        source_filter: str | None = None,
        include_deleted: bool = False,
    ) -> list[models.BalancerRegistration]:
        # Analytical: the admin table's filter matrix, including a correlated
        # workspace subquery for the balancer-pool clauses.
        query = (
            self.registration_repo.select()
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
                # serialize_registration derives user_id from workspace_member.player_id
                # and the team brief from registration_team; both must be eager.
                *registration_read_loaders(),
            )
            .order_by(models.BalancerRegistration.submitted_at.desc(), models.BalancerRegistration.id.desc())
        )
        if not include_deleted:
            query = query.where(models.BalancerRegistration.deleted_at.is_(None))
        if status_filter and status_filter != "all":
            query = query.where(models.BalancerRegistration.status == status_filter)
        if inclusion_filter in ("included", "excluded"):
            workspace_id_expr = (
                sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id).scalar_subquery()
            )
            clause = balancer_pool_included_clause if inclusion_filter == "included" else balancer_pool_excluded_clause
            query = query.where(clause(models.BalancerRegistration.balancer_status, workspace_id_expr))
        if source_filter == "google_sheets":
            query = query.where(models.BalancerRegistration.google_sheet_binding.has())
        elif source_filter == "manual":
            query = query.where(~models.BalancerRegistration.google_sheet_binding.has())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_registration_by_id(self, session: AsyncSession, registration_id: int) -> models.BalancerRegistration:
        registration = await self.registration_repo.get(session, registration_id, options=_registration_read_options())
        if registration is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
        return registration

    async def ensure_unique_battle_tag(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        battle_tag: str | None,
        exclude_registration_id: int | None = None,
    ) -> None:
        normalized = normalize_battle_tag_key(battle_tag)
        if not normalized:
            return
        filters: list[sa.ColumnElement[bool]] = [
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.battle_tag_normalized == normalized,
        ]
        if exclude_registration_id is not None:
            filters.append(models.BalancerRegistration.id != exclude_registration_id)
        if await self.registration_repo.exists(session, filters=filters):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Registration with this BattleTag already exists"
            )

    async def validate_registration_status_value(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        scope: str,
        value: str,
    ) -> None:
        builtin_values = VALID_REGISTRATION_STATUSES if scope == "registration" else VALID_BALANCER_STATUSES
        if value in builtin_values:
            return

        if await self.status_repo.get_by_slug(session, workspace_id=workspace_id, scope=scope, slug=value) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {scope} status: {value}",
            )

    async def create_manual_registration(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        display_name: str | None,
        battle_tag: str | None,
        smurf_tags_json: list[str] | None,
        discord_nick: str | None,
        twitch_nick: str | None,
        boosty_nick: str | None = None,
        stream_pov: bool = False,
        notes: str | None,
        admin_notes: str | None,
        custom_fields_json: dict[str, Any] | None = None,
        status_value: str | None = None,
        balancer_status_value: str | None = None,
        roles: list[dict[str, Any]],
        auth_user_id: int | None = None,
    ) -> models.BalancerRegistration:
        battle_tag = normalize_battle_tag(battle_tag)
        await self.ensure_unique_battle_tag(session, tournament_id=tournament_id, battle_tag=battle_tag)

        resolved_status = status_value or "approved"
        workspace_id = await self.tournament_repo.get_workspace_id(session, tournament_id)
        if status_value is not None or balancer_status_value is not None:
            if status_value is not None:
                await self.validate_registration_status_value(
                    session, workspace_id=workspace_id, scope="registration", value=status_value
                )
            if balancer_status_value is not None:
                await self.validate_registration_status_value(
                    session, workspace_id=workspace_id, scope="balancer", value=balancer_status_value
                )

        form = await self.common.get_registration_form(session, tournament_id)
        config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
        hero_catalog = None
        max_heroes = None
        if config and config.get("enabled", True) is not False:
            from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, resolve_hero_catalog

            hero_catalog = await resolve_hero_catalog(session)
            raw_max = config.get("max_heroes")
            max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

        registration = models.BalancerRegistration(
            tournament_id=tournament_id,
            display_name=display_name or battle_tag,
            battle_tag=battle_tag,
            battle_tag_normalized=normalize_battle_tag_key(battle_tag),
            smurf_tags_json=smurf_tags_json or None,
            discord_nick=discord_nick,
            twitch_nick=twitch_nick,
            boosty_nick=boosty_nick,
            stream_pov=stream_pov,
            notes=notes,
            admin_notes=admin_notes,
            custom_fields_json=custom_fields_json or None,
            status=resolved_status,
            balancer_status=NOT_ADDED_BALANCER_STATUS,
        )
        replace_registration_roles(
            registration,
            roles,
            hero_catalog=hero_catalog,
            max_heroes=max_heroes,
            mode=flex_role_mode(form),
        )
        auto_managed = balancer_status_value is None or balancer_status_value in AUTO_MANAGED_BALANCER_STATUSES
        if not auto_managed:
            registration.balancer_status = balancer_status_value
        await self.registration_repo.create(session, registration)
        # Unconditional, and with the workspace: a manual registration has no auth
        # account, but its BattleTag is still the identity every inherited rank
        # layer is read through. Gating this on ``auth_user_id`` left admin-created
        # rows with no ``workspace_member``, hence no canon to inherit.
        await self.registrations.ensure_player_identity(
            session, registration, auth_user_id=auth_user_id, workspace_id=workspace_id
        )
        if auto_managed:
            # Resolved only now: the member anchor above is what the inherited rank
            # layers hang off, so a roster read before it would rate every blank
            # role as unranked.
            registration.balancer_status = (
                included_balancer_status(await resolve_roster(session, registration))
                if resolved_status == "approved"
                else NOT_ADDED_BALANCER_STATUS
            )
        if resolved_status == "approved":
            await enqueue_registration_approved(session, registration)
        else:
            await self.common._register_registration_changed(session, registration)
        await session.commit()
        return await self.get_registration_by_id(session, registration.id)

    async def update_registration_profile(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        display_name: str | None,
        battle_tag: str | None,
        smurf_tags_json: list[str] | None,
        discord_nick: str | None,
        twitch_nick: str | None,
        boosty_nick: str | None = None,
        stream_pov: bool | None = None,
        notes: str | None,
        admin_notes: str | None,
        custom_fields_json: dict[str, Any] | None = None,
        status_value: str | None,
        balancer_status_value: str | None,
        roles: list[dict[str, Any]] | None,
        auth_user_id: int | None = None,
        exclude_reason: str | None = None,
        pin: bool | None = None,
        clear_pin: bool = False,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        previous_status = registration.status
        if battle_tag is not None:
            normalized_battle_tag = normalize_battle_tag(battle_tag)
            await self.ensure_unique_battle_tag(
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
        if boosty_nick is not None:
            registration.boosty_nick = boosty_nick
        if stream_pov is not None:
            registration.stream_pov = stream_pov
        if notes is not None:
            registration.notes = notes
        if custom_fields_json is not None:
            registration.custom_fields_json = custom_fields_json or None
        if admin_notes is not None:
            registration.admin_notes = admin_notes
        if status_value is not None:
            await self.validate_registration_status_value(
                session,
                workspace_id=registration.tournament.workspace_id,
                scope="registration",
                value=status_value,
            )
            registration.status = status_value
        if balancer_status_value is not None:
            if balancer_status_value in AUTO_MANAGED_BALANCER_STATUSES:
                sync_included_balancer_status(registration, await resolve_roster(session, registration))
            else:
                await self.validate_registration_status_value(
                    session,
                    workspace_id=registration.tournament.workspace_id,
                    scope="balancer",
                    value=balancer_status_value,
                )
                if balancer_status_value != NOT_ADDED_BALANCER_STATUS and registration.status != "approved":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Registration must be approved before adding to balancer",
                    )
                registration.balancer_status = balancer_status_value
                registration.exclude_reason = (
                    exclude_reason if balancer_status_value == EXCLUDED_BALANCER_STATUS else None
                )

        unpin = clear_pin or (pin is False and roles is None)
        if roles is not None:
            for r_obj in registration.roles:
                r_obj.hero_entries.clear()
            await session.flush()

            form = await self.common.get_registration_form(session, registration.tournament_id)
            config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
            hero_catalog = None
            max_heroes = None
            if config and config.get("enabled", True) is not False:
                from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, resolve_hero_catalog

                hero_catalog = await resolve_hero_catalog(session)
                raw_max = config.get("max_heroes")
                max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

            replace_registration_roles(
                registration,
                roles,
                hero_catalog=hero_catalog,
                max_heroes=max_heroes,
                mode=flex_role_mode(form),
            )

        if pin:
            registration.balancer_profile_overridden_at = datetime.now(UTC)
        elif unpin:
            registration.balancer_profile_overridden_at = None

        workspace_id = await _workspace_id_for(session, registration)
        # Same reason as create_manual_registration: the anchor must not depend on
        # whoever is editing being signed in as the registrant.
        await self.registrations.ensure_player_identity(
            session, registration, auth_user_id=auth_user_id, workspace_id=workspace_id
        )
        if roles is not None or unpin:
            sync_included_balancer_status(registration, await resolve_roster(session, registration))

        if status_value == "approved" and previous_status != "approved":
            await enqueue_registration_approved(session, registration)
        elif status_value == "rejected" and previous_status != "rejected":
            await enqueue_registration_rejected(session, registration)
        else:
            await self.common._register_registration_changed(session, registration)

        await session.commit()
        if roles is not None or auth_user_id is not None:
            return await self.get_registration_by_id(session, registration.id)
        return registration

    async def approve_registration(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        reviewed_by: int | None,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        registration.status = "approved"
        registration.reviewed_at = datetime.now(UTC)
        registration.reviewed_by = reviewed_by
        # A pending registration's balancer_status is always not_in_balancer with
        # no exclude_reason -- every write path that could set anything else
        # requires status == "approved" already (see set_balancer_status /
        # update_registration_profile). Nothing to reset here.
        await enqueue_registration_approved(session, registration)
        await session.commit()
        # Refetch: reviewed_by changed, the serializer needs a loaded .reviewer.
        return await self.get_registration_by_id(session, registration.id)

    async def reject_registration(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        reviewed_by: int | None,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        registration.status = "rejected"
        registration.reviewed_at = datetime.now(UTC)
        registration.reviewed_by = reviewed_by
        await enqueue_registration_rejected(session, registration)
        await session.commit()
        # Refetch: reviewed_by changed, the serializer needs a loaded .reviewer.
        return await self.get_registration_by_id(session, registration.id)

    async def bulk_approve_registrations(
        self,
        session: AsyncSession,
        tournament_id: int,
        registration_ids: list[int],
        *,
        reviewed_by: int | None,
    ) -> tuple[int, int]:
        result = await session.execute(
            self.registration_repo.select().where(
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
            await enqueue_registration_approved(session, registration)
        await session.commit()
        return len(registrations), len(registration_ids) - len(registrations)

    async def add_to_balancer(
        self,
        session: AsyncSession,
        registration_id: int,
    ) -> models.BalancerRegistration:
        """Put an approved registration into the pool, rating it from its resolved
        roster (`ready` if every declared role carries a rank, else `incomplete`).

        Replaces the former `set_registration_exclusion(..., exclude_from_balancer=False)`
        path -- the "(re)include" half of the old exclusion toggle.
        """
        registration = await self.get_registration_by_id(session, registration_id)
        if registration.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registration must be approved before adding to balancer",
            )
        registration.exclude_reason = None
        registration.balancer_status = included_balancer_status(await resolve_roster(session, registration))
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        # Scalar-only mutation; the eagerly-loaded object stays valid after
        # commit (expire_on_commit=False), so no refetch is needed.
        return registration

    async def withdraw_registration(
        self,
        session: AsyncSession,
        registration_id: int,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        registration.status = "withdrawn"
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        # Scalar-only mutation; no refetch needed (expire_on_commit=False).
        return registration

    async def restore_registration(
        self,
        session: AsyncSession,
        registration_id: int,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        registration.status = "approved"
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        # Scalar-only mutation; no refetch needed (expire_on_commit=False).
        return registration

    async def soft_delete_registration(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        deleted_by: int | None,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        registration.deleted_at = datetime.now(UTC)
        registration.deleted_by = deleted_by
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        return registration

    async def set_balancer_status(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        balancer_status: str,
        exclude_reason: str | None = None,
    ) -> models.BalancerRegistration:
        """Explicitly pin a registration to a balancer status: `not_in_balancer`,
        `excluded` (with an optional `exclude_reason`), or a workspace custom
        slug. `ready`/`incomplete` are rejected -- those two are exclusively
        derived from role ranks; use `add_to_balancer` to (re)compute one of them.
        """
        _reject_auto_managed_status(balancer_status)
        registration = await self.get_registration_by_id(session, registration_id)
        await self.validate_registration_status_value(
            session,
            workspace_id=registration.tournament.workspace_id,
            scope="balancer",
            value=balancer_status,
        )
        if balancer_status != NOT_ADDED_BALANCER_STATUS and registration.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registration must be approved before adding to balancer",
            )
        registration.balancer_status = balancer_status
        registration.exclude_reason = exclude_reason if balancer_status == EXCLUDED_BALANCER_STATUS else None
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        # Scalar-only mutation; no refetch needed (expire_on_commit=False).
        return registration

    async def check_in_registration(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        checked_in_by: int | None,
    ) -> models.BalancerRegistration:
        """Admin check-in. Deliberately ungated by the CHECK_IN phase window --
        organizers check people in before the phase opens, after it closes, and
        during LIVE when someone shows up late. The window gate belongs to the
        self-service path only (``registration_service.check_in_registration``),
        and undo (``uncheck_in_registration``) has never had one either.
        """
        registration = await self.get_registration_by_id(session, registration_id)
        registration.checked_in = True
        registration.checked_in_at = datetime.now(UTC)
        registration.checked_in_by = checked_in_by
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        # Refetch: checked_in_by changed, the serializer needs a loaded
        # .checked_in_by_user.
        return await self.get_registration_by_id(session, registration.id)

    async def uncheck_in_registration(
        self,
        session: AsyncSession,
        registration_id: int,
    ) -> models.BalancerRegistration:
        registration = await self.get_registration_by_id(session, registration_id)
        registration.checked_in = False
        registration.checked_in_at = None
        registration.checked_in_by = None
        # Also clear the loaded relationship so the serializer does not report a
        # stale username: assigning the FK column alone leaves .checked_in_by_user
        # populated (and we skip the refetch — expire_on_commit=False keeps the
        # object valid after commit).
        registration.checked_in_by_user = None
        await self.common._register_registration_changed(session, registration)
        await session.commit()
        return registration

    async def bulk_add_to_balancer(
        self,
        session: AsyncSession,
        tournament_id: int,
        registration_ids: list[int],
    ) -> tuple[int, int]:
        """Bulk version of `add_to_balancer` -- only approved registrations
        qualify; every other id is silently skipped (counted, not errored).
        """
        result = await session.execute(
            self.registration_repo.select()
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.id.in_(registration_ids),
                models.BalancerRegistration.status == "approved",
            )
            # The engine reads roles, their heroes and the member anchor; none of
            # them may lazy-load on an async session.
            .options(*registration_load_options())
        )
        registrations = list(result.scalars().all())
        workspace_id = await session.scalar(
            sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
        )
        rosters = await roster_engine.resolve(
            session, registrations, workspace_id=workspace_id, tournament_id=tournament_id
        )
        for registration in registrations:
            registration.exclude_reason = None
            registration.balancer_status = included_balancer_status(rosters.get(registration.id))
        await session.commit()
        return len(registrations), len(registration_ids) - len(registrations)

    async def bulk_set_balancer_status(
        self,
        session: AsyncSession,
        tournament_id: int,
        registration_ids: list[int],
        *,
        balancer_status: str,
        exclude_reason: str | None = None,
    ) -> tuple[int, int]:
        """Bulk version of `set_balancer_status`. Rejects the request outright
        for the auto-managed ready/incomplete pair (structural error, not a
        per-row skip); rows that aren't approved are silently skipped when
        `balancer_status` isn't `not_in_balancer`, mirroring the single-row 409.
        """
        _reject_auto_managed_status(balancer_status)
        tournament = await self.common.ensure_tournament_exists(session, tournament_id)
        await self.validate_registration_status_value(
            session,
            workspace_id=tournament.workspace_id,
            scope="balancer",
            value=balancer_status,
        )
        query = self.registration_repo.select().where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.id.in_(registration_ids),
        )
        if balancer_status != NOT_ADDED_BALANCER_STATUS:
            query = query.where(models.BalancerRegistration.status == "approved")
        result = await session.execute(query)
        registrations = list(result.scalars().all())
        for registration in registrations:
            registration.balancer_status = balancer_status
            registration.exclude_reason = exclude_reason if balancer_status == EXCLUDED_BALANCER_STATUS else None
            await self.common._register_registration_changed(session, registration)
        await session.commit()
        return len(registrations), len(registration_ids) - len(registrations)


lifecycle_service = RegistrationLifecycleService()
