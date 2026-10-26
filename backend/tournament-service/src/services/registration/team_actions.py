"""Roster, admission, lock, check-in and team-subscription writes.

Installed onto :class:`RegistrationTeamService` at import time so ``teams`` stays
the occupancy/invite core and these flows can share its lock helpers without a
circular import at definition time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.social import display_social_handle, normalize_social_handle
from shared.disciplines import DISCIPLINES, identity_provider
from shared.domain.team_roster import RosterMember
from shared.domain.team_subscription import SUBSCRIPTION_SCOPE_TEAM, team_subscription_is_current
from shared.repository import CatalogRoleRepository
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from src.core.clients import discord_client
from src.services.registration._common import replace_registration_roles
from src.services.registration.subscription_codes import redeem_challenge_code
from src.services.registration.team_eligibility import team_eligibility
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
        _apply_occupancy_status,
        _assert_mutable,
        _check_slot,
        _fail,
        _owned_by,
    )

    TEAM_ADMISSIONS = frozenset({"pending", "accepted", "waitlisted"})

    def _cleaned_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise _fail(400, "team_name_required", "A team needs a name")
        if "#" in cleaned:
            raise _fail(400, "team_name_invalid", 'A team name cannot contain "#"')
        return cleaned

    def _assert_unlocked(team: models.RegistrationTeam) -> None:
        if team.roster_locked_at is not None:
            raise _fail(409, "roster_locked", "This team's roster is locked")

    async def _form(self, session: AsyncSession, tournament_id: int) -> models.RegistrationForm | None:
        return await session.scalar(
            sa.select(models.RegistrationForm).where(models.RegistrationForm.tournament_id == tournament_id)
        )

    async def _workspace(self, session: AsyncSession, workspace_id: int) -> models.Workspace | None:
        return await session.scalar(sa.select(models.Workspace).where(models.Workspace.id == workspace_id))

    async def _member_auth_user_id(self, session: AsyncSession, registration_id: int) -> int | None:
        return await session.scalar(
            sa.select(models.User.auth_user_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
            .join(
                models.Registration,
                models.Registration.workspace_member_id == models.WorkspaceMember.id,
            )
            .where(models.Registration.id == registration_id)
        )

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
        team: models.RegistrationTeam,
        members: list[models.Registration],
        shape: Any,
    ) -> list[Any]:
        """Refuse a roster that breaks a blocking team rule; otherwise return every issue found.

        The issues come back so the flow's own team read can reuse them instead of
        evaluating (and asking Discord) a second time.
        """
        form = await _form(self, session, team.tournament_id)
        workspace = await _workspace(self, session, team.workspace_id)
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
        if not await is_team_staff(self, session, team, auth_user.id):
            raise _fail(403, "not_captain", "Only the team captain or a manager can do this")

    async def _assert_staff_editable(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
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
    ) -> models.RegistrationTeam:
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await _assert_staff(self, session, team, auth_user)
        return team

    async def _lock_teams(self, session: AsyncSession, team_ids: list[int]) -> dict[int, models.RegistrationTeam]:
        locked: dict[int, models.RegistrationTeam] = {}
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
    ) -> models.RegistrationTeam:
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
    ) -> models.RegistrationTeam:
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

    async def extend_invite(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        invite_id: int,
        auth_user: models.AuthUser,
        ttl: timedelta | None = None,
        rotate_token: bool = False,
    ) -> tuple[models.RegistrationTeamInvite, str | None]:
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
    ) -> models.RegistrationTeam:
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

    async def check_in_roster(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        exclude_registration_ids: list[int] | None = None,
    ) -> models.RegistrationTeam:
        from src.services.admission.resolve import load_auth_user_ids
        from src.services.registration.admission import assert_roster_admitted

        excluded = set(exclude_registration_ids or [])

        def _awaiting(members: list[models.Registration]) -> list[models.Registration]:
            awaiting = [r for r in members if r.id not in excluded and not r.checked_in]
            if any(r.status != "approved" for r in awaiting):
                raise _fail(409, "member_not_approved", "Every member must be approved before team check-in")
            return awaiting

        # Admission first, for the whole roster in ONE provider batch and outside the
        # team lock: the gate asks providers and commits, and a lock held across that
        # would queue every roster edit behind Discord/Twitch. Under the lock below the
        # roster is re-read; a member the gate did not see is refused, never checked
        # in ungated.
        team = await session.scalar(
            self.team_repo.select().where(
                models.RegistrationTeam.id == team_id,
                models.RegistrationTeam.deleted_at.is_(None),
            )
        )
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await _assert_staff(self, session, team, auth_user)
        tournament = await self.tournament_repo.get(session, team.tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        if not is_check_in_window_active(tournament):
            raise _fail(409, "check_in_closed", "Check-in is not active for this tournament")
        awaiting = _awaiting(await self._roster_members(session, team.id))
        accounts = await load_auth_user_ids(session, awaiting)
        if any(accounts[registration.id] is None for registration in awaiting):
            raise _fail(409, "player_has_no_account", "This player has no account to check in")
        for registration in awaiting:
            registration.tournament = tournament
            registration.registration_team = team
        await assert_roster_admitted(session, awaiting, tournament_id=team.tournament_id)
        admitted = {registration.id for registration in awaiting}

        team = await self._lock_team(session, team_id)
        await _assert_staff(self, session, team, auth_user)
        now = datetime.now(UTC)
        for registration in _awaiting(await self._roster_members(session, team.id, fresh=True)):
            if registration.id not in admitted:
                raise _fail(409, "roster_changed", "The roster changed during check-in; try again")
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
    ) -> models.RegistrationTeam:
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
        locked = await _lock_teams(self, session, lock_ids)
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
        dest = await _place_onto(
            self,
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
        await _raise_if_ineligible(self, session, dest, members, shape)
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
        dest = await _place_onto(
            self,
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

    async def _maybe_cover_from_personal(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
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
    cls.attach_member_as_organizer = attach_member_as_organizer
    cls._assert_staff = _assert_staff
    cls._assert_staff_editable = _assert_staff_editable
    cls._apply_occupancy_status = staticmethod(_apply_occupancy_status)
    cls._assert_unlocked = staticmethod(_assert_unlocked)
    cls._notify_roster = _notify_roster
    cls._raise_if_ineligible = _raise_if_ineligible
    cls._lock_teams = _lock_teams
    cls._maybe_cover_from_personal = _maybe_cover_from_personal
