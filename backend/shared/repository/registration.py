from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.repository.base import BaseRepository


class BalancerRegistrationRepository(BaseRepository[models.BalancerRegistration]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistration)

    async def get_active_for_user(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user_id: int,
    ) -> models.BalancerRegistration | None:
        result = await session.execute(
            sa.select(models.BalancerRegistration)
            .options(selectinload(models.BalancerRegistration.roles))
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.workspace_member.has(
                    models.WorkspaceMember.player.has(models.User.auth_user_id == auth_user_id)
                ),
                models.BalancerRegistration.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_active_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        with_workspace_member: bool = False,
    ) -> Sequence[models.BalancerRegistration]:
        options = [selectinload(models.BalancerRegistration.roles)]
        if with_workspace_member:
            options.append(selectinload(models.BalancerRegistration.workspace_member))
        result = await session.execute(
            sa.select(models.BalancerRegistration)
            .options(*options)
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
            )
            .order_by(models.BalancerRegistration.id.asc())
        )
        return result.scalars().all()


class RegistrationFormRepository(BaseRepository[models.BalancerRegistrationForm]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationForm)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerRegistrationForm | None:
        return await self.get_by(session, tournament_id=tournament_id)


class RegistrationFormVersionRepository(BaseRepository[models.BalancerRegistrationFormVersion]):
    """``registration_form_version`` — append-only schema snapshots of one form."""

    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationFormVersion)

    async def latest_number(self, session: AsyncSession, form_id: int) -> int:
        """The highest version number on ``form_id``; ``0`` when it has none yet,
        so a caller writes ``number = latest_number + 1`` without a branch."""
        result = await session.execute(
            sa.select(sa.func.max(models.BalancerRegistrationFormVersion.number)).where(
                models.BalancerRegistrationFormVersion.form_id == form_id
            )
        )
        return result.scalar_one_or_none() or 0


class RegistrationFormTemplateRepository(BaseRepository[models.BalancerRegistrationFormTemplate]):
    """``registration_form_template`` — workspace-level named schemas, copied on apply."""

    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationFormTemplate)

    async def list_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.BalancerRegistrationFormTemplate]:
        result = await session.execute(
            sa.select(models.BalancerRegistrationFormTemplate)
            .where(models.BalancerRegistrationFormTemplate.workspace_id == workspace_id)
            .order_by(models.BalancerRegistrationFormTemplate.name.asc())
        )
        return result.scalars().all()

    async def get_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
        template_id: int,
    ) -> models.BalancerRegistrationFormTemplate | None:
        """Scoped by workspace on purpose: a bare id lookup would let one
        workspace read or overwrite another's template."""
        return await self.get_by(session, id=template_id, workspace_id=workspace_id)


class RegistrationStatusRepository(BaseRepository[models.BalancerRegistrationStatus]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationStatus)

    async def get_by_slug(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None,
        scope: str,
        slug: str,
        kind: str | None = None,
    ) -> models.BalancerRegistrationStatus | None:
        filters: list[sa.ColumnElement[bool]] = [
            models.BalancerRegistrationStatus.workspace_id.is_(None)
            if workspace_id is None
            else models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == slug,
        ]
        if kind is not None:
            filters.append(models.BalancerRegistrationStatus.kind == kind)
        result = await session.execute(sa.select(models.BalancerRegistrationStatus).where(*filters))
        return result.scalar_one_or_none()

    async def list_for_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        scope: str | None = None,
    ) -> Sequence[models.BalancerRegistrationStatus]:
        filters: list[sa.ColumnElement[bool]] = [
            sa.or_(
                models.BalancerRegistrationStatus.workspace_id == workspace_id,
                models.BalancerRegistrationStatus.workspace_id.is_(None),
            )
        ]
        if scope is not None:
            filters.append(models.BalancerRegistrationStatus.scope == scope)
        result = await session.execute(
            sa.select(models.BalancerRegistrationStatus)
            .where(*filters)
            .order_by(
                models.BalancerRegistrationStatus.scope.asc(),
                sa.case((models.BalancerRegistrationStatus.workspace_id.is_(None), 0), else_=1).asc(),
                models.BalancerRegistrationStatus.kind.asc(),
                models.BalancerRegistrationStatus.name.asc(),
                models.BalancerRegistrationStatus.id.asc(),
            )
        )
        return result.scalars().all()


class GoogleSheetFeedRepository(BaseRepository[models.BalancerRegistrationGoogleSheetFeed]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationGoogleSheetFeed)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerRegistrationGoogleSheetFeed | None:
        return await self.get_by(session, tournament_id=tournament_id)


