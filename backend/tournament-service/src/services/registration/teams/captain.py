"""Captain flows over the team itself: create, crest, rename, lock, check-in,
subscription cover, captaincy transfer and disband.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.domain.team_eligibility import EligibilityIssue
from shared.domain.team_subscription import SUBSCRIPTION_SCOPE_TEAM, team_subscription_is_current
from shared.services.realtime import Resource, Scope, emit
from shared.services.subscriptions import SubscriptionState
from shared.services.subscriptions.wiring import build_store
from src.schemas.registration import RegistrationSubmit
from src.services.registration.service import TeamPlacement
from src.services.registration.subscription_codes import redeem_challenge_code
from src.services.registration.teams._core import TeamServiceBase, _form
from src.services.registration.teams._shared import (
    INVITE_PENDING,
    INVITE_REVOKED,
    TEAM_COMPLETE,
    TEAM_DISBANDED,
    TEAM_FORMING,
    _apply_occupancy_status,
    _assert_mutable,
    _assert_unlocked,
    _check_slot,
    _fail,
)
from src.services.registration.windows import is_check_in_window_active


def _cleaned_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise _fail(400, "team_name_required", "A team needs a name")
    if "#" in cleaned:
        raise _fail(400, "team_name_invalid", 'A team name cannot contain "#"')
    return cleaned


class CaptainMixin(TeamServiceBase):
    """A team's own lifecycle, driven by its captain or managers."""

    async def create_team(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
        name: str,
        slot_code: str,
        body: RegistrationSubmit,
    ) -> tuple[models.RegistrationTeam, models.Registration, list[EligibilityIssue]]:
        """Register a new team, with the caller as captain occupying one slot.

        The captain is a member like any other: they take a real slot and
        their own registration goes through the same validation as a solo entrant. One
        transaction, so a team can never exist without its captain's registration.

        Returns the team, the captain's registration row and the roster's
        eligibility issues (reused by the caller's team read, see ``accept_invite``).
        """
        cleaned_name = name.strip()
        if not cleaned_name:
            raise _fail(400, "team_name_required", "A team needs a name")
        if "#" in cleaned_name:
            # The materialization seam derives ``Team.name`` as everything before the
            # first "#" (the battle-tag convention the balancer/draft payloads use), so
            # a name containing one would be silently truncated on export — and the
            # exported_team_id backfill, keyed on the full name, would then miss.
            raise _fail(400, "team_name_invalid", 'A team name cannot contain "#"')

        tournament = await self._assert_registration_open(session, tournament_id)
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, tournament_id)

        team = models.RegistrationTeam(
            tournament_id=tournament_id,
            workspace_id=tournament.workspace_id,
            name=cleaned_name,
            name_normalized=cleaned_name.lower(),
            status=TEAM_FORMING,
        )
        try:
            await self.team_repo.create(session, team)
        except IntegrityError as exc:
            # The partial unique index on (tournament_id, lower(name)) matches the
            # export writer's dedup rule, so a silent two-teams-into-one merge is
            # impossible.
            raise _fail(409, "team_name_taken", "A team with this name is already registered") from exc

        # An empty roster: the captain's own slot must exist in the shape, and this is
        # the check that rejects e.g. "tank" on a role-less tournament.
        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)
        _check_slot(occupancy, slot_code, is_substitute=False, offering=False)

        registration = await self.registrations.write_public_registration(
            session,
            tournament_id=tournament_id,
            auth_user=auth_user,
            body=body,
            team_placement=TeamPlacement(registration_team_id=team.id, slot_code=slot_code),
            commit=False,
        )
        team.captain_registration_id = registration.id
        _apply_occupancy_status(
            team,
            await self._occupancy(
                session,
                team,
                shape,
                max_substitutes=max_substitutes,
            ),
        )
        issues = await self._raise_if_ineligible(session, team, await self._roster_members(session, team.id), shape)
        await self._maybe_cover_from_personal(session, team, auth_user)
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            # With ``commit=False`` the duplicate-registration and duplicate-name races
            # fire here, outside the submit helper's own ``try``.
            raise _fail(409, "already_registered", "You are already registered for this tournament") from exc
        return team, registration, issues

    async def set_team_image(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        image_url: str | None,
    ) -> models.RegistrationTeam:
        """Set (or clear, with ``None``) a registered team's crest.

        Captain-gated rather than workspace-permission-gated — the deliberate
        difference from the materialized ``Team``'s image pair in
        ``services/admin/team.py``, which requires ``team.update`` on the workspace.
        A registration team belongs to the players who formed it, not to the
        organizer's staff: its captain is an ordinary competitor who typically holds
        no workspace membership at all, so a workspace gate would lock out exactly
        the person who owns the crest. The organizer's lever over a team's branding
        stays :meth:`reject_team`, not silent re-branding.

        Same mutability rule as every other roster edit (:func:`_assert_mutable`): an
        exported or terminal team is frozen, so its card cannot change after the
        field is set.
        """
        team = await self._lock_team(session, team_id)
        await self._assert_staff_editable(session, team, auth_user)
        team.image_url = image_url
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        # Scalar-only mutation; expire_on_commit=False keeps the instance renderable
        # by ``describe_team`` without a refresh round-trip.
        return team

    async def assert_may_edit_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """The captain gate without the row lock, for callers that must refuse
        *before* doing slow external work.

        A crest upload writes its S3 object before the row write, so a stranger who
        reached S3 would leave an orphan object behind regardless of what the database
        later refuses (the delete touches S3 only after the row commits).
        Taking :meth:`_lock_team`'s row lock across that network round-trip would
        instead pin a backend slot for its whole duration, so this reads without
        ``FOR UPDATE``.

        Advisory only: :meth:`set_team_image` re-runs both checks under the lock, and
        that is the authoritative decision.
        """
        team = await self.assert_staff_of_team(session, team_id=team_id, auth_user=auth_user)
        _assert_mutable(team)
        _assert_unlocked(team)

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
            await self._assert_staff_editable(session, team, auth_user)
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
        await self._assert_staff(session, team, auth_user)
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
        await self._assert_staff(session, team, auth_user)
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
        await self._assert_staff(session, team, auth_user)
        form = await _form(session, team.tournament_id)
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
        form = await _form(session, team.tournament_id)
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

    async def transfer_captaincy(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        registration_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Hand captaincy to another accepted member. Rosters are unchanged."""
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        await self._assert_registration_open(session, team.tournament_id)
        await self._assert_captain(session, team, auth_user)

        successor = await self.registration_repo.get(session, registration_id)
        if successor is None or successor.registration_team_id != team.id:
            raise _fail(404, "member_not_found", "This player is not on the team")
        if successor.is_substitute:
            # A bench player holds no starter slot, so making them captain would leave
            # the roster with a captain outside its own shape.
            raise _fail(409, "captain_must_be_starter", "A substitute cannot captain the team")
        team.captain_registration_id = successor.id
        await session.commit()

    async def disband_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Captain dissolves the team.

        Members' registrations survive as withdrawn rows, which is why the captain FK
        is ``SET NULL`` rather than a cascade: a captain walking away must not delete
        other people's entries.
        """
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        await self._assert_registration_open(session, team.tournament_id)
        await self._assert_captain(session, team, auth_user)

        # Only the STATUS changes; the team link is retained deliberately. The "your
        # team was disbanded" line on the member's own card is derived from this FK,
        # so clearing it (as ``kick_member``/``leave_team`` do) would leave a withdrawn
        # registration with no explanation. ``_roster_members`` filters withdrawn rows
        # out, so slot accounting and the export are unaffected. Kick/leave means "you
        # are not on this team"; disband/reject means "this team ended".
        members = await self._roster_members(session, team.id)
        tournament = await self.tournament_repo.get(session, team.tournament_id)
        await self._notify_roster(
            session,
            team,
            kind="team.disbanded",
            payload={
                "team_id": team.id,
                "team_name": team.name,
                "tournament_id": team.tournament_id,
                "tournament_name": tournament.name if tournament is not None else "",
            },
            members=members,
        )
        for registration in members:
            registration.status = "withdrawn"
        # Revokes EXPIRED pending rows too, unlike ``consume_if_pending`` — see that
        # repository method's docstring.
        await self.invite_repo.revoke_pending_for_team(
            session, team.id, pending_state=INVITE_PENDING, revoked_state=INVITE_REVOKED
        )
        team.status = TEAM_DISBANDED
        team.deleted_at = datetime.now(UTC)
        team.deleted_by = auth_user.id
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
