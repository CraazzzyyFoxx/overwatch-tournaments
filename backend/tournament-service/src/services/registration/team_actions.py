"""Roster, admission, lock, check-in and team-subscription writes.

Installed onto :class:`RegistrationTeamService` at import time so the original
module stays the occupancy/invite core and these flows can share its lock
helpers without a circular import at definition time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.team_roster import RosterMember
from shared.domain.team_subscription import SUBSCRIPTION_SCOPE_TEAM, team_subscription_is_current
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from src.core.config import settings
from src.services.registration.subscription_codes import redeem_challenge_code
from src.services.registration.team_eligibility import evaluate_team_eligibility
from src.services.registration.windows import is_check_in_window_active

__all__ = ("install_team_actions",)


def install_team_actions(cls: type) -> None:
    from shared.services.subscriptions import SubscriptionState
    from shared.services.subscriptions.wiring import build_store
    from src.services.registration.teams import (
        DEFAULT_INVITE_TTL,
        INVITE_PENDING,
        TEAM_COMPLETE,
        TEAM_DISBANDED,
        TEAM_REJECTED,
        _assert_mutable,
        _check_slot,
        _fail,
        _owned_by,
        _status_for,
    )

    TEAM_ADMISSIONS = frozenset({"pending", "accepted", "waitlisted"})

    def _apply_occupancy_status(team: models.BalancerRegistrationTeam, occupancy: Any) -> None:
        from src.services.registration.teams import _MUTABLE_TEAM_STATUSES

        if team.status in _MUTABLE_TEAM_STATUSES:
            team.status = _status_for(occupancy)

    def _cleaned_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise _fail(400, "team_name_required", "A team needs a name")
        if "#" in cleaned:
            raise _fail(400, "team_name_invalid", 'A team name cannot contain "#"')
        return cleaned

    def _assert_unlocked(team: models.BalancerRegistrationTeam) -> None:
        if team.roster_locked_at is not None:
            raise _fail(409, "roster_locked", "This team's roster is locked")

    async def _form(self, session: AsyncSession, tournament_id: int) -> models.BalancerRegistrationForm | None:
        return await session.scalar(
            sa.select(models.BalancerRegistrationForm).where(
                models.BalancerRegistrationForm.tournament_id == tournament_id
            )
        )

    async def _workspace(self, session: AsyncSession, workspace_id: int) -> models.Workspace | None:
        return await session.scalar(sa.select(models.Workspace).where(models.Workspace.id == workspace_id))

    async def _member_auth_user_id(self, session: AsyncSession, registration_id: int) -> int | None:
        return await session.scalar(
            sa.select(models.User.auth_user_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
            .join(
                models.BalancerRegistration,
                models.BalancerRegistration.workspace_member_id == models.WorkspaceMember.id,
            )
            .where(models.BalancerRegistration.id == registration_id)
        )

    async def _notify_roster(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        *,
        kind: str,
        payload: dict[str, Any],
        skip_registration_id: int | None = None,
        members: list[models.BalancerRegistration] | None = None,
    ) -> None:
        # Callers that have already withdrawn or unlinked the roster must pass
        # the members they loaded *before* that write: `_roster_members`
        # hides withdrawn rows, so a second query would notify nobody.
        roster = members if members is not None else await self._roster_members(session, team.id)
        for registration in roster:
            if skip_registration_id is not None and registration.id == skip_registration_id:
                continue
            auth_user_id = await _member_auth_user_id(self, session, registration.id)
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
        team: models.BalancerRegistrationTeam,
        members: list[models.BalancerRegistration],
        shape: Any,
    ) -> None:
        form = await _form(self, session, team.tournament_id)
        workspace = await _workspace(self, session, team.workspace_id)
        issues = await evaluate_team_eligibility(
            session,
            team,
            members,
            form=form,
            shape=shape,
            workspace=workspace,
            bot_token=settings.discord_token,
        )
        blocking = [issue for issue in issues if issue.blocking]
        if not blocking:
            return
        issue = blocking[0]
        raise _fail(409, issue.code, f"This roster is not eligible ({issue.code})")

    async def is_team_staff(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        auth_user_id: int,
    ) -> bool:
        if await self.is_team_captain(session, team, auth_user_id):
            return True
        found = await session.scalar(
            sa.select(models.BalancerRegistration.id).where(
                models.BalancerRegistration.registration_team_id == team.id,
                models.BalancerRegistration.is_team_manager.is_(True),
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.status.notin_(("withdrawn", "rejected")),
                _owned_by(auth_user_id),
            )
        )
        return found is not None

    async def _assert_staff(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        if team.captain_registration_id is None:
            raise _fail(409, "team_has_no_captain", "This team has no captain and must be handled by an organizer")
        if not await is_team_staff(self, session, team, auth_user.id):
            raise _fail(403, "not_captain", "Only the team captain or a manager can do this")

    async def _assert_staff_editable(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        await _assert_staff(self, session, team, auth_user)
        _assert_mutable(team)
        _assert_unlocked(team)

    async def assert_staff_of_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> models.BalancerRegistrationTeam:
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await _assert_staff(self, session, team, auth_user)
        return team

    async def _lock_teams(
        self, session: AsyncSession, team_ids: list[int]
    ) -> dict[int, models.BalancerRegistrationTeam]:
        locked: dict[int, models.BalancerRegistrationTeam] = {}
        for team_id in sorted(set(team_ids)):
            locked[team_id] = await self._lock_team(session, team_id)
        return locked

    async def rename_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        name: str,
        as_organizer: bool = False,
        tournament_id: int | None = None,
    ) -> models.BalancerRegistrationTeam:
        team = await self._lock_team(session, team_id)
        if as_organizer:
            # The organizer's permission was checked against ``tournament_id``;
            # accepting any other team's id would rename across events.
            if tournament_id is None or team.tournament_id != tournament_id:
                raise _fail(404, "team_not_found", "Team not found")
            _assert_mutable(team)
        else:
            await _assert_staff_editable(self, session, team, auth_user)
        team.name = _cleaned_name(name)
        team.name_normalized = team.name.lower()
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            raise _fail(409, "team_name_taken", "A team with this name is already registered") from exc
        return team

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
    ) -> models.BalancerRegistrationTeam:
        team = await self._lock_team(session, team_id)
        await _assert_staff_editable(self, session, team, auth_user)
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
            from shared.domain.team_roster import RosterOccupancy

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
        await _raise_if_ineligible(self, session, team, await self._roster_members(session, team.id), shape)
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
    ) -> models.BalancerRegistrationTeam:
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

    async def extend_invite(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        invite_id: int,
        auth_user: models.AuthUser,
        ttl: timedelta | None = None,
        rotate_token: bool = False,
    ) -> tuple[models.BalancerRegistrationTeamInvite, str | None]:
        team = await self._lock_team(session, team_id)
        await _assert_staff_editable(self, session, team, auth_user)
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None or invite.team_id != team.id:
            raise _fail(404, "invite_not_found", "Invite not found")
        if invite.state != INVITE_PENDING:
            from src.services.registration.teams import _diagnose_dead_invite

            raise _diagnose_dead_invite(invite)
        invite.expires_at = datetime.now(UTC) + (ttl or DEFAULT_INVITE_TTL)
        raw_token: str | None = None
        if rotate_token:
            if invite.token_sha256 is None:
                raise _fail(409, "invite_not_a_link", "Only a link invite can rotate its token")
            from shared.domain.invite_token import generate_invite_token

            raw_token, token_hash = generate_invite_token()
            invite.token_sha256 = token_hash
        await session.commit()
        return invite, raw_token

    async def lock_roster(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> models.BalancerRegistrationTeam:
        team = await self._lock_team(session, team_id)
        await self._assert_captain(session, team, auth_user)
        _assert_mutable(team)
        if team.status != TEAM_COMPLETE:
            raise _fail(409, "team_not_complete", "A roster can only be locked when it is complete")
        team.roster_locked_at = datetime.now(UTC)
        team.roster_locked_by = auth_user.id
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
    ) -> models.BalancerRegistrationTeam:
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

    async def check_in_roster(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        exclude_registration_ids: list[int] | None = None,
    ) -> models.BalancerRegistrationTeam:
        from shared.services.admission import AdmissionStage
        from src.services.registration.admission import assert_admitted_at

        team = await self._lock_team(session, team_id)
        await _assert_staff(self, session, team, auth_user)
        tournament = await self.tournament_repo.get(session, team.tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        if not is_check_in_window_active(tournament):
            raise _fail(409, "check_in_closed", "Check-in is not active for this tournament")
        excluded = set(exclude_registration_ids or [])
        now = datetime.now(UTC)
        for registration in await self._roster_members(session, team.id):
            if registration.id in excluded or registration.checked_in:
                continue
            if registration.status != "approved":
                raise _fail(409, "member_not_approved", "Every member must be approved before team check-in")
            registration.tournament = tournament
            registration.registration_team = team
            member_auth_user_id = await _member_auth_user_id(self, session, registration.id)
            if member_auth_user_id is None:
                raise _fail(409, "player_has_no_account", "This player has no account to check in")
            await assert_admitted_at(
                session,
                registration,
                tournament_id=team.tournament_id,
                auth_user_id=member_auth_user_id,
                stage=AdmissionStage.check_in,
            )
            registration.checked_in = True
            registration.checked_in_at = now
            registration.checked_in_by = auth_user.id
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return team

    async def cover_team_subscription(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        code: str | None = None,
        provider: str = "boosty",
    ) -> models.BalancerRegistrationTeam:
        team = await self._lock_team(session, team_id)
        await _assert_staff(self, session, team, auth_user)
        form = await _form(self, session, team.tournament_id)
        if form is None or (form.subscription_scope or "player") != SUBSCRIPTION_SCOPE_TEAM:
            raise _fail(409, "subscription_not_team_scoped", "This tournament does not use team subscription")
        store = build_store(session)
        now = datetime.now(UTC)
        if code:
            verdict = await redeem_challenge_code(
                store=store,
                workspace_id=team.workspace_id,
                auth_user_id=auth_user.id,
                provider=provider,
                submitted_code=code,
            )
        else:
            entitlements = await store.load_entitlements(team.workspace_id, [auth_user.id], [provider])
            stored = entitlements.get((auth_user.id, provider))
            if stored is None:
                raise _fail(409, "subscription_not_active", "No active subscription to attach to this team")
            verdict = stored.to_verdict()
        if verdict.state != SubscriptionState.ACTIVE:
            raise _fail(409, "subscription_not_active", "No active subscription to attach to this team")
        team.subscription_covered_at = now
        team.subscription_covered_by = auth_user.id
        team.subscription_provider = provider
        team.subscription_tier_rank = verdict.tier_rank
        team.subscription_expires_at = verdict.expires_at
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
    ) -> models.BalancerRegistrationTeam:
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
    ) -> models.BalancerRegistrationTeam:
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        team.organizer_notes = notes
        await session.commit()
        return team

    async def place_member_as_organizer(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        registration_id: int,
        slot_code: str,
        is_substitute: bool = False,
    ) -> models.BalancerRegistrationTeam:
        dest_probe = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if dest_probe is None or dest_probe.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        registration = await self.registration_repo.get(session, registration_id)
        if registration is None or registration.tournament_id != tournament_id:
            raise _fail(404, "registration_not_found", "That registration is not in this tournament")
        if registration.status in ("withdrawn", "rejected"):
            raise _fail(409, "registration_terminal", "This registration is no longer active")

        source_id = registration.registration_team_id
        lock_ids = [team_id] + ([source_id] if source_id and source_id != team_id else [])
        locked = await _lock_teams(self, session, lock_ids)
        dest = locked[team_id]
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
        members = await self._roster_members(session, dest.id)
        await _raise_if_ineligible(self, session, dest, members, shape)
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return dest

    async def _maybe_cover_from_personal(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        """Stamp team coverage from the founding captain's personal entitlement.

        Does not refuse create when nothing is active: the captain may redeem a
        code later. Create still gates the captain personally when the form asks.
        """
        form = await _form(self, session, team.tournament_id)
        if form is None or (form.subscription_scope or "player") != SUBSCRIPTION_SCOPE_TEAM:
            return
        if team_subscription_is_current(team):
            return
        store = build_store(session)
        entitlements = await store.load_entitlements(team.workspace_id, [auth_user.id], ["boosty", "discord", "twitch"])
        now = datetime.now(UTC)
        for (_uid, provider), stored in entitlements.items():
            verdict = stored.to_verdict()
            if verdict.state != SubscriptionState.ACTIVE:
                continue
            team.subscription_covered_at = now
            team.subscription_covered_by = auth_user.id
            team.subscription_provider = provider
            team.subscription_tier_rank = verdict.tier_rank
            team.subscription_expires_at = verdict.expires_at
            return

    cls.is_team_staff = is_team_staff
    cls.assert_staff_of_team = assert_staff_of_team
    cls.rename_team = rename_team
    cls.place_member = place_member
    cls.set_member_manager = set_member_manager
    cls.extend_invite = extend_invite
    cls.lock_roster = lock_roster
    cls.unlock_roster = unlock_roster
    cls.check_in_roster = check_in_roster
    cls.cover_team_subscription = cover_team_subscription
    cls.set_admission = set_admission
    cls.set_organizer_notes = set_organizer_notes
    cls.place_member_as_organizer = place_member_as_organizer
    cls._assert_staff = _assert_staff
    cls._assert_staff_editable = _assert_staff_editable
    cls._apply_occupancy_status = staticmethod(_apply_occupancy_status)
    cls._assert_unlocked = staticmethod(_assert_unlocked)
    cls._notify_roster = _notify_roster
    cls._raise_if_ineligible = _raise_if_ineligible
    cls._lock_teams = _lock_teams
    cls._maybe_cover_from_personal = _maybe_cover_from_personal
