"""Read models: team lists and pages, free agents, staffed teams and the caller's
own targeted invites.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.errors import ApiHTTPException
from shared.disciplines import identity_provider
from shared.domain.team_eligibility import EligibilityIssue
from shared.domain.team_roster import RosterOccupancy
from src.schemas.registration_team import (
    RegistrationFreeAgentRead,
    RegistrationTeamInviteOffer,
    RegistrationTeamMemberRead,
    RegistrationTeamRead,
    serialize_invite,
    serialize_registration_team,
)
from src.services.registration.service import _owned_by
from src.services.registration.teams._core import TeamServiceBase
from src.services.registration.teams._shared import (
    _MUTABLE_TEAM_STATUSES,
    _SLOT_RELEASING_STATUSES,
    INVITE_PENDING,
    TEAM_REJECTED,
    _check_slot,
    _fail,
    _free_agent_clause,
    _occupancy_of,
)
from src.services.registration.windows import is_registration_open


class ReadsMixin(TeamServiceBase):
    """Serialization and listing; no writes."""

    async def count_unassigned_players(self, session: AsyncSession, tournament_id: int) -> int:
        """How many free agents there are.

        These are invisible to the export: it materializes registered teams, and on a
        team-registration tournament neither the balancer nor the draft runs. So an
        approved player nobody invited silently never becomes a ``tournament.player``.
        Surfacing the count is what lets an organizer notice them BEFORE pressing
        export, which is the only moment it is still cheap to fix.
        """
        return await self.registration_repo.count(session, filters=_free_agent_clause(tournament_id))

    async def list_free_agents(self, session: AsyncSession, tournament_id: int) -> list[RegistrationFreeAgentRead]:
        """The free agents a captain may invite, newest registration last.

        This is what makes a targeted invite possible without a global account search:
        the captain picks from people who already registered for THIS tournament, so no
        new identity surface is opened. Everything returned here is already on the
        public participants list — the account requirement on the route exists because
        the only use of this list is to act on it.

        Roles ride along because the captain is filling a specific slot; a list of bare
        names would make them open every profile to find a tank.
        """
        provider = await self._owner_provider(session, tournament_id)
        rows = await session.scalars(
            self.registration_repo.select()
            .where(*_free_agent_clause(tournament_id))
            .options(
                selectinload(models.Registration.roles),
                selectinload(models.Registration.identities),
            )
            .order_by(models.Registration.submitted_at.asc())
        )
        return [
            RegistrationFreeAgentRead(
                registration_id=row.id,
                primary_handle=(
                    identity.handle if (identity := row.primary_game_identity(provider=provider)) else None
                ),
                # Primary first: it is the role they actually want, and the captain
                # scanning for one reads the first chip.
                roles=[entry.role_ref for entry in sorted(row.roles, key=lambda r: not r.is_primary)],
            )
            for row in list(rows)
        ]

    async def list_teams(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        include_terminal: bool = False,
        include_terminal_for_auth_user_id: int | None = None,
    ) -> list[models.RegistrationTeam]:
        """Every registered team, by name — the page :meth:`describe_teams` serializes
        with its live occupancy (the organizer's "who is incomplete, and what are they
        missing?")."""
        conditions = [models.RegistrationTeam.tournament_id == tournament_id]
        if not include_terminal:
            visible = sa.and_(
                models.RegistrationTeam.deleted_at.is_(None),
                models.RegistrationTeam.status.in_(sorted(_MUTABLE_TEAM_STATUSES)),
            )
            if include_terminal_for_auth_user_id is not None:
                # Captain identity survives returning the roster to the solo pool.
                visible = sa.or_(
                    visible,
                    sa.and_(
                        models.RegistrationTeam.status == TEAM_REJECTED,
                        models.RegistrationTeam.captain_registration_id.in_(
                            sa.select(models.Registration.id).where(_owned_by(include_terminal_for_auth_user_id))
                        ),
                    ),
                )
            conditions.append(visible)
        return list(
            await session.scalars(
                self.team_repo.select().where(*conditions).order_by(models.RegistrationTeam.name_normalized)
            )
        )

    async def describe_team(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        *,
        include_invites: bool = False,
        include_staff: bool = False,
        eligibility: list[EligibilityIssue] | None = None,
    ) -> RegistrationTeamRead:
        """Serialize a team with its live occupancy.

        ``include_invites`` is off by default because a public roster must not leak who
        has been asked and declined; only the captain's own view and the organizer's
        pass True. ``eligibility`` is the roster's issues when the calling flow just
        evaluated them under its lock, so they are not evaluated (and Discord asked)
        twice.
        """
        (read,) = await self.describe_teams(
            session,
            [team],
            private_team_ids={team.id} if include_invites else (),
            include_staff=include_staff,
            eligibility={team.id: eligibility} if eligibility is not None else None,
        )
        return read

    async def describe_teams(
        self,
        session: AsyncSession,
        teams: Sequence[models.RegistrationTeam],
        *,
        private_team_ids: Collection[int],
        include_staff: bool = False,
        eligibility: Mapping[int, list[EligibilityIssue]] | None = None,
    ) -> list[RegistrationTeamRead]:
        """:meth:`describe_team` for a page of ONE tournament's teams.

        The tournament, shape and bench size are read once, members and live invites
        with one ``IN (…)`` each, and eligibility (with its one Discord batch) once for
        every team that needs it — not a dozen statements and a Discord call per team.
        ``private_team_ids`` are the teams whose invites and eligibility this reader
        may see (``include_invites``).
        """
        from shared.domain.team_subscription import team_subscription_is_current
        from src.core.clients import discord_client
        from src.schemas.registration_team import TeamEligibilityIssueRead
        from src.services.registration.team_eligibility import team_eligibility

        if not teams:
            return []
        tournament = await self.tournament_repo.get(session, teams[0].tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        provider = identity_provider(tournament.discipline)
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, tournament.id)
        team_ids = [team.id for team in teams]

        rosters: dict[int, list[models.Registration]] = {team_id: [] for team_id in team_ids}
        for registration in await session.scalars(
            self.registration_repo.select()
            .where(
                models.Registration.registration_team_id.in_(team_ids),
                models.Registration.deleted_at.is_(None),
                models.Registration.status.notin_(_SLOT_RELEASING_STATUSES),
            )
            .options(selectinload(models.Registration.identities))
        ):
            rosters[registration.registration_team_id].append(registration)
        pending: dict[int, list[models.RegistrationTeamInvite]] = {team_id: [] for team_id in team_ids}
        for invite in await self.invite_repo.list_pending_for_teams(session, team_ids, pending_state=INVITE_PENDING):
            pending[invite.team_id].append(invite)

        private = [team for team in teams if team.id in private_team_ids]
        tags = await self._handles_by_account(
            session,
            tournament_id=tournament.id,
            provider=provider,
            auth_user_ids={
                invite.target_auth_user_id
                for team in private
                for invite in pending[team.id]
                if invite.target_auth_user_id is not None
            },
        )
        issues = dict(eligibility or {})
        unevaluated = [team for team in private if team.id not in issues]
        if unevaluated:
            form = await session.scalar(
                sa.select(models.RegistrationForm).where(models.RegistrationForm.tournament_id == tournament.id)
            )
            workspace = await session.scalar(
                sa.select(models.Workspace).where(models.Workspace.id == tournament.workspace_id)
            )
            issues.update(
                await team_eligibility.evaluate_many(
                    session,
                    [(team, rosters[team.id]) for team in unevaluated],
                    form=form,
                    shape=shape,
                    workspace=workspace,
                    discord=discord_client(),
                )
            )

        reads = []
        for team in teams:
            roster = rosters[team.id]
            is_private = team.id in private_team_ids
            reads.append(
                serialize_registration_team(
                    team,
                    _occupancy_of(shape, roster, pending[team.id], max_substitutes=max_substitutes),
                    members=[
                        RegistrationTeamMemberRead(
                            registration_id=registration.id,
                            display_name=registration.display_name,
                            primary_handle=(
                                identity.handle
                                if (identity := registration.primary_game_identity(provider=provider))
                                else None
                            ),
                            slot_code=registration.team_slot_code,
                            is_substitute=bool(registration.is_substitute),
                            is_captain=registration.id == team.captain_registration_id,
                            is_manager=bool(registration.is_team_manager),
                            checked_in=bool(registration.checked_in),
                            status=registration.status,
                        )
                        for registration in roster
                    ],
                    invites=[
                        serialize_invite(invite, target_handle=tags.get(invite.target_auth_user_id))
                        for invite in pending[team.id]
                    ]
                    if is_private
                    else [],
                    include_staff=include_staff,
                    include_private=is_private,
                    eligibility_issues=[
                        TeamEligibilityIssueRead(
                            code=issue.code, registration_id=issue.registration_id, blocking=issue.blocking
                        )
                        for issue in issues.get(team.id, [])
                    ]
                    if is_private
                    else [],
                    subscription_covered=team_subscription_is_current(team),
                )
            )
        return reads

    async def staffed_team_ids(
        self, session: AsyncSession, teams: Sequence[models.RegistrationTeam], auth_user_id: int
    ) -> set[int]:
        """Which of one tournament's ``teams`` this account captains or manages.

        :meth:`is_team_staff` for a whole page, in one query: the account's
        registrations in the tournament decide both (captaincy by id, management by
        the live, flagged member row).
        """
        if not teams:
            return set()
        rows = (
            await session.execute(
                sa.select(
                    models.Registration.id,
                    models.Registration.registration_team_id,
                    models.Registration.is_team_manager,
                    models.Registration.deleted_at,
                    models.Registration.status,
                ).where(
                    models.Registration.tournament_id == teams[0].tournament_id,
                    _owned_by(auth_user_id),
                )
            )
        ).all()
        own = {row.id for row in rows}
        managed = {
            row.registration_team_id
            for row in rows
            if row.is_team_manager and row.deleted_at is None and row.status not in _SLOT_RELEASING_STATUSES
        }
        return {team.id for team in teams if team.captain_registration_id in own or team.id in managed}

    async def list_my_invites(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> list[RegistrationTeamInviteOffer]:
        """Targeted invites addressed to the caller in this tournament.

        Targeted invites carry no token, so this read is the ONLY way their recipient
        can learn one exists; without it the mode would be strictly worse than a link.

        Link invites are excluded because they have no addressee; a bearer credential
        is not "yours" until you hold it, and listing them here would hand every
        outstanding link to whoever asked.

        Expired rows are filtered rather than shown greyed out: an offer the accept
        guard would refuse is not an offer, and the recipient has no action for it.
        """
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None or not is_registration_open(tournament):
            return []
        # Only structurally available offers; acceptance still rechecks under lock.
        rows = await session.scalars(
            self.invite_repo.select()
            .join(
                models.RegistrationTeam,
                models.RegistrationTeam.id == models.RegistrationTeamInvite.team_id,
            )
            .where(
                models.RegistrationTeam.tournament_id == tournament_id,
                models.RegistrationTeam.deleted_at.is_(None),
                models.RegistrationTeam.status.in_(sorted(_MUTABLE_TEAM_STATUSES)),
                models.RegistrationTeam.exported_team_id.is_(None),
                models.RegistrationTeam.roster_locked_at.is_(None),
                ~sa.exists(
                    sa.select(models.Registration.id).where(
                        models.Registration.tournament_id == tournament_id,
                        models.Registration.deleted_at.is_(None),
                        models.Registration.status.in_(sorted(_SLOT_RELEASING_STATUSES)),
                        _owned_by(auth_user.id),
                    )
                ),
                models.RegistrationTeamInvite.target_auth_user_id == auth_user.id,
                models.RegistrationTeamInvite.state == INVITE_PENDING,
                sa.or_(
                    models.RegistrationTeamInvite.expires_at.is_(None),
                    models.RegistrationTeamInvite.expires_at > datetime.now(UTC),
                ),
            )
            .options(selectinload(models.RegistrationTeamInvite.team))
            .order_by(models.RegistrationTeamInvite.invited_at.asc())
        )
        invites = list(rows)
        if not invites:
            return []
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, tournament_id)
        occupancies: dict[int, RosterOccupancy] = {}
        offers = []
        for invite in invites:
            if invite.team_id not in occupancies:
                occupancies[invite.team_id] = await self._occupancy(
                    session, invite.team, shape, max_substitutes=max_substitutes
                )
            try:
                _check_slot(
                    occupancies[invite.team_id],
                    invite.slot_code,
                    is_substitute=bool(invite.is_substitute),
                    offering=False,
                )
            except ApiHTTPException:
                continue
            offers.append(
                RegistrationTeamInviteOffer(
                    invite_id=invite.id,
                    team_id=invite.team_id,
                    team_name=invite.team.name,
                    slot_code=invite.slot_code,
                    is_substitute=bool(invite.is_substitute),
                    expires_at=invite.expires_at,
                )
            )
        return offers
