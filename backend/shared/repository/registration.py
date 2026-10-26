from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.repository.base import BaseRepository


class RegistrationRepository(BaseRepository[models.Registration]):
    def __init__(self) -> None:
        super().__init__(models.Registration)

    async def attach_to_team_if_free(
        self,
        session: AsyncSession,
        registration_id: int,
        *,
        team_id: int,
        slot_code: str,
        is_substitute: bool,
    ) -> bool:
        """Seat a registration on a team only if it sits on none. ``True`` only when it was seated.

        "On no team" is checked *inside* the UPDATE, so a member of another team is
        never silently moved and two accepts into two different teams (two different
        team locks) cannot both seat the row. ORM-enabled, so a loaded instance sees
        the new seat.
        """
        registration = models.Registration
        seated = await session.scalar(
            sa.update(registration)
            .where(registration.id == registration_id, registration.registration_team_id.is_(None))
            .values(registration_team_id=team_id, team_slot_code=slot_code, is_substitute=is_substitute)
            .returning(registration.id)
        )
        return seated is not None


class RegistrationFormRepository(BaseRepository[models.RegistrationForm]):
    def __init__(self) -> None:
        super().__init__(models.RegistrationForm)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.RegistrationForm | None:
        return await self.get_by(session, tournament_id=tournament_id)


class RegistrationFormVersionRepository(BaseRepository[models.RegistrationFormVersion]):
    """``registration_form_version`` — append-only schema snapshots of one form."""

    def __init__(self) -> None:
        super().__init__(models.RegistrationFormVersion)

    async def latest_number(self, session: AsyncSession, form_id: int) -> int:
        """The highest version number on ``form_id``; ``0`` when it has none yet,
        so a caller writes ``number = latest_number + 1`` without a branch."""
        result = await session.execute(
            sa.select(sa.func.max(models.RegistrationFormVersion.number)).where(
                models.RegistrationFormVersion.form_id == form_id
            )
        )
        return result.scalar_one_or_none() or 0

    async def current_schema_json(self, session: AsyncSession, tournament_id: int) -> dict | None:
        """``schema_json`` of the tournament form's current version; ``None`` when there is no form."""
        return await session.scalar(
            sa.select(models.RegistrationFormVersion.schema_json)
            .join(
                models.RegistrationForm,
                models.RegistrationForm.current_version_id == models.RegistrationFormVersion.id,
            )
            .where(models.RegistrationForm.tournament_id == tournament_id)
        )


class RegistrationFormTemplateRepository(BaseRepository[models.RegistrationFormTemplate]):
    """``registration_form_template`` — workspace-level named schemas, copied on apply."""

    def __init__(self) -> None:
        super().__init__(models.RegistrationFormTemplate)

    async def list_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
        *,
        discipline: str | None = None,
    ) -> Sequence[models.RegistrationFormTemplate]:
        """The workspace's templates by name; ``discipline`` narrows to one game's."""
        query = (
            sa.select(models.RegistrationFormTemplate)
            .where(models.RegistrationFormTemplate.workspace_id == workspace_id)
            .order_by(models.RegistrationFormTemplate.name.asc())
        )
        if discipline is not None:
            query = query.where(models.RegistrationFormTemplate.discipline == discipline)
        result = await session.execute(query)
        return result.scalars().all()

    async def get_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
        template_id: int,
    ) -> models.RegistrationFormTemplate | None:
        """Scoped by workspace on purpose: a bare id lookup would let one
        workspace read or overwrite another's template."""
        return await self.get_by(session, id=template_id, workspace_id=workspace_id)


class RegistrationStatusRepository(BaseRepository[models.RegistrationStatus]):
    def __init__(self) -> None:
        super().__init__(models.RegistrationStatus)

    async def get_by_slug(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None,
        scope: str,
        slug: str,
        kind: str | None = None,
    ) -> models.RegistrationStatus | None:
        filters: list[sa.ColumnElement[bool]] = [
            models.RegistrationStatus.workspace_id.is_(None)
            if workspace_id is None
            else models.RegistrationStatus.workspace_id == workspace_id,
            models.RegistrationStatus.scope == scope,
            models.RegistrationStatus.slug == slug,
        ]
        if kind is not None:
            filters.append(models.RegistrationStatus.kind == kind)
        result = await session.execute(sa.select(models.RegistrationStatus).where(*filters))
        return result.scalar_one_or_none()

    async def list_for_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        scope: str | None = None,
    ) -> Sequence[models.RegistrationStatus]:
        filters: list[sa.ColumnElement[bool]] = [
            sa.or_(
                models.RegistrationStatus.workspace_id == workspace_id,
                models.RegistrationStatus.workspace_id.is_(None),
            )
        ]
        if scope is not None:
            filters.append(models.RegistrationStatus.scope == scope)
        result = await session.execute(
            sa.select(models.RegistrationStatus)
            .where(*filters)
            .order_by(
                models.RegistrationStatus.scope.asc(),
                sa.case((models.RegistrationStatus.workspace_id.is_(None), 0), else_=1).asc(),
                models.RegistrationStatus.kind.asc(),
                models.RegistrationStatus.name.asc(),
                models.RegistrationStatus.id.asc(),
            )
        )
        return result.scalars().all()


