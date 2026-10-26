"""Team registration flows: create, invite, accept, and roster edits.

Three properties shape every method here.

**One registration per player, always.** A team member's registration is an
ordinary :class:`Registration` row with three extra columns set, so every
existing gate (self-register capability, subscription, open profile, verified
identity), every count and every reader keeps working untouched. That is why the
captain and invitee flows delegate to
:meth:`~src.services.registration.service.RegistrationService.write_public_registration`
rather than writing rows themselves.

**The slot check and the slot write are one transaction.** Every mutating flow
takes ``SELECT … FOR UPDATE`` on the team row *before* reading occupancy, and the
write lands before that lock is released. Without it two invitees accept the last
``damage`` slot and the roster silently overflows the shape, which the export would
then materialize as an over-sized team. Most flows lock exactly one team row.
Organizer placement of a player who already sits on another team is the
exception: both teams are locked in id order so two concurrent moves cannot
deadlock.

**A dead invite must say why it is dead.** The guarded ``UPDATE`` collapses
expired / revoked / already-accepted into one rowcount 0, and each case needs a
distinct machine code, so :func:`_diagnose_dead_invite` re-reads the row *for
reporting only* — after the guard has already decided, where it cannot reintroduce
the race.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.errors import ApiExc, ApiHTTPException
from shared.disciplines import identity_provider
from shared.domain.invite_token import generate_invite_token, hash_invite_token
from shared.domain.roster_shape import RosterShape, RosterShapeError
from shared.domain.team_eligibility import EligibilityIssue
from shared.domain.team_roster import RosterMember, RosterOccupancy
from shared.repository import (
    RegistrationRepository,
    RegistrationTeamInviteRepository,
    RegistrationTeamRepository,
    TournamentRepository,
)
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from shared.services.team_format import tournament_slot_shape
from src.schemas.registration import RegistrationSubmit
from src.schemas.registration_team import (
    RegistrationFreeAgentRead,
    RegistrationTeamInviteHistoryEntry,
    RegistrationTeamInviteHistoryResponse,
    RegistrationTeamInviteOffer,
    RegistrationTeamInvitePreview,
    RegistrationTeamMemberRead,
    RegistrationTeamRead,
    RegistrationTeamRejectRequest,
    serialize_invite,
    serialize_registration_team,
)
from src.services.admission import AdmissionStage
from src.services.registration.admission import assert_admitted_at
from src.services.registration.service import (
    RegistrationService,
    TeamPlacement,
    _owned_by,
    registration_service,
)
from src.services.registration.team_rate_limits import (
    TEAM_INVITE_TOTAL_CAP,
    assert_accept_attempt_allowed,
    assert_invite_attempt_allowed,
)
from src.services.registration.windows import is_registration_open

__all__ = (
    "DEFAULT_INVITE_TTL",
    "TEAM_STATUSES",
    "RegistrationTeamService",
    "teams_service",
)

# ── vocabularies ─────────────────────────────────────────────────────────────

TEAM_FORMING = "forming"
TEAM_COMPLETE = "complete"
TEAM_REJECTED = "rejected"
TEAM_DISBANDED = "disbanded"
TEAM_STATUSES = (TEAM_FORMING, TEAM_COMPLETE, TEAM_REJECTED, TEAM_DISBANDED)
#: Statuses whose roster may still change. ``rejected``/``disbanded`` are terminal,
#: and an exported team is frozen by ``exported_team_id`` rather than by status —
#: its shape is already baked into ``tournament.player`` rows.
_MUTABLE_TEAM_STATUSES = frozenset({TEAM_FORMING, TEAM_COMPLETE})

INVITE_PENDING = "pending"
INVITE_ACCEPTED = "accepted"
INVITE_DECLINED = "declined"
INVITE_REVOKED = "revoked"

DEFAULT_INVITE_TTL = timedelta(days=7)

#: Statuses that release a roster slot. A withdrawn member frees their slot for a
#: replacement; a rejected registration was never on the roster.
_SLOT_RELEASING_STATUSES = frozenset({"withdrawn", "rejected"})


def _fail(status_code: int, code: str, msg: str) -> ApiHTTPException:
    """Build a rejection carrying a stable machine code.

    These surfaces are public and Russian-first, so the frontend maps
    ``code`` to a translated string. A bare ``detail`` string would be rendered
    verbatim in English.
    """
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(msg=msg, code=code)])


def _assert_mutable(team: models.RegistrationTeam) -> None:
    if team.exported_team_id is not None:
        raise _fail(409, "team_already_exported", "This team has already been exported to the tournament")
    if team.status not in _MUTABLE_TEAM_STATUSES:
        raise _fail(409, "team_not_forming", f"This team is {team.status} and can no longer be changed")


def _status_for(occupancy: RosterOccupancy) -> str:
    return TEAM_COMPLETE if occupancy.is_complete else TEAM_FORMING


def _apply_occupancy_status(team: models.RegistrationTeam, occupancy: RosterOccupancy) -> None:
    """Write forming/complete from occupancy, never over a terminal status.

    Admission is a separate column. Occupancy must not clobber rejected/disbanded,
    and must not invent a status the organizer's waitlist decision sits on top of.
    """
    if team.status in _MUTABLE_TEAM_STATUSES:
        team.status = _status_for(occupancy)


def _occupancy_of(
    shape: RosterShape,
    members: Sequence[models.Registration],
    invites: Sequence[models.RegistrationTeamInvite],
    *,
    max_substitutes: int,
    extra: RosterMember | None = None,
) -> RosterOccupancy:
    """Slot occupancy from already-read members and live invites."""
    accepted = [
        RosterMember(slot_code=m.team_slot_code or "", is_substitute=bool(m.is_substitute))
        for m in members
        if m.team_slot_code
    ]
    if extra is not None:
        accepted.append(extra)
    return RosterOccupancy(
        shape=shape,
        accepted=tuple(accepted),
        pending=tuple(RosterMember(slot_code=i.slot_code, is_substitute=bool(i.is_substitute)) for i in invites),
        max_substitutes=max_substitutes,
    )


def _check_slot(occupancy: RosterOccupancy, slot_code: str, *, is_substitute: bool, offering: bool) -> None:
    """Raise the right machine code for a slot that cannot take one more body."""
    try:
        allowed = (
            occupancy.can_offer(slot_code, is_substitute=is_substitute)
            if offering
            else occupancy.can_accept(slot_code, is_substitute=is_substitute)
        )
    except RosterShapeError as exc:
        # ``slot_not_in_shape``/``roster_slots_unknown_code`` — a client asking for
        # a slot this tournament's roster does not have. A 400, not a 409: nothing
        # about the team's state would make it succeed later.
        raise _fail(400, exc.code, str(exc)) from exc
    if allowed:
        return
    if is_substitute:
        raise _fail(409, "bench_full", "This team has no substitute places left")
    raise _fail(
        409,
        "slot_taken" if not offering else "slot_already_offered",
        f"The {slot_code} slot is not available on this team",
    )


def _diagnose_dead_invite(invite: models.RegistrationTeamInvite) -> ApiHTTPException:
    """Turn a rowcount-0 guard result into a distinct machine code.

    Called only *after* the guarded ``UPDATE`` has already decided, so this read
    cannot reintroduce the race it is explaining. Four situations with four
    different recourses would otherwise collapse into one opaque failure.
    """
    if invite.state == INVITE_ACCEPTED:
        return _fail(409, "invite_already_accepted", "This invite has already been accepted")
    if invite.state == INVITE_REVOKED:
        return _fail(409, "invite_revoked", "This invite was withdrawn by the captain")
    if invite.state == INVITE_DECLINED:
        return _fail(409, "invite_declined", "This invite was already declined")
    expires_at = invite.expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return _fail(409, "invite_expired", "This invite has expired — ask the captain for a new one")
    # Pending, unexpired, and still rejected by the guard: the only remaining
    # explanation is a concurrent acceptance that committed between the guard and
    # this read.
    return _fail(409, "invite_already_accepted", "This invite has already been accepted")


def _withdraw_invite(
    invite: models.RegistrationTeamInvite,
    *,
    by: models.AuthUser,
    by_organizer: bool,
) -> None:
    """The state transition both revoke paths share.

    Extracted rather than parameterised with an ``as_organizer`` AUTHORIZATION
    flag: flag-driven authorization is how a privilege check gets skipped by a
    caller who passes the wrong default. The two gates stay in the two named entry
    points; ``by_organizer`` here is provenance, recorded by the caller that knows
    it, because inferring it later is impossible once captaincy has moved.
    """
    if invite.state != INVITE_PENDING:
        raise _diagnose_dead_invite(invite)
    invite.state = INVITE_REVOKED
    invite.revoked_by = by.id
    invite.revoked_at = datetime.now(UTC)
    invite.revoked_by_organizer = by_organizer


def _normalize_invite_token(token: str) -> str:
    """Strip EVERY whitespace character, not just the ends.

    A real token is a bare base64url string — it never legitimately contains
    whitespace anywhere. A stray leading/trailing/embedded space or newline is
    always corruption picked up while the link was pasted out of the `<code>`
    block that displays it, wrapped by a text field, or forwarded through a
    chat client. Removing it can therefore only rescue a mangled presentation;
    it can never turn one valid token into another.
    """
    return "".join(token.split())


def _free_agent_clause(tournament_id: int) -> list[sa.ColumnElement[bool]]:
    """The one definition of "free agent": a live registration on no team.

    Shared by the count and the list on purpose. Two copies would drift, and the
    failure is silent and specific — an organizer reading "3 players without a
    team" above a picker offering two of them cannot tell which number is lying.

    Withdrawn and rejected rows are excluded on the same rule the roster reader
    uses: they released their slot and are not waiting for anything.
    """
    return [
        models.Registration.tournament_id == tournament_id,
        models.Registration.registration_team_id.is_(None),
        models.Registration.deleted_at.is_(None),
        models.Registration.status.notin_(_SLOT_RELEASING_STATUSES),
    ]


class RegistrationTeamService:
    """Captain, invitee and organizer flows over ``registration_team``."""

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

    # ── captain flows ────────────────────────────────────────────────────────

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
        self._assert_unlocked(team)

    async def _resolve_invite_target(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        registration_id: int,
    ) -> int:
        """The account behind a targeted invite's registration.

        An invite binds to an IDENTITY, not to a registration row: the invitee may
        withdraw and resubmit before answering, and `accept_invite` attaches whatever
        live registration they have at that moment. Binding to the row would strand the
        offer on a dead one.

        Every rejection here is a distinct code because each has a different recourse:
        picked someone from another tournament (impossible from the UI, so a real bug),
        picked someone who joined a team while the dialog was open (pick again), or
        picked a row with no account behind it (an imported player who never signed in —
        only a link invite can reach them).
        """
        registration = await session.scalar(
            self.registration_repo.select()
            .where(
                models.Registration.id == registration_id,
                models.Registration.deleted_at.is_(None),
            )
            .options(selectinload(models.Registration.workspace_member))
        )
        if registration is None or registration.tournament_id != tournament_id:
            # Deliberately 404 rather than 403: confirming that a registration exists
            # elsewhere would answer a question the caller has no business asking.
            raise _fail(404, "registration_not_found", "That registration is not in this tournament")
        if registration.registration_team_id is not None or registration.status in _SLOT_RELEASING_STATUSES:
            # The free-agent list is a snapshot; someone can be recruited between the
            # captain opening the picker and pressing invite.
            raise _fail(409, "player_not_free", "That player is no longer available")

        member = registration.workspace_member
        auth_user_id = (
            await session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == member.player_id))
            if member is not None
            else None
        )
        if auth_user_id is None:
            raise _fail(409, "player_has_no_account", "That player has no site account; send them a link instead")
        return auth_user_id

    async def invite_member(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        slot_code: str,
        is_substitute: bool = False,
        target_registration_id: int | None = None,
        ttl: timedelta | None = DEFAULT_INVITE_TTL,
    ) -> tuple[models.RegistrationTeamInvite, str | None]:
        """Offer one roster slot. Returns the invite and, for a link invite, the raw
        token — which is shown exactly once and never stored.

        Two addressing modes on one entity. ``target_registration_id`` is
        an in-app offer to a free agent already in this tournament; without it the
        invite is a shareable link for someone who has no account yet.

        A targeted invite gets NO token. That is the point: nothing to paste, nothing
        to leak, nothing to forward to the wrong person. Its recipient learns of it from
        their own registration card.
        """
        # Metered BEFORE the row lock: a limiter behind the lock would let a flood
        # serialize on the team row and hold it, turning the throttle into a
        # lock-contention amplifier.
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await assert_invite_attempt_allowed(tournament_id=team.tournament_id, auth_user_id=auth_user.id)

        team = await self._lock_team(session, team_id)
        await self._assert_staff_editable(session, team, auth_user)
        tournament = await self._assert_registration_open(session, team.tournament_id)

        # The slot reservation caps *concurrent* pending invites, but an
        # invite -> revoke -> invite loop stays inside every slot rule. This cumulative
        # ceiling counts every invite ever created for the team, so the loop ends.
        issued = await self.count_invites_against_cap(session, team)
        if issued >= TEAM_INVITE_TOTAL_CAP:
            raise _fail(
                409,
                "invite_cap_reached",
                "This team has issued too many invites; revoke an outstanding one or ask an organizer to reset the cap",
            )

        shape = await self._resolve_shape(session, tournament)
        occupancy = await self._occupancy(
            session, team, shape, max_substitutes=await self._max_substitutes(session, team.tournament_id)
        )
        # ``offering=True``: a pending invite reserves its slot, so a captain cannot
        # hold ten open offers for one place.
        _check_slot(occupancy, slot_code, is_substitute=is_substitute, offering=True)

        raw_token: str | None = None
        token_hash: str | None = None
        target_auth_user_id: int | None = None
        if target_registration_id is None:
            raw_token, token_hash = generate_invite_token()
        else:
            # Resolved INSIDE the lock, after the slot check: the freshness of "this
            # player is unattached" and "this slot is open" must be decided under the
            # same lock that the write commits under, or a concurrent acceptance can
            # invalidate one of them between check and insert.
            target_auth_user_id = await self._resolve_invite_target(
                session, tournament_id=team.tournament_id, registration_id=target_registration_id
            )

        invite = await self.invite_repo.create(
            session,
            models.RegistrationTeamInvite(
                team_id=team.id,
                slot_code=slot_code,
                is_substitute=is_substitute,
                target_auth_user_id=target_auth_user_id,
                token_sha256=token_hash,
                expires_at=datetime.now(UTC) + ttl if ttl is not None else None,
                state=INVITE_PENDING,
                invited_by=auth_user.id,
            ),
        )
        if target_auth_user_id is not None:
            # Only the targeted mode has an addressee. A link invite is a bearer
            # credential whose recipient is whoever the captain sends it to --
            # there is no account to write an inbox row for.
            await notify(
                session,
                kind="team_invite.received",
                recipient_auth_user_id=target_auth_user_id,
                source_workspace_id=team.workspace_id,
                actor_auth_user_id=auth_user.id,
                payload={
                    "team_id": team.id,
                    "team_name": team.name,
                    "tournament_id": team.tournament_id,
                    "tournament_name": tournament.name,
                    "slot_code": slot_code,
                    "is_substitute": is_substitute,
                    "invite_id": invite.id,
                },
            )
        await session.commit()
        return invite, raw_token

    async def count_invites_against_cap(
        self,
        session: AsyncSession,
        team: models.RegistrationTeam,
    ) -> int:
        """How many invites count toward this team's cumulative ceiling.

        One definition, shared by the check that refuses an invite and the number the
        UI shows. Two copies would produce the worst version of this feature: a captain
        told "12 of 60 used" and refused at the same moment, with no way to tell which
        is wrong.

        Every invite ever created counts, not just live ones — that is the whole point
        of a cumulative cap, since an invite -> revoke -> invite loop stays inside every
        slot rule. ``invite_cap_reset_at`` moves the floor rather than zeroing a
        counter, so the rows behind a forgiven cap remain readable.
        """
        conditions: list[sa.ColumnElement[bool]] = [models.RegistrationTeamInvite.team_id == team.id]
        if team.invite_cap_reset_at is not None:
            conditions.append(models.RegistrationTeamInvite.invited_at > team.invite_cap_reset_at)
        return await self.invite_repo.count(session, filters=conditions)

    async def revoke_invite(
        self,
        session: AsyncSession,
        *,
        invite_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """A captain withdraws their own outstanding offer, releasing its slot."""
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        team = await self._lock_team(session, invite.team_id)
        await self._assert_staff(session, team, auth_user)
        _withdraw_invite(invite, by=auth_user, by_organizer=False)
        await session.commit()

    async def revoke_invite_as_organizer(
        self,
        session: AsyncSession,
        *,
        invite_id: int,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """An organizer withdraws an offer from a team they do not captain.

        The caller owns the workspace-permission check; what this owns is the scope
        one: the invite must belong to a team in ``tournament_id``. Without that an
        organizer of any tournament could pass any invite id and act on another
        tournament's roster, because an invite id is global while their permission is
        not.

        Unlike the captain path this does NOT require the team to be mutable. A
        forming-only rule would make the power useless exactly when it is needed — the
        reason to reach in is usually that something is stuck.
        """
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        team = await self._lock_team(session, invite.team_id)
        if team.tournament_id != tournament_id:
            # 404, not 403: confirming the invite exists elsewhere would answer a
            # question this organizer has no permission to ask.
            raise _fail(404, "invite_not_found", "Invite not found")
        _withdraw_invite(invite, by=auth_user, by_organizer=True)
        await session.commit()

    async def list_invite_history(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        tournament_id: int,
    ) -> RegistrationTeamInviteHistoryResponse:
        """Every invite the team ever issued, newest first, plus its cap standing.

        A separate read from ``describe_team`` on purpose. That one returns only LIVE
        pending invites because occupancy depends on them reserving slots; mixing
        terminal rows in would make a declined offer hold a place. This is also why the
        section is collapsed in the UI: nothing pays for it until someone asks.

        The cap counts every invite ever created, so every one must be visible:
        otherwise an invite -> revoke -> invite cycle burns the ceiling with no cause
        on screen, and a DECLINED offer is indistinguishable from a lapsed link —
        different situations with different next moves.

        ``tournament_id`` is the caller's already-authorized tournament (organizer
        permission checked against it, or the captain's own tournament in the public
        handler) — required and checked against the team's own, like
        ``reset_invite_cap``, so a foreign ``team_id`` 404s instead of leaking another
        tournament's invite history and target handles.
        """
        team = await self.team_repo.get(session, team_id)
        if team is None or team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")

        rows = list(await self.invite_repo.list_for_team(session, team_id))
        tags = await self._handles_by_account(
            session,
            tournament_id=team.tournament_id,
            provider=await self._owner_provider(session, team.tournament_id),
            auth_user_ids={r.target_auth_user_id for r in rows if r.target_auth_user_id is not None},
        )
        now = datetime.now(UTC)
        return RegistrationTeamInviteHistoryResponse(
            items=[
                RegistrationTeamInviteHistoryEntry(
                    id=row.id,
                    slot_code=row.slot_code,
                    is_substitute=bool(row.is_substitute),
                    # `expired` is not a stored state: it is a pending row past its
                    # clock. Computed here for the same reason the link preview computes
                    # it — a lapsed offer and a live one are not the same entry, and the
                    # column cannot tell them apart.
                    state="expired"
                    if row.state == INVITE_PENDING and row.expires_at is not None and row.expires_at <= now
                    else row.state,
                    target_handle=tags.get(row.target_auth_user_id),
                    is_link=row.token_sha256 is not None,
                    invited_at=row.invited_at,
                    expires_at=row.expires_at,
                    answered_at=row.accepted_at or row.revoked_at,
                    # Who ended it, when anyone did. A captain revoking their own offer
                    # and an organizer reaching into the roster are the same state and
                    # very different events.
                    revoked_by_organizer=bool(row.revoked_by_organizer),
                )
                for row in rows
            ],
            cap_used=await self.count_invites_against_cap(session, team),
            cap_limit=TEAM_INVITE_TOTAL_CAP,
            cap_reset_at=team.invite_cap_reset_at,
        )

    async def reset_invite_cap(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Forgive a team's cumulative invite count so its captain can invite again.

        A watermark, not a counter reset: the cap is a COUNT over every invite ever
        created, and clearing it by deleting rows would erase the history that explains
        why the cap was hit. The rows stay; the count starts here.
        """
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        team.invite_cap_reset_at = datetime.now(UTC)
        team.invite_cap_reset_by = auth_user.id
        await session.commit()

    # ── invitee flows ────────────────────────────────────────────────────────

    async def _resolve_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        token: str | None,
        invite_id: int | None,
    ) -> models.RegistrationTeamInvite:
        """Find the invite being redeemed, by token or by id.

        Token lookup is by *hash*, which the partial unique index serves as a single
        indexed read — the raw value is never compared against anything stored.

        By id only a TARGETED invite resolves, and only for its addressee. A link
        invite's credential is its token; its id is a sequential key anybody can
        guess, so a link invite asked for by id is ``invite_not_found``.
        """
        if token is not None:
            invite = await self.invite_repo.get_by_token_hash(
                session, hash_invite_token(_normalize_invite_token(token))
            )
        elif invite_id is not None:
            invite = await self.invite_repo.get(session, invite_id)
            if invite is not None and invite.target_auth_user_id is None:
                invite = None
        else:
            raise _fail(400, "invite_reference_required", "An invite id or token is required")
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        # A targeted invite is addressed to one account; a link invite is bearer.
        if invite.target_auth_user_id is not None and invite.target_auth_user_id != auth_user.id:
            raise _fail(403, "invite_not_for_you", "This invite was sent to a different account")
        return invite

    async def preview_invite(self, session: AsyncSession, *, token: str) -> RegistrationTeamInvitePreview:
        """What a link invite shows before anyone signs in.

        Deliberately anonymous: the whole point of a link invite is that it reaches
        someone with no account yet, and asking them to register before telling them
        what they are joining is the wrong order. The token itself is the credential,
        so holding it is the authorization — and this returns strictly the offer (team,
        tournament, slot), never the roster.

        Unmetered by necessity: with no actor there is nothing to key a limiter on. The
        guessing space is a 256-bit token, and flooding is the gateway's anonymous IP
        budget, not this handler's problem.

        A dead or expired invite is NOT an error here. The landing page needs to say
        *why* a link stopped working, so state travels in the payload and only a token
        matching nothing at all is a 404.
        """
        # Not ``get_by_token_hash``: this read needs the team -> tournament eager-load
        # graph for the preview payload, and that method takes no ``options``.
        invite = await session.scalar(
            self.invite_repo.select()
            # See `_normalize_invite_token`'s docstring for why stripping whitespace
            # here is safe: a real token never contains any.
            .where(models.RegistrationTeamInvite.token_sha256 == hash_invite_token(_normalize_invite_token(token)))
            .options(selectinload(models.RegistrationTeamInvite.team).selectinload(models.RegistrationTeam.tournament))
        )
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")

        team = invite.team
        # Expiry is computed here rather than client-side: the clock this compares
        # against is the one the guarded UPDATE in `accept_invite` uses, not the
        # visitor's. A link that looks live but rejects on submit is the worse bug.
        live = invite.state == INVITE_PENDING and (invite.expires_at is None or invite.expires_at > datetime.now(UTC))
        return RegistrationTeamInvitePreview(
            tournament_id=team.tournament_id,
            tournament_name=team.tournament.name,
            workspace_id=team.workspace_id,
            discipline=team.tournament.discipline,
            team_id=team.id,
            team_name=team.name,
            slot_code=invite.slot_code,
            is_substitute=invite.is_substitute,
            state=invite.state,
            expires_at=invite.expires_at,
            # A team that already exported, or was disbanded, cannot take anyone —
            # regardless of how healthy the invite row looks.
            is_redeemable=live and team.status == TEAM_FORMING and team.exported_team_id is None,
        )

    async def _notify_invite_answered(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        team_name: str,
        tournament_id: int,
        workspace_id: int,
        captain_registration_id: int | None,
        invite_id: int,
        answer: str,
        responder: models.AuthUser,
        responder_name: str,
    ) -> None:
        """Tell the captain how their offer was answered.

        Nobody to tell is not an error: a team whose captain registration was
        hard-deleted, or a captain who is a shadow player
        (``players.user.auth_user_id IS NULL``). The roster change itself stands,
        it just goes unannounced.

        The recipient is derived from the team's own captain row, never from
        anything the answering account supplied.
        """
        if captain_registration_id is None:
            return
        captain_auth_user_id = await session.scalar(
            sa.select(models.User.auth_user_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
            .join(
                models.Registration,
                models.Registration.workspace_member_id == models.WorkspaceMember.id,
            )
            .where(models.Registration.id == captain_registration_id)
        )
        if captain_auth_user_id is None:
            return
        await notify(
            session,
            kind="team_invite.answered",
            recipient_auth_user_id=int(captain_auth_user_id),
            source_workspace_id=workspace_id,
            actor_auth_user_id=responder.id,
            payload={
                "team_id": team_id,
                "team_name": team_name,
                "tournament_id": tournament_id,
                "invite_id": invite_id,
                "answer": answer,
                "responder_name": responder_name,
            },
        )

    async def accept_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        body: RegistrationSubmit | None,
        token: str | None = None,
        invite_id: int | None = None,
    ) -> tuple[models.RegistrationTeam, int, list[EligibilityIssue]]:
        """Redeem an invite: take the offered slot, registering if necessary.

        Returns the team, the id of the registration now holding the slot, and the
        roster's eligibility issues as evaluated under the lock (the caller's team
        read reuses them instead of asking Discord a second time).

        Everything below the team lock happens in one transaction, which is what
        makes the slot check binding. Ordering matters: every rejection that can be
        known up front is raised *before* the invite is consumed, so a failed
        acceptance never burns the invite.

        A redeemer with no registration yet is signing up, so the registration-stage
        admission gate runs first, outside the lock: it asks providers and commits.

        ``body`` is used ONLY when the redeemer has no registration yet. An existing
        one is attached to the team instead — see the comment at the write below.
        """
        # Metered before the token lookup, so a guessing flood is throttled without
        # even reaching the index. Fails OPEN: 256 bits of entropy already make
        # guessing infeasible, so this is defence in depth, not the defence.
        await assert_accept_attempt_allowed(auth_user_id=auth_user.id)

        invite = await self._resolve_invite(session, auth_user=auth_user, token=token, invite_id=invite_id)
        # Advisory, before the admission gate's provider call: a dead link answers with
        # its real reason, for free. ``consume_if_pending`` under the lock stays the
        # authoritative guard against a concurrent redemption.
        if invite.state != INVITE_PENDING or (invite.expires_at is not None and invite.expires_at <= datetime.now(UTC)):
            raise _diagnose_dead_invite(invite)
        tournament_id = await session.scalar(
            sa.select(models.RegistrationTeam.tournament_id).where(
                models.RegistrationTeam.id == invite.team_id,
                models.RegistrationTeam.deleted_at.is_(None),
            )
        )
        gated = False
        if tournament_id is not None and not await self._has_registration(session, tournament_id, auth_user.id):
            await assert_admitted_at(
                session,
                None,
                tournament_id=tournament_id,
                auth_user_id=auth_user.id,
                stage=AdmissionStage.registration,
            )
            gated = True

        team = await self._lock_team(session, invite.team_id)
        _assert_mutable(team)
        self._assert_unlocked(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, team.tournament_id)

        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)
        # ``offering=False``: this invite must not block its own acceptance.
        _check_slot(occupancy, invite.slot_code, is_substitute=bool(invite.is_substitute), offering=False)

        # A player who already registered solo is a FREE AGENT, not a duplicate: the
        # partial unique index allows one registration row per player per tournament,
        # so accepting *attaches* the existing row to the team. A second row would be
        # an `already_registered` 409 and, since withdrawal is final, would lock a solo
        # registrant out of every team.
        #
        # The submitted ``body`` is deliberately IGNORED on this path: the player
        # already answered the form, and the invite only decides which slot they
        # occupy. Their recorded roles and ranks stand.
        existing = await self._own_registration(session, team.tournament_id, auth_user.id)
        if existing is not None:
            if existing.status in _SLOT_RELEASING_STATUSES:
                # Withdrawn or rejected. Reviving it here would smuggle a re-entry past
                # the rule that withdrawal is final, which exists because a withdrawal
                # after check-in invalidates a composed roster.
                raise _fail(
                    409,
                    "registration_terminal",
                    "Your registration for this tournament is no longer active",
                )
            # Attach only a row on NO team, decided inside the UPDATE (see
            # ``attach_to_team_if_free``). Before the invite is consumed, so a refusal keeps it.
            if not await self.registration_repo.attach_to_team_if_free(
                session,
                existing.id,
                team_id=team.id,
                slot_code=invite.slot_code,
                is_substitute=bool(invite.is_substitute),
            ):
                raise _fail(409, "already_on_team", "You are already on a team in this tournament")
        elif not gated:
            # The registration seen before the lock is gone, so this accept would sign
            # up without having passed the gate. Rare (a concurrent delete); retrying
            # takes the gated path.
            raise _fail(409, "registration_changed", "Your registration changed; try again")

        # The guard: state and expiry are checked *in the UPDATE*, so two
        # simultaneous redemptions of one link cannot both win. ``consume_if_pending``
        # is that one conditional statement, decided by whether its RETURNING produced
        # a row — never split into a read-then-write.
        consumed = await self.invite_repo.consume_if_pending(
            session,
            invite.id,
            pending_state=INVITE_PENDING,
            accepted_state=INVITE_ACCEPTED,
            accepted_at=datetime.now(UTC),
        )
        if not consumed:
            await session.refresh(invite)
            raise _diagnose_dead_invite(invite)

        registration = existing or await self.registrations.write_public_registration(
            session,
            tournament_id=team.tournament_id,
            auth_user=auth_user,
            body=body,
            team_placement=TeamPlacement(
                registration_team_id=team.id,
                slot_code=invite.slot_code,
                is_substitute=bool(invite.is_substitute),
            ),
            commit=False,
        )
        identity = registration.primary_game_identity(provider=identity_provider(tournament.discipline))
        invite.accepted_registration_id = registration.id
        # Projected, not re-read: the new member's row is already flushed, but
        # computing the post-write status here keeps it inside the lock.
        _apply_occupancy_status(
            team,
            await self._occupancy(session, team, shape, max_substitutes=max_substitutes),
        )
        issues = await self._raise_if_ineligible(session, team, await self._roster_members(session, team.id), shape)
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await self._notify_invite_answered(
            session,
            team_id=team.id,
            team_name=team.name,
            tournament_id=team.tournament_id,
            workspace_id=team.workspace_id,
            captain_registration_id=team.captain_registration_id,
            invite_id=invite.id,
            answer="accepted",
            responder=auth_user,
            responder_name=(identity.handle if identity else None) or auth_user.username,
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            raise _fail(409, "already_registered", "You are already registered for this tournament") from exc
        return team, registration.id, issues

    async def decline_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        token: str | None = None,
        invite_id: int | None = None,
    ) -> None:
        """Refuse an offer, releasing its reserved slot back to the captain."""
        invite = await self._resolve_invite(session, auth_user=auth_user, token=token, invite_id=invite_id)
        if invite.state != INVITE_PENDING:
            raise _diagnose_dead_invite(invite)
        invite.state = INVITE_DECLINED
        # A narrow projection of the team, not a row fetch: the snapshot needs the
        # name the captain reads, the registration that identifies them, and the
        # tenant that owns the resulting notification.
        team_row = (
            await session.execute(
                sa.select(
                    models.RegistrationTeam.name,
                    models.RegistrationTeam.captain_registration_id,
                    models.RegistrationTeam.tournament_id,
                    models.RegistrationTeam.workspace_id,
                ).where(models.RegistrationTeam.id == invite.team_id)
            )
        ).one_or_none()
        if team_row is not None:
            # The game handle the captain picked them by, not the account handle:
            # a targeted invite was chosen off the free-agent list, which shows
            # exactly this. Accepting gets it for free off the registration it
            # just wrote; declining has to read it.
            tags = await self._handles_by_account(
                session,
                tournament_id=team_row.tournament_id,
                provider=await self._owner_provider(session, team_row.tournament_id),
                auth_user_ids={auth_user.id},
            )
            await self._notify_invite_answered(
                session,
                team_id=invite.team_id,
                team_name=team_row.name,
                tournament_id=team_row.tournament_id,
                workspace_id=team_row.workspace_id,
                captain_registration_id=team_row.captain_registration_id,
                invite_id=invite.id,
                answer="declined",
                responder=auth_user,
                responder_name=tags.get(auth_user.id) or auth_user.username,
            )
        await session.commit()

    # ── roster edits ─────────────────────────────────────────────────────────

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
        self._assert_unlocked(team)
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

    # ── organizer flows ──────────────────────────────────────────────────────

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

    # ── read models ──────────────────────────────────────────────────────────

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


# Imported here, not at the top: ``team_actions`` binds its methods onto the
# class defined above, so the module cannot be read before that class exists.
from src.services.registration.team_actions import install_team_actions  # noqa: E402

install_team_actions(RegistrationTeamService)

teams_service = RegistrationTeamService()