class BalancerRegistrationTeamRepository(BaseRepository[models.BalancerRegistrationTeam]):
    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationTeam)

    async def get_active_for_update(
        self, session: AsyncSession, team_id: int
    ) -> models.BalancerRegistrationTeam | None:
        """The serialization point for every roster decision on a team.

        Eleven flows take this lock before reading slot occupancy; it is what stops
        two invitees from redeeming into the same slot. Plain ``FOR UPDATE`` — no
        ``skip_locked``, no ``nowait``: a caller must wait its turn, not skip the row.

        Named ``get_active_for_update`` rather than ``get_for_update`` because
        ``deleted_at IS NULL`` is part of the lock's meaning — a disbanded team must
        not be lockable at all.
        """
        team = models.BalancerRegistrationTeam
        return await session.scalar(
            self.select().where(team.id == team_id, team.deleted_at.is_(None)).with_for_update()
        )


class BalancerRegistrationRoleRepository(BaseRepository[models.BalancerRegistrationRole]):
    """``registration_role`` — one declared role (with rank/priority) on a registration."""

    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationRole)


class BalancerRegistrationTeamInviteRepository(BaseRepository[models.BalancerRegistrationTeamInvite]):
    """``registration_team_invite`` — slot offers a captain issues for their team."""

    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationTeamInvite)

    @staticmethod
    def _live_clause() -> sa.ColumnElement[bool]:
        """ "Not expired" — a NULL ``expires_at`` never lapses."""
        invite = models.BalancerRegistrationTeamInvite
        return sa.or_(invite.expires_at.is_(None), invite.expires_at > sa.func.now())

    async def list_pending(
        self, session: AsyncSession, team_id: int, *, pending_state: str
    ) -> Sequence[models.BalancerRegistrationTeamInvite]:
        """Live invites only: an expired one reserves nothing, so its slot is
        offerable again without an explicit revoke."""
        invite = models.BalancerRegistrationTeamInvite
        result = await session.scalars(
            self.select().where(
                invite.team_id == team_id,
                invite.state == pending_state,
                self._live_clause(),
            )
        )
        return result.all()

    async def list_for_team(
        self, session: AsyncSession, team_id: int
    ) -> Sequence[models.BalancerRegistrationTeamInvite]:
        invite = models.BalancerRegistrationTeamInvite
        result = await session.scalars(
            self.select().where(invite.team_id == team_id).order_by(invite.invited_at.desc())
        )
        return result.all()

    async def get_by_token_hash(
        self, session: AsyncSession, token_sha256: str
    ) -> models.BalancerRegistrationTeamInvite | None:
        """Indexed single read against the partial unique index on the hash.

        The raw token is never compared against anything stored.
        """
        return await session.scalar(
            self.select().where(models.BalancerRegistrationTeamInvite.token_sha256 == token_sha256)
        )

    async def consume_if_pending(
        self,
        session: AsyncSession,
        invite_id: int,
        *,
        pending_state: str,
        accepted_state: str,
        accepted_at: datetime,
    ) -> bool:
        """Atomically claim a pending, unexpired invite. ``True`` only for the winner.

        State and expiry are checked *inside* the UPDATE, so two simultaneous
        redemptions of one link cannot both succeed. Preserved verbatim as a single
        conditional statement — a read-then-write reintroduces the double-redeem race.
        """
        invite = models.BalancerRegistrationTeamInvite
        consumed = await session.execute(
            sa.update(invite)
            .where(
                invite.id == invite_id,
                invite.state == pending_state,
                self._live_clause(),
            )
            .values(state=accepted_state, accepted_at=accepted_at)
            .returning(invite.id)
        )
        return consumed.first() is not None

    async def revoke_pending_for_team(
        self,
        session: AsyncSession,
        team_id: int,
        *,
        pending_state: str,
        revoked_state: str,
    ) -> None:
        """Revoke every pending invite on a team, expired ones included.

        Deliberately does NOT carry ``_live_clause()``: disbanding or rejecting a team
        must close out expired pending rows too, so they cannot linger in a state the
        UI still renders as outstanding. That is the opposite of ``consume_if_pending``,
        where an expired row must not be redeemable.
        """
        invite = models.BalancerRegistrationTeamInvite
        await session.execute(
            sa.update(invite)
            .where(invite.team_id == team_id, invite.state == pending_state)
            .values(state=revoked_state)
        )


class GoogleSheetBindingRepository(BaseRepository[models.BalancerRegistrationGoogleSheetBinding]):
    """``registration_google_sheet_binding`` — one imported sheet row ↔ one registration."""

    def __init__(self) -> None:
        super().__init__(models.BalancerRegistrationGoogleSheetBinding)

    async def list_source_record_keys(self, session: AsyncSession, feed_id: int) -> Sequence[str]:
        binding = models.BalancerRegistrationGoogleSheetBinding
        result = await session.scalars(sa.select(binding.source_record_key).where(binding.feed_id == feed_id))
        return result.all()

    async def list_by_feed(
        self,
        session: AsyncSession,
        feed_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.BalancerRegistrationGoogleSheetBinding]:
        query = self._apply_options(
            self.select().where(models.BalancerRegistrationGoogleSheetBinding.feed_id == feed_id),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()
