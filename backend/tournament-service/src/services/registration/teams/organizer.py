"""Organizer flows over registered teams: reject, unlock, admission, notes and
placement by registration or by game handle.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.social import display_social_handle, normalize_social_handle
from shared.disciplines import DISCIPLINES, identity_provider
from shared.repository import CatalogRoleRepository
from shared.services.realtime import Resource, Scope, emit
from src.schemas.registration_team import RegistrationTeamRejectRequest
from src.services.registration._common import replace_registration_roles
from src.services.registration.teams._core import TeamServiceBase
from src.services.registration.teams._shared import (
    INVITE_PENDING,
    INVITE_REVOKED,
    TEAM_DISBANDED,
    TEAM_REJECTED,
    _apply_occupancy_status,
    _assert_mutable,
    _check_slot,
    _fail,
)

TEAM_ADMISSIONS = frozenset({"pending", "accepted", "waitlisted"})


class OrganizerMixin(TeamServiceBase):
    """Organizer overrides; the caller owns the workspace-permission check."""

    async def reject_team(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        auth_user: models.AuthUser,
        reason: str,
        withdraw_members: bool = False,
    ) -> models.RegistrationTeam:
        """Organizer refuses a team — the counterpart of rejecting a registration.

        ``tournament_id`` is required and asserted, not decorative: the caller's
        permission was checked against *that* tournament's workspace, so accepting a
        ``team_id`` from any other tournament would let an organizer of one event
        reject teams in another.

        Members return to the solo pool by default, preserving registration status.
        Explicit ``withdraw_members=True`` withdraws them instead and retains their
        team link so their own registration can explain the withdrawal.
        """
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            # Deliberately 404, not 403: confirming the team exists elsewhere would
            # leak roster membership across workspaces.
            raise _fail(404, "team_not_found", "Team not found")
        if team.exported_team_id is not None:
            raise _fail(409, "team_already_exported", "This team has already been exported to the tournament")
        if team.status in (TEAM_REJECTED, TEAM_DISBANDED):
            raise _fail(409, "team_not_forming", f"This team is already {team.status}")
        rejection_reason = RegistrationTeamRejectRequest(reason=reason).reason

        members = await self._roster_members(session, team.id)
        tournament = await self.tournament_repo.get(session, team.tournament_id)
        await self._notify_roster(
            session,
            team,
            kind="team.rejected",
            payload={
                "team_id": team.id,
                "team_name": team.name,
                "tournament_id": team.tournament_id,
                "tournament_name": tournament.name if tournament is not None else "",
                "reason": rejection_reason,
            },
            members=members,
        )
        for registration in members:
            if withdraw_members:
                registration.status = "withdrawn"
            else:
                # Returning to the solo pool DOES mean leaving the team, so here the
                # link is cleared. When members are withdrawn it is retained, so their
                # own card can say the team was rejected rather than leaving them with
                # an unexplained withdrawal.
                registration.registration_team_id = None
                registration.team_slot_code = None
                registration.is_substitute = False
        # Revokes EXPIRED pending rows too, unlike ``consume_if_pending`` — see that
        # repository method's docstring.
        await self.invite_repo.revoke_pending_for_team(
            session, team.id, pending_state=INVITE_PENDING, revoked_state=INVITE_REVOKED
        )
        team.status = TEAM_REJECTED
        team.rejection_reason = rejection_reason
        team.deleted_at = datetime.now(UTC)
        team.deleted_by = auth_user.id
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return team

    async def unlock_roster(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> models.RegistrationTeam:
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        _assert_mutable(team)
        team.roster_locked_at = None
        team.roster_locked_by = None
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return team

    async def set_admission(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        admission: str,
        auth_user: models.AuthUser,
    ) -> models.RegistrationTeam:
        if admission not in TEAM_ADMISSIONS:
            raise _fail(400, "admission_invalid", "Admission must be pending, accepted or waitlisted")
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        if team.status in (TEAM_REJECTED, TEAM_DISBANDED):
            raise _fail(409, "team_not_forming", f"This team is already {team.status}")
        team.admission = admission
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return team

    async def set_organizer_notes(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        notes: str | None,
    ) -> models.RegistrationTeam:
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        team.organizer_notes = notes
        await session.commit()
        return team

    async def _lock_teams(self, session: AsyncSession, team_ids: list[int]) -> dict[int, models.RegistrationTeam]:
        locked: dict[int, models.RegistrationTeam] = {}
        for team_id in sorted(set(team_ids)):
            locked[team_id] = await self._lock_team(session, team_id)
        return locked

    async def _place_onto(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        registration: models.Registration,
        slot_code: str,
        is_substitute: bool = False,
    ) -> models.RegistrationTeam:
        if registration.tournament_id != tournament_id:
            raise _fail(404, "registration_not_found", "That registration is not in this tournament")
        if registration.status in ("withdrawn", "rejected"):
            raise _fail(409, "registration_terminal", "This registration is no longer active")

        source_id = registration.registration_team_id
        lock_ids = [team_id] + ([source_id] if source_id and source_id != team_id else [])
        locked = await self._lock_teams(session, lock_ids)
        dest = locked[team_id]
        if dest.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        _assert_mutable(dest)
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, tournament_id)
        occupancy = await self._occupancy(session, dest, shape, max_substitutes=max_substitutes)
        _check_slot(occupancy, slot_code, is_substitute=is_substitute, offering=False)

        if source_id and source_id != dest.id:
            source = locked[source_id]
            _assert_mutable(source)
            if registration.id == source.captain_registration_id:
                raise _fail(409, "cannot_move_captain", "Transfer captaincy before moving the captain to another team")
            registration.is_team_manager = False

        if dest.captain_registration_id == registration.id and is_substitute:
            raise _fail(409, "captain_must_be_starter", "A substitute cannot captain the team")

        registration.registration_team_id = dest.id
        registration.team_slot_code = slot_code
        registration.is_substitute = bool(is_substitute)
        await session.flush()
        dest_occ = await self._occupancy(session, dest, shape, max_substitutes=max_substitutes)
        _apply_occupancy_status(dest, dest_occ)
        if source_id and source_id != dest.id:
            source_occ = await self._occupancy(session, locked[source_id], shape, max_substitutes=max_substitutes)
            _apply_occupancy_status(locked[source_id], source_occ)
        return dest

    async def place_member_as_organizer(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        registration_id: int,
        slot_code: str,
        is_substitute: bool = False,
    ) -> models.RegistrationTeam:
        dest_probe = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if dest_probe is None or dest_probe.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        registration = await self.registration_repo.get(session, registration_id)
        if registration is None:
            raise _fail(404, "registration_not_found", "That registration is not in this tournament")
        dest = await self._place_onto(
            session,
            tournament_id=tournament_id,
            team_id=team_id,
            registration=registration,
            slot_code=slot_code,
            is_substitute=is_substitute,
        )
        tournament = await self.tournament_repo.get(session, tournament_id)
        shape = await self._resolve_shape(session, tournament)
        members = await self._roster_members(session, dest.id)
        await self._raise_if_ineligible(session, dest, members, shape)
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return dest

    async def attach_member_as_organizer(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        handle: str,
        slot_code: str,
        is_substitute: bool = False,
    ) -> models.RegistrationTeam:
        """Place by game handle, creating a shadow registration when none exists.

        Organizer override: eligibility is shown on the team card and still
        blocks export, but it must not refuse the write — a player with no
        Discord/account is exactly who this path exists to add.
        """
        dest_probe = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if dest_probe is None or dest_probe.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        provider = identity_provider(tournament.discipline)
        tag = display_social_handle(provider, handle)
        if not tag:
            raise _fail(400, "handle_required", "A game handle is required")
        key = normalize_social_handle(provider, tag)
        registration = await session.scalar(
            self.registration_repo.select()
            .where(
                models.Registration.tournament_id == tournament_id,
                models.Registration.deleted_at.is_(None),
                models.Registration.identities.any(
                    sa.and_(
                        models.RegistrationIdentity.provider == provider,
                        models.RegistrationIdentity.position == 0,
                        models.RegistrationIdentity.handle_normalized == key,
                    )
                ),
            )
            .options(selectinload(models.Registration.identities))
        )
        if registration is None:
            catalog_roles = await CatalogRoleRepository().rated_rows(
                session, discipline=tournament.discipline, workspace_id=tournament.workspace_id
            )
            role_codes = tuple(role.code for role in DISCIPLINES[tournament.discipline].rated_dimension.roles)
            role = slot_code if slot_code in role_codes else role_codes[0]
            registration = models.Registration(
                tournament_id=tournament_id,
                display_name=tag,
                status="approved",
                balancer_status="not_in_balancer",
            )
            registration.identities.append(
                models.RegistrationIdentity(provider=provider, position=0, handle=tag, handle_normalized=key)
            )
            replace_registration_roles(registration, [{"role": role, "is_primary": True}], catalog_roles=catalog_roles)
            await self.registration_repo.create(session, registration)
            await session.flush()
            await self.registrations.ensure_player_identity(
                session, registration, provider=provider, auth_user_id=None, workspace_id=dest_probe.workspace_id
            )
        dest = await self._place_onto(
            session,
            tournament_id=tournament_id,
            team_id=team_id,
            registration=registration,
            slot_code=slot_code,
            is_substitute=is_substitute,
        )
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            raise _fail(409, "already_registered", "A player with this handle is already registered") from exc
        return dest
