"""The base every team-flow mixin extends: repositories, row locks, roster loading
and the captain/staff gates.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.disciplines import identity_provider
from shared.domain.roster_shape import RosterShape
from shared.domain.team_roster import RosterMember, RosterOccupancy
from shared.repository import (
    RegistrationRepository,
    RegistrationTeamInviteRepository,
    RegistrationTeamRepository,
    TournamentRepository,
)
from shared.services.notifications import notify
from shared.services.team_format import tournament_slot_shape
from src.core.clients import discord_client
from src.services.registration.service import RegistrationService, _owned_by, registration_service
from src.services.registration.team_eligibility import team_eligibility
from src.services.registration.teams._shared import (
    _SLOT_RELEASING_STATUSES,
    INVITE_PENDING,
    _assert_mutable,
    _assert_unlocked,
    _fail,
    _occupancy_of,
)
from src.services.registration.windows import is_registration_open


async def _form(session: AsyncSession, tournament_id: int) -> models.RegistrationForm | None:
    return await session.scalar(
        sa.select(models.RegistrationForm).where(models.RegistrationForm.tournament_id == tournament_id)
    )


async def _workspace(session: AsyncSession, workspace_id: int) -> models.Workspace | None:
    return await session.scalar(sa.select(models.Workspace).where(models.Workspace.id == workspace_id))


async def _member_auth_user_id(session: AsyncSession, registration_id: int) -> int | None:
    return await session.scalar(
        sa.select(models.User.auth_user_id)
        .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
        .join(
            models.Registration,
            models.Registration.workspace_member_id == models.WorkspaceMember.id,
        )
        .where(models.Registration.id == registration_id)
    )


class TeamServiceBase:
    """Repositories, row locks, roster loading and the staff gates every team flow builds on."""

    def __init__(
        self,
        *,
        team_repo: RegistrationTeamRepository = RegistrationTeamRepository(),
        invite_repo: RegistrationTeamInviteRepository = RegistrationTeamInviteRepository(),
        registration_repo: RegistrationRepository = RegistrationRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        registrations: RegistrationService = registration_service,
    ) -> None:
        self.team_repo = team_repo
        self.invite_repo = invite_repo
        self.registration_repo = registration_repo
        self.tournament_repo = tournament_repo
        self.registrations = registrations

    # ── loading ──────────────────────────────────────────────────────────────

    async def _lock_team(self, session: AsyncSession, team_id: int) -> models.RegistrationTeam:
        """Load a team holding its row lock, or reject.

        The lock is the serialization point for every roster decision below; taking it
        before reading occupancy is what stops two acceptances from overfilling one
        slot.
        """
        team = await self.team_repo.get_active_for_update(session, team_id)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        return team

    async def _assert_registration_open(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        if not is_registration_open(tournament):
            raise _fail(400, "registration_closed", "Registration is not open for this tournament")
        return tournament

    async def _resolve_shape(self, session: AsyncSession, tournament: models.Tournament) -> RosterShape:
        """The slots projected from the tournament's own team format."""
        return await tournament_slot_shape(session, tournament.id)

    async def _max_substitutes(self, session: AsyncSession, tournament_id: int) -> int:
        # Single-column scalar projection off the form, not a row fetch.
        return (
            await session.scalar(
                sa.select(models.RegistrationForm.max_substitutes).where(
                    models.RegistrationForm.tournament_id == tournament_id
                )
            )
            or 0
        )

    async def _roster_members(
        self, session: AsyncSession, team_id: int, *, fresh: bool = False
    ) -> list[models.Registration]:
        """The team's live members.

        ``fresh`` re-reads rows this session already holds (``populate_existing``):
        for a flow that read the roster before taking the team lock, what another
        transaction committed in between must win over the identity map.
        """
        result = await session.scalars(
            self.registration_repo.select()
            .where(
                models.Registration.registration_team_id == team_id,
                models.Registration.deleted_at.is_(None),
                models.Registration.status.notin_(_SLOT_RELEASING_STATUSES),
            )
            # The team eligibility rules read each member's Discord handle off
            # the identity rows, never lazy-loadable in async code.
            .options(selectinload(models.Registration.identities))
            .execution_options(populate_existing=fresh)
        )
        return list(result)

    async def _has_registration(self, session: AsyncSession, tournament_id: int, auth_user_id: int) -> bool:
        """Does the account hold a live registration here? One indexed id probe."""
        return (
            await session.scalar(
                sa.select(models.Registration.id)
                .where(
                    models.Registration.tournament_id == tournament_id,
                    models.Registration.deleted_at.is_(None),
                    _owned_by(auth_user_id),
                )
                .limit(1)
            )
            is not None
        )

    async def _own_registration(
        self, session: AsyncSession, tournament_id: int, auth_user_id: int
    ) -> models.Registration | None:
        """The account's live registration with only what an accept reads.

        ``populate_existing``: read under the team lock, so a status another
        transaction just wrote must win over a copy already in the identity map.
        """
        return await session.scalar(
            self.registration_repo.select()
            .where(
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
                _owned_by(auth_user_id),
            )
            .options(selectinload(models.Registration.identities))
            .execution_options(populate_existing=True)
        )

    async def _pending_invites(self, session: AsyncSession, team_id: int) -> list[models.RegistrationTeamInvite]:
        """Live invites only: an expired one reserves nothing, so its slot is
        offerable again without an explicit revoke."""
        return list(await self.invite_repo.list_pending(session, team_id, pending_state=INVITE_PENDING))

    async def _occupancy(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        shape: RosterShape,
        *,
        max_substitutes: int,
        extra: RosterMember | None = None,
    ) -> RosterOccupancy:
        """Current slot occupancy, optionally including one not-yet-written member.

        ``extra`` is how a flow projects the roster *after* the write it is about to
        make, so the team's denormalized ``status`` can be set under the same lock
        rather than in a follow-up transaction where it could drift.
        """
        return _occupancy_of(
            shape,
            await self._roster_members(session, team.id),
            await self._pending_invites(session, team.id),
            max_substitutes=max_substitutes,
            extra=extra,
        )

    # ── gates and shared side effects ─────────────────────────────────────────

    async def is_team_captain(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        auth_user_id: int,
    ) -> bool:
        """Does this account captain this team?

        A team whose ``captain_registration_id`` is NULL is structurally broken (the
        captain's registration was hard-deleted) — never true for that team.
        """
        if team.captain_registration_id is None:
            return False
        is_captain = await session.scalar(
            sa.select(models.Registration.id).where(
                models.Registration.id == team.captain_registration_id,
                _owned_by(auth_user_id),
            )
        )
        return is_captain is not None

    async def _assert_captain(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        """Only the captain edits a roster."""
        if team.captain_registration_id is None:
            raise _fail(409, "team_has_no_captain", "This team has no captain and must be handled by an organizer")
        if not await self.is_team_captain(session, team, auth_user.id):
            raise _fail(403, "not_captain", "Only the team captain can do this")

    async def is_team_staff(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        auth_user_id: int,
    ) -> bool:
        if await self.is_team_captain(session, team, auth_user_id):
            return True
        found = await session.scalar(
            sa.select(models.Registration.id).where(
                models.Registration.registration_team_id == team.id,
                models.Registration.is_team_manager.is_(True),
                models.Registration.deleted_at.is_(None),
                models.Registration.status.notin_(("withdrawn", "rejected")),
                _owned_by(auth_user_id),
            )
        )
        return found is not None

    async def _assert_staff(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        if team.captain_registration_id is None:
            raise _fail(409, "team_has_no_captain", "This team has no captain and must be handled by an organizer")
        if not await self.is_team_staff(session, team, auth_user.id):
            raise _fail(403, "not_captain", "Only the team captain or a manager can do this")

    async def _assert_staff_editable(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        await self._assert_staff(session, team, auth_user)
        _assert_mutable(team)
        _assert_unlocked(team)

    async def assert_staff_of_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> models.RegistrationTeam:
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await self._assert_staff(session, team, auth_user)
        return team

    async def _notify_roster(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        *,
        kind: str,
        payload: dict[str, Any],
        skip_registration_id: int | None = None,
        members: list[models.Registration] | None = None,
    ) -> None:
        # Callers that have already withdrawn or unlinked the roster must pass
        # the members they loaded *before* that write: `_roster_members`
        # hides withdrawn rows, so a second query would notify nobody.
        roster = members if members is not None else await self._roster_members(session, team.id)
        for registration in roster:
            if skip_registration_id is not None and registration.id == skip_registration_id:
                continue
            auth_user_id = await _member_auth_user_id(session, registration.id)
            if auth_user_id is None:
                continue
            await notify(
                session,
                kind=kind,
                recipient_auth_user_id=int(auth_user_id),
                source_workspace_id=team.workspace_id,
                payload=payload,
            )

    async def _raise_if_ineligible(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        members: list[models.Registration],
        shape: Any,
    ) -> list[Any]:
        """Refuse a roster that breaks a blocking team rule; otherwise return every issue found.

        The issues come back so the flow's own team read can reuse them instead of
        evaluating (and asking Discord) a second time.
        """
        form = await _form(session, team.tournament_id)
        workspace = await _workspace(session, team.workspace_id)
        issues = await team_eligibility.evaluate(
            session,
            team,
            members,
            form=form,
            shape=shape,
            workspace=workspace,
            discord=discord_client(),
        )
        blocking = [issue for issue in issues if issue.blocking]
        if not blocking:
            return issues
        issue = blocking[0]
        raise _fail(409, issue.code, f"This roster is not eligible ({issue.code})")

    async def _owner_provider(self, session: AsyncSession, tournament_id: int) -> str:
        """The tournament's identity provider: the one game whose handle names its players."""
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        return identity_provider(tournament.discipline)

    async def _handles_by_account(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        provider: str,
        auth_user_ids: set[int],
    ) -> dict[int, str]:
        """Primary game handles for the accounts a team's pending invites address.

        One query for every invite on the team rather than one per invite: the
        organizer's page describes every team at once, so a per-invite lookup would be
        an N+1 that grows with the field.

        Read from the addressee's registration in THIS tournament, not from their
        profile: the handle they entered on the form is the one the captain picked
        them by, and a profile rename must not make a pending offer unrecognisable.
        """
        if not auth_user_ids:
            return {}
        # Analytical: a two-column projection across a member -> player join.
        rows = await session.execute(
            sa.select(models.User.auth_user_id, models.RegistrationIdentity.handle)
            # Neither projected column is the left side: name the registration
            # explicitly, or the first join has two candidate FROMs to start from.
            .select_from(models.Registration)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Registration.workspace_member_id,
            )
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .join(
                models.RegistrationIdentity,
                models.RegistrationIdentity.registration_id == models.Registration.id,
            )
            .where(
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
                models.RegistrationIdentity.provider == provider,
                models.RegistrationIdentity.position == 0,
                models.User.auth_user_id.in_(sorted(auth_user_ids)),
            )
        )
        return dict(rows.all())
