"""Registration exports: domain-user provisioning.

``export_registrations_to_users`` provisions domain players + social identities
from approved registrations. The balancer's ``xv-1`` payload used to be
assembled here from raw role rows -- it now comes from
:meth:`shared.services.roster.RosterEngine.balancer_input`, which is the same
roster the draft and the balance job read.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider, normalize_social_handle
from shared.repository import BalancerRegistrationRepository, SocialAccountRepository, UserRepository
from shared.services.social_identity import social_identity_service
from src import models
from src.domain.registration.utils import BATTLE_TAG_SCAN_RE
from src.services.registration.lifecycle import RegistrationLifecycleService, lifecycle_service

logger = logging.getLogger(__name__)

__all__ = (
    "RegistrationExportService",
    "export_service",
    "registration_source",
)


def registration_source(registration: models.BalancerRegistration) -> str:
    return "google_sheets" if registration.google_sheet_binding is not None else "manual"


def _registration_identity_handles(registration: models.BalancerRegistration) -> list[tuple[str, str]]:
    """(provider, raw_handle) pairs this registration would upsert on export."""
    handles: list[tuple[str, str]] = []
    if registration.battle_tag:
        handles.append((SocialProvider.BATTLENET, registration.battle_tag))
        for smurf in registration.smurf_tags_json or []:
            if BATTLE_TAG_SCAN_RE.match(smurf):
                handles.append((SocialProvider.BATTLENET, smurf))
    handles.extend((identity.provider, identity.handle) for identity in registration.identities if identity.handle)
    return handles


class RegistrationExportService:
    """Balancer "xv-1" payload export and domain-player provisioning."""

    def __init__(
        self,
        *,
        registration_repo: BalancerRegistrationRepository = BalancerRegistrationRepository(),
        user_repo: UserRepository = UserRepository(),
        social_account_repo: SocialAccountRepository = SocialAccountRepository(),
        lifecycle: RegistrationLifecycleService = lifecycle_service,
    ) -> None:
        self.registration_repo = registration_repo
        self.user_repo = user_repo
        self.social_account_repo = social_account_repo
        self.lifecycle = lifecycle

    async def _find_user_by_battle_tag(self, session: AsyncSession, battle_tag: str) -> models.User | None:
        user_id = await social_identity_service.find_player_id_by_handle(
            session, provider=SocialProvider.BATTLENET, username=battle_tag
        )
        if user_id is None:
            return None
        return await self.user_repo.get(session, user_id)

    async def _ensure_user_battle_tag(self, session: AsyncSession, user: models.User, battle_tag: str) -> None:
        if "#" not in battle_tag:
            return
        await social_identity_service.upsert(
            session, user_id=user.id, provider=SocialProvider.BATTLENET, username=battle_tag
        )

    async def _upsert_user_from_registration(
        self,
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
                user = await self.user_repo.get(session, owner_id)
        else:
            user = await self._find_user_by_battle_tag(session, battle_tag)
        if user is None:
            user = await self.user_repo.create(session, models.User(name=battle_tag))
            if owner_by_handle is not None:
                owner_by_handle[main_key] = user.id

        for provider, handle in _registration_identity_handles(registration):
            if known_handles is not None:
                key = (user.id, provider, normalize_social_handle(provider, handle))
                if key in known_handles:
                    continue
                known_handles.add(key)
            await social_identity_service.upsert(session, user_id=user.id, provider=provider, username=handle)

    async def export_registrations_to_users(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> dict[str, int]:
        registrations = await self.lifecycle.list_registrations(
            session, tournament_id, include_deleted=False, status_filter="approved"
        )

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
            # Analytical: a three-column projection across every wanted handle in
            # one round trip, not a row fetch.
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
                await self._upsert_user_from_registration(
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


export_service = RegistrationExportService()