class GoogleSheetFeedRepository(BaseRepository[models.RegistrationGoogleSheetFeed]):
    def __init__(self) -> None:
        super().__init__(models.RegistrationGoogleSheetFeed)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.RegistrationGoogleSheetFeed | None:
        return await self.get_by(session, tournament_id=tournament_id)


class RegistrationTeamRepository(BaseRepository[models.RegistrationTeam]):
    def __init__(self) -> None:
        super().__init__(models.RegistrationTeam)

    async def get_active_for_update(self, session: AsyncSession, team_id: int) -> models.RegistrationTeam | None:
        """The serialization point for every roster decision on a team.

        Eleven flows take this lock before reading slot occupancy; it is what stops
        two invitees from redeeming into the same slot. Plain ``FOR UPDATE`` — no
        ``skip_locked``, no ``nowait``: a caller must wait its turn, not skip the row.

        Named ``get_active_for_update`` rather than ``get_for_update`` because
        ``deleted_at IS NULL`` is part of the lock's meaning — a disbanded team must
        not be lockable at all.

        ``populate_existing``: the values this returns must be the locked row's, not a
        copy the session read before it took the lock.
        """
        team = models.RegistrationTeam
        return await session.scalar(
            self.select()
            .where(team.id == team_id, team.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )


class RegistrationRoleRepository(BaseRepository[models.RegistrationRole]):
    """``registration_role`` — one declared role (with rank/priority) on a registration."""

    def __init__(self) -> None:
        super().__init__(models.RegistrationRole)

    async def get_by_registration_and_role(
        self, session: AsyncSession, registration_id: int, role: str
    ) -> models.RegistrationRole | None:
        """The registration's row for ``role``, active or not."""
        return await session.scalar(
            sa.select(models.RegistrationRole).where(
                models.RegistrationRole.registration_id == registration_id,
                models.RegistrationRole.role == role,
            )
        )

    async def next_priority(self, session: AsyncSession, registration_id: int) -> int:
        """``max(priority) + 1`` over the registration's roles; ``0`` when it has none."""
        return (
            await session.scalar(
                sa.select(sa.func.coalesce(sa.func.max(models.RegistrationRole.priority), -1)).where(
                    models.RegistrationRole.registration_id == registration_id
                )
            )
        ) + 1


class RegistrationTeamInviteRepository(BaseRepository[models.RegistrationTeamInvite]):
    """``registration_team_invite`` — slot offers a captain issues for their team."""

    def __init__(self) -> None:
        super().__init__(models.RegistrationTeamInvite)

    @staticmethod
    def _live_clause() -> sa.ColumnElement[bool]:
        """ "Not expired" — a NULL ``expires_at`` never lapses."""
        invite = models.RegistrationTeamInvite
        return sa.or_(invite.expires_at.is_(None), invite.expires_at > sa.func.now())

    async def list_pending(
        self, session: AsyncSession, team_id: int, *, pending_state: str
    ) -> Sequence[models.RegistrationTeamInvite]:
        """Live invites only: an expired one reserves nothing, so its slot is
        offerable again without an explicit revoke."""
        invite = models.RegistrationTeamInvite
        result = await session.scalars(
            self.select().where(
                invite.team_id == team_id,
                invite.state == pending_state,
                self._live_clause(),
            )
        )
        return result.all()

    async def list_pending_for_teams(
        self, session: AsyncSession, team_ids: Sequence[int], *, pending_state: str
    ) -> Sequence[models.RegistrationTeamInvite]:
        """:meth:`list_pending` for a page of teams, in one ``IN (…)`` read."""
        if not team_ids:
            return []
        invite = models.RegistrationTeamInvite
        result = await session.scalars(
            self.select().where(
                invite.team_id.in_(list(team_ids)),
                invite.state == pending_state,
                self._live_clause(),
            )
        )
        return result.all()

    async def list_for_team(self, session: AsyncSession, team_id: int) -> Sequence[models.RegistrationTeamInvite]:
        invite = models.RegistrationTeamInvite
        result = await session.scalars(
            self.select().where(invite.team_id == team_id).order_by(invite.invited_at.desc())
        )
        return result.all()

    async def get_by_token_hash(self, session: AsyncSession, token_sha256: str) -> models.RegistrationTeamInvite | None:
        """Indexed single read against the partial unique index on the hash.

        The raw token is never compared against anything stored.
        """
        return await session.scalar(self.select().where(models.RegistrationTeamInvite.token_sha256 == token_sha256))

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
        invite = models.RegistrationTeamInvite
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
        invite = models.RegistrationTeamInvite
        await session.execute(
            sa.update(invite)
            .where(invite.team_id == team_id, invite.state == pending_state)
            .values(state=revoked_state)
        )


class GoogleSheetBindingRepository(BaseRepository[models.RegistrationGoogleSheetBinding]):
    """``registration_google_sheet_binding`` — one imported sheet row ↔ one registration."""

    def __init__(self) -> None:
        super().__init__(models.RegistrationGoogleSheetBinding)

    async def list_source_record_keys(self, session: AsyncSession, feed_id: int) -> Sequence[str]:
        binding = models.RegistrationGoogleSheetBinding
        result = await session.scalars(sa.select(binding.source_record_key).where(binding.feed_id == feed_id))
        return result.all()

    async def list_by_feed(
        self,
        session: AsyncSession,
        feed_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.RegistrationGoogleSheetBinding]:
        query = self._apply_options(
            self.select().where(models.RegistrationGoogleSheetBinding.feed_id == feed_id),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()
