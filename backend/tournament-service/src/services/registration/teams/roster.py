"""Roster membership edits by the team's staff and members: place, manager flag,
kick and leave.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.roster_shape import RosterShape
from shared.domain.team_roster import RosterMember, RosterOccupancy
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from src.services.registration.service import _owned_by
from src.services.registration.teams._core import TeamServiceBase
from src.services.registration.teams._shared import (
    _apply_occupancy_status,
    _assert_mutable,
    _assert_unlocked,
    _check_slot,
    _fail,
)


class RosterMixin(TeamServiceBase):
    """Who sits in which slot, and who leaves."""

    async def place_member(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        registration_id: int,
        auth_user: models.AuthUser,
        slot_code: str,
        is_substitute: bool = False,
        swap_with_registration_id: int | None = None,
    ) -> models.RegistrationTeam:
        team = await self._lock_team(session, team_id)
        await self._assert_staff_editable(session, team, auth_user)
        tournament = await self.tournament_repo.get(session, team.tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, team.tournament_id)
        members = await self._roster_members(session, team.id)
        target = next((m for m in members if m.id == registration_id), None)
        if target is None:
            raise _fail(404, "member_not_found", "This player is not on the team")
        if target.id == team.captain_registration_id and is_substitute:
            raise _fail(409, "captain_must_be_starter", "A substitute cannot captain the team")

        if swap_with_registration_id is not None:
            other = next((m for m in members if m.id == swap_with_registration_id), None)
            if other is None:
                raise _fail(404, "member_not_found", "This player is not on the team")
            if other.id == team.captain_registration_id and target.is_substitute:
                raise _fail(409, "captain_must_be_starter", "A substitute cannot captain the team")
            other_slot, other_sub = target.team_slot_code, bool(target.is_substitute)
            target.team_slot_code = other.team_slot_code
            target.is_substitute = bool(other.is_substitute)
            other.team_slot_code = other_slot
            other.is_substitute = other_sub
        else:
            occupancy = await self._occupancy(
                session,
                team,
                shape,
                max_substitutes=max_substitutes,
            )
            # Occupancy currently includes this member. Pretend they have left
            # so the destination slot is tested as it will be after the move.
            remaining = [
                RosterMember(slot_code=m.team_slot_code or "", is_substitute=bool(m.is_substitute))
                for m in members
                if m.id != target.id and m.team_slot_code
            ]
            projected = RosterOccupancy(
                shape=shape,
                accepted=tuple(remaining),
                pending=tuple(
                    RosterMember(slot_code=i.slot_code, is_substitute=bool(i.is_substitute))
                    for i in await self._pending_invites(session, team.id)
                ),
                max_substitutes=max_substitutes,
            )
            _check_slot(projected, slot_code, is_substitute=is_substitute, offering=False)
            target.team_slot_code = slot_code
            target.is_substitute = bool(is_substitute)

        await session.flush()
        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)
        _apply_occupancy_status(team, occupancy)
        await self._raise_if_ineligible(session, team, await self._roster_members(session, team.id), shape)
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return team

    async def set_member_manager(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        registration_id: int,
        auth_user: models.AuthUser,
        is_manager: bool,
    ) -> models.RegistrationTeam:
        team = await self._lock_team(session, team_id)
        await self._assert_captain(session, team, auth_user)
        _assert_mutable(team)
        _assert_unlocked(team)
        if registration_id == team.captain_registration_id:
            raise _fail(409, "captain_is_not_manager", "The captain is not a manager; they already command the roster")
        registration = await self.registration_repo.get(session, registration_id)
        if registration is None or registration.registration_team_id != team.id:
            raise _fail(404, "member_not_found", "This player is not on the team")
        registration.is_team_manager = bool(is_manager)
        await session.commit()
        return team

    async def _release_member(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
        registration: models.Registration,
        shape: RosterShape,
        *,
        max_substitutes: int,
    ) -> None:
        """Detach a member from the roster and recompute the team's status.

        The registration itself is *withdrawn*, not deleted: it is a real person's
        real entry, and the admin registration table plus the audit trail both expect
        it to survive. Clearing the three team columns is what frees the slot.
        """
        registration.status = "withdrawn"
        registration.registration_team_id = None
        registration.team_slot_code = None
        registration.is_substitute = False
        await session.flush()
        _apply_occupancy_status(team, await self._occupancy(session, team, shape, max_substitutes=max_substitutes))
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )

    async def kick_member(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        registration_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Captain removes an accepted member; the vacated slot returns to open."""
        team = await self._lock_team(session, team_id)
        await self._assert_staff_editable(session, team, auth_user)
        tournament = await self._assert_registration_open(session, team.tournament_id)

        if registration_id == team.captain_registration_id:
            raise _fail(409, "cannot_kick_captain", "A captain cannot remove themselves; transfer or disband instead")
        registration = await self.registration_repo.get(session, registration_id)
        if registration is None or registration.registration_team_id != team.id:
            raise _fail(404, "member_not_found", "This player is not on the team")

        kicked_auth_user_id = await session.scalar(
            sa.select(models.User.auth_user_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
            .join(
                models.Registration,
                models.Registration.workspace_member_id == models.WorkspaceMember.id,
            )
            .where(models.Registration.id == registration.id)
        )
        shape = await self._resolve_shape(session, tournament)
        await self._release_member(
            session,
            team,
            registration,
            shape,
            max_substitutes=await self._max_substitutes(session, team.tournament_id),
        )
        if kicked_auth_user_id is not None:
            await notify(
                session,
                kind="team.kicked",
                recipient_auth_user_id=int(kicked_auth_user_id),
                source_workspace_id=team.workspace_id,
                actor_auth_user_id=auth_user.id,
                payload={
                    "team_id": team.id,
                    "team_name": team.name,
                    "tournament_id": team.tournament_id,
                    "tournament_name": tournament.name,
                },
            )
        await session.commit()

    async def leave_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """A member withdraws themselves. Symmetric with :meth:`kick_member`, but a
        captain must transfer or disband, never silently vanish from a team other
        people have already joined."""
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        _assert_unlocked(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)

        registration = await session.scalar(
            self.registration_repo.select().where(
                models.Registration.registration_team_id == team.id,
                _owned_by(auth_user.id),
            )
        )
        if registration is None:
            raise _fail(404, "member_not_found", "You are not on this team")
        if registration.id == team.captain_registration_id:
            raise _fail(409, "captain_must_transfer", "Transfer captaincy or disband the team instead")

        shape = await self._resolve_shape(session, tournament)
        await self._release_member(
            session,
            team,
            registration,
            shape,
            max_substitutes=await self._max_substitutes(session, team.tournament_id),
        )
        await session.commit()
